"""Scoring: free rule-based heuristic (always available) + optional local LLM via Ollama.

Hybrid strategy (keeps CPU-only LLMs usable): heuristic ranks ALL candidates, the LLM re-scores only the
top-N, anything the LLM can't score falls back to its heuristic score.

P3.1 (UPDATED LOGIC): heuristic recalibrated against real live results - weak buying words no longer open the
"buying intent" gate, contributions are capped (no saturation), long posts / content marketing / job ads /
crypto promo are penalised, Unicode fancy fonts + curly quotes are normalised.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import unicodedata
import urllib.error
import urllib.request
from typing import Any, Protocol

from ..config import Settings
from ..models import Tweet
from .models import AgencyProfile, Candidate, LeadScore

log = logging.getLogger("leadsweep.scoring")

# --------------------------------------------------------------------------- rule tables
# trailing '*' = prefix match; everything else = whole word/phrase (after NFKC + lowercase normalisation)
INTENT_STRONG: dict[str, int] = {  # only these (or RFP terms) open the "buying intent" gate
    "looking for": 12, "we need": 10, "need a": 10, "need an": 10, "i need": 8, "hiring": 12, "seeking": 10,
    "who can": 10, "anyone know": 8, "any recommendations": 8, "recommend a": 8, "recommend an": 8, "budget": 10,
    "outsourc*": 10, "dm me": 4,
}
INTENT_WEAK: dict[str, int] = {"freelancer": 8, "agency": 8, "contractor": 8, "quote": 6, "paid": 4, "project": 4,
                              "expert": 4, "developer": 4, "build": 4}  # help only AFTER a strong signal exists
RFP_TERMS: dict[str, int] = {"rfp": 30, "request for proposal": 30, "request for quotation": 30, "tender": 15, "proposals due": 10}
SERVICE: dict[str, int] = {
    "ai agent*": 10, "automation": 8, "automate": 6, "llm": 8, "chatbot": 8, "scraper": 8, "scraping": 8, "n8n": 8,
    "langchain": 8, "langgraph": 8, "mcp": 6, "rag": 6, "workflow*": 4, "integration*": 4, "openai": 4, "claude": 4,
    "ai developer": 12, "ai engineer": 10, "llm developer": 12, "ml engineer": 8, "computer vision": 8,
    "data pipeline*": 6, "data extraction": 6, "mvp": 6, "agentic": 6,
}
NEGATIVE_HARD: dict[str, int] = {  # authors selling/seeking JOBS are competitors, not buyers -> forced noise
    "open to work": -35, "#opentowork": -35, "available for hire": -35, "hire me": -35, "looking for work": -30,
    "looking for a job": -30, "my services": -25, "i offer": -20, "we offer": -20, "i build": -10, "i can build": -20,
}
PENALTY_SOFT: dict[str, int] = {  # job ads + content marketing: lower the score, don't force noise (capped at -40)
    "full-time": -15, "full time": -15, "apply now": -15, "join our team": -15, "salary": -10, "equity": -10,
    "thread": -10, "🧵": -10, "here's how": -10, "how to": -10, "tips": -10, "step-by-step": -10, "newsletter": -10,
    "subscribe": -10, "free course": -10, "waitlist": -10, "link in bio": -10, "introducing": -10,
    "just launched": -10, "we built": -10, "sign up": -10,
}
SPAM_HARD = ["airdrop", "presale", "giveaway", "memecoin", "100x", "whitelist"]  # dropped before scoring (lead/rfp queries)
SPAM_SOFT = ["nft", "web3", "defi", "mint", "pump", "tokenomics", "onchain", "on-chain", "crypto", "token2049"]
LENGTH_CAP_CHARS, LENGTH_CAP_SCORE, LENGTH_DAMP_CHARS = 600, 55, 300
SCALE = 1.8


def _compile(terms: dict[str, int]) -> list[tuple[str, int, re.Pattern[str]]]:
    out = []
    for term, w in terms.items():
        if term.endswith("*"):
            pat = r"(?<!\w)" + re.escape(term[:-1])
        else:
            pat = r"(?<!\w)" + re.escape(term) + r"(?!\w)"
        out.append((term.rstrip("*"), w, re.compile(pat)))
    return out


_STRONG, _WEAK, _RFP = _compile(INTENT_STRONG), _compile(INTENT_WEAK), _compile(RFP_TERMS)
_SERVICE, _HARD, _SOFT = _compile(SERVICE), _compile(NEGATIVE_HARD), _compile(PENALTY_SOFT)
_SPAM_HARD = re.compile(r"(?<!\w)(" + "|".join(map(re.escape, SPAM_HARD)) + r")(?!\w)")
_SPAM_SOFT = re.compile(r"(?<!\w)(" + "|".join(map(re.escape, SPAM_SOFT)) + r")(?!\w)")
_CASHTAG = re.compile(r"(?<!\w)\$[a-z]{2,10}(?!\w)")  # $NEAR, $MSFT ... ($3k / $120 are not matched)


def norm(text: str) -> str:
    """NFKC folds fancy Unicode fonts (𝗕𝗔𝗡𝗚𝗘𝗥 -> BANGER); also unescape HTML, straighten quotes, lowercase."""
    t = unicodedata.normalize("NFKC", html.unescape(text)).replace("’", "'").replace("‘", "'")
    return " ".join(t.lower().split())


def _hits(rules: list[tuple[str, int, re.Pattern[str]]], text: str) -> list[tuple[str, int]]:
    return [(name, w) for name, w, rx in rules if rx.search(text)]


def prefilter_reason(t: Tweet, query_type: str) -> str | None:
    """Cheap drops BEFORE scoring. Returns the reason or None to keep."""
    if t.is_retweet:
        return "retweet"
    text = norm(t.text)
    if len(text) < 25:
        return "too_short"
    if query_type in ("lead", "rfp") and _SPAM_HARD.search(text):
        return "spam"
    return None


def heuristic_score(c: Candidate, profile: AgencyProfile) -> LeadScore:
    t = c.tweet
    text = norm(t.text)
    n = len(text)
    strong, weak, rfp = _hits(_STRONG, text), _hits(_WEAK, text), _hits(_RFP, text)
    service, hard, soft = _hits(_SERVICE, text), _hits(_HARD, text), _hits(_SOFT, text)
    known = {name for name, _ in service}
    extra = [s.lower() for s in profile.services if s.lower() in text and s.lower() not in known]
    spammy = bool(_SPAM_SOFT.search(text) or _CASHTAG.search(text))

    service_raw = sum(w for _, w in service) + 6 * len(extra)
    signals = [nm for nm, _ in rfp + strong + service][:6] + extra[:2]

    if c.query_type == "trend":
        engagement = min(30, (t.like_count + 3 * t.retweet_count + (t.view_count or 0) // 1000) // 4)
        score = (min(60, service_raw * 2.5) + engagement) if service_raw else 0
        if spammy:
            score -= 40  # token/crypto promotion is not an industry trend
        score = int(max(0, min(100, score)))
        return LeadScore(
            score=score, category="trend" if score >= 40 else "noise", intent_signals=signals,
            reason=f"heuristic trend: service={[nm for nm, _ in service]}, engagement={engagement}, promo_penalty={spammy}",
            suggested_action="Consider content/outreach angle on this trend" if score >= 40 else "",
        )

    soft_pen = max(-40, sum(w for _, w in soft))
    raw = (min(30, sum(w for _, w in strong)) + min(10, sum(w for _, w in weak)) + min(24, service_raw)
           + min(30, sum(w for _, w in rfp)) + sum(w for _, w in hard))
    score = raw * SCALE + soft_pen - (25 if spammy else 0)
    if not ((strong or rfp) and (service or extra)):
        score = min(score, 30)  # need a REAL buying signal AND a relevant service term
    if n > LENGTH_CAP_CHARS and not rfp:
        score = min(score, LENGTH_CAP_SCORE)  # long posts are essays/marketing, rarely a client request
    elif n > LENGTH_DAMP_CHARS:
        score *= 0.85
    score = int(max(0, min(100, score)))

    # NEW FEATURE: Lead-Direction Layer (LEAD_INTEL / QUERY_INTELLIGENCE)
    if os.getenv("LEAD_INTEL", "on").lower() in ("on", "true", "1", "yes") or os.getenv("QUERY_INTELLIGENCE", "on").lower() in ("on", "true", "1", "yes"):
        try:
            from leadsweep.leadintel.lead_quick import direction_gate, apply_direction_cap
            dir_res = direction_gate(text)
            capped_score = apply_direction_cap(score, dir_res["label"])
            if capped_score < score:
                score = capped_score
                if dir_res["label"] in ("JOB_SEEKER", "SERVICE_PROVIDER_PROMO", "AIRDROP_BOT_SPAM"):
                    category = "noise"
        except Exception:
            pass

    category = "noise" if (hard or score < 25) else ("rfp" if rfp else "lead")

    # Format natural, client-ready buying intent insight
    intent_terms = [nm for nm, _ in rfp + strong]
    service_terms = [nm for nm, _ in service] + extra
    if category in ("lead", "rfp"):
        if intent_terms and service_terms:
            readable_reason = f"Actively seeking {', '.join(service_terms[:3])} services with direct hiring intent ('{', '.join(intent_terms[:2])}')."
        elif service_terms:
            readable_reason = f"High-intent requirement detected for {', '.join(service_terms[:3])} development and workflow automation."
        elif intent_terms:
            readable_reason = f"Explicit procurement / contractor request: '{', '.join(intent_terms[:2])}'."
        else:
            readable_reason = "Qualified opportunity matching target agency automation and development capabilities."
    elif category == "trend":
        readable_reason = f"Industry discussion around {', '.join(service_terms[:3]) if service_terms else 'automation tools'} with high audience engagement."
    else:
        readable_reason = "Educational, promotional, or general commentary with no explicit buying or hiring intent."

    return LeadScore(
        score=score, category=category, intent_signals=signals,
        reason=readable_reason,
        suggested_action="Reply/DM with a relevant case study" if category in ("lead", "rfp") else "",
    )



# --------------------------------------------------------------------------- LLM scoring
class Scorer(Protocol):
    label: str

    async def score(self, c: Candidate, profile: AgencyProfile) -> LeadScore: ...


SYSTEM_PROMPT = """You are a business-development analyst for an AI & automation agency.
Agency services: {services}
Ideal clients: {clients}

Judge ONE X/Twitter post and answer using the required JSON schema.
Categories:
- lead: the author is a potential BUYER actively seeking to hire/outsource work matching the services.
- rfp: an explicit project brief, RFP, tender or budgeted scope.
- trend: an informative post about a relevant AI/automation industry development (never token or product promotion).
- noise: everything else - people advertising their own services, job seekers, promotions, ads, content marketing and threads, crypto/NFT/web3/token posts, giveaways, generic opinions.
Rules: developers/freelancers offering or seeking jobs are competitors, NOT leads (noise, score <= 20).
Full-time employee job ads are weak leads (score <= 50) unless they mention contract, freelance or outsourcing.
Score 0-100: 90+ explicit buyer with budget or urgency; 70-89 clear buyer intent; 40-69 weak or ambiguous; below 40 noise. Be strict.
This post was found by a "{qtype}" search ("{qname}")."""


def build_messages(c: Candidate, profile: AgencyProfile) -> list[tuple[str, str]]:
    t = c.tweet
    system = SYSTEM_PROMPT.format(
        services="; ".join(profile.services) or "AI and automation development",
        clients="; ".join(profile.ideal_clients) or "businesses adopting AI",
        qtype=c.query_type, qname=",".join(c.queries),
    )
    human = (f"Author: @{t.author_username} ({t.author_followers} followers)\n"
             f"Engagement: {t.like_count} likes, {t.retweet_count} reposts, {t.view_count} views\n"
             f"Post:\n{html.unescape(t.text)[:800]}")
    return [("system", system), ("human", human)]


class GroqScorer:
    def __init__(self, model: str, api_key: str, chain: Any | None = None) -> None:
        self.model, self.api_key, self._chain = model, api_key, chain
        self.label = f"groq:{model}"

    def _get_chain(self) -> Any:
        if self._chain is None:
            try:
                from langchain_groq import ChatGroq
            except ImportError:
                raise RuntimeError("Missing 'langchain-groq'. Run: pip install langchain-groq")
            # max_tokens=250 ensures concise structured output within Groq token-per-minute limits
            self._chain = ChatGroq(model=self.model, api_key=self.api_key, temperature=0, max_tokens=250).with_structured_output(LeadScore)
        return self._chain

    async def score(self, c: Candidate, profile: AgencyProfile) -> LeadScore:
        out = await self._get_chain().ainvoke(build_messages(c, profile))
        if isinstance(out, LeadScore):
            return out
        if isinstance(out, dict):
            return LeadScore.model_validate(out)
        raise ValueError(f"LLM returned no structured output ({type(out).__name__})")



class OllamaScorer:
    def __init__(self, model: str, base_url: str, chain: Any | None = None) -> None:
        self.model, self.base_url, self._chain = model, base_url, chain
        self.label = f"ollama:{model}"

    def _get_chain(self) -> Any:
        if self._chain is None:
            try:  # lazy: only needed when the LLM is used
                from langchain_ollama import ChatOllama
            except ImportError:
                raise RuntimeError("Missing 'langchain-ollama'. Run: python -m scripts.doctor --install")
            self._chain = ChatOllama(model=self.model, base_url=self.base_url, temperature=0, num_ctx=4096).with_structured_output(LeadScore)
        return self._chain

    async def score(self, c: Candidate, profile: AgencyProfile) -> LeadScore:
        out = await self._get_chain().ainvoke(build_messages(c, profile))
        if isinstance(out, LeadScore):
            return out
        if isinstance(out, dict):
            return LeadScore.model_validate(out)
        raise ValueError(f"LLM returned no structured output ({type(out).__name__})")


def _ollama_hint(detail: str, model: str) -> str:
    if "llama-server" in detail or "runner" in detail.lower():
        return (f"Ollama is running but cannot start its model runner (broken/incomplete install). Reinstall: "
                f"curl -fsSL https://ollama.com/install.sh | sh   then test: ollama run {model} \"hi\"")
    return f"Ollama could not run '{model}': {detail[:160]}"


def ollama_ready(base_url: str, model: str, timeout: float = 3.0, probe: bool = True, probe_timeout: float = 180.0) -> tuple[bool, str]:
    """UPDATED LOGIC (P3.1): also runs a 1-token test generation, because /api/tags answering does NOT prove models can load."""
    base = base_url.rstrip("/")
    try:
        with urllib.request.urlopen(base + "/api/tags", timeout=timeout) as r:
            names = [m.get("name", "") for m in json.load(r).get("models", [])]
    except Exception as e:  # noqa: BLE001
        return False, f"Ollama not reachable at {base_url} ({type(e).__name__}); start it with `ollama serve`"
    if not (model in names or (":" not in model and f"{model}:latest" in names)):
        return False, f"Ollama running but model '{model}' not pulled; run `ollama pull {model}` (have: {names[:6]})"
    if probe:
        req = urllib.request.Request(
            base + "/api/generate", method="POST", headers={"Content-Type": "application/json"},
            data=json.dumps({"model": model, "prompt": "Reply with OK", "stream": False, "options": {"num_predict": 1}}).encode())
        try:
            with urllib.request.urlopen(req, timeout=probe_timeout) as r:
                r.read()
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read().decode()).get("error", "")
            except Exception:  # noqa: BLE001
                detail = str(e)
            return False, _ollama_hint(detail, model)
        except Exception as e:  # noqa: BLE001
            return False, f"Ollama test generation failed ({type(e).__name__}: {e}); model may be too slow - raise probe timeout or use a smaller model"
        return True, f"Ollama OK, model '{model}' loaded and answering"
    return True, f"Ollama OK, model '{model}' available (not probed)"


async def pick_scorer(preference: str, s: Settings) -> tuple[Scorer | None, str]:
    """Returns (scorer or None for heuristic-only, human-readable label).

    Supports 'groq', 'ollama', 'heuristic', or 'auto' (checks Groq first, then Ollama, falls back to heuristic).
    """
    if preference == "heuristic":
        return None, "heuristic (forced)"

    # Groq explicit selection
    if preference == "groq":
        key = s.groq_api_key
        if not key:
            raise RuntimeError("LEADSWEEP_GROQ_API_KEY is not set.")
        model = s.groq_model or "openai/gpt-oss-120b"
        return GroqScorer(model=model, api_key=key), f"groq:{model}"

    # Auto mode: Prioritise Groq if key is present, otherwise try Ollama, then heuristic
    if preference == "auto":
        if s.groq_api_key:
            model = s.groq_model or "openai/gpt-oss-120b"
            return GroqScorer(model=model, api_key=s.groq_api_key), f"groq:{model}"
        ok, msg = await asyncio.to_thread(ollama_ready, s.ollama_url, s.llm_model)
        if ok:
            return OllamaScorer(s.llm_model, s.ollama_url), f"ollama:{s.llm_model}"
        return None, f"heuristic (auto fallback: {msg})"

    # Ollama explicit selection
    if preference == "ollama":
        ok, msg = await asyncio.to_thread(ollama_ready, s.ollama_url, s.llm_model)
        if ok:
            return OllamaScorer(s.llm_model, s.ollama_url), f"ollama:{s.llm_model}"
        raise RuntimeError(msg)

    return None, "heuristic"

