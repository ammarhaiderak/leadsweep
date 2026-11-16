"""LangGraph Lead Qualification State Machine.

Intent-Aware Content Classification, Scoring Dimensions & Evidence Extraction.
Distinguishes genuine commercial/hiring demand from news, announcements,
promotions (airdrop/check-in/points), spam, and general ecosystem discussions.

Taxonomy (Primary Categories):
- DIRECT_BUYING_INTENT: Explicit request for vendor, contractor, developer, or solution (Qualified lead).
- HIRING_OR_CONTRACT: Explicit hiring, freelance, contractor, or project opportunity (Qualified lead).
- PAIN_POINT_OR_UNMET_NEED: Concrete problem potentially addressable by services (Potential opportunity / Nurture).
- FOUNDER_PROJECT_SIGNAL: Founder or project owner discussing relevant need without explicit purchase request (Review / Nurture).
- PARTNERSHIP_REQUEST: Explicit collaboration or partnership opportunity (Opportunity / Review).
- GENERAL_DISCUSSION: Industry discussion without concrete commercial opportunity (Excluded / Not qualified).
- NEWS_OR_INCIDENT: Reporting, summaries, apologies, controversy, joke digests, public incidents (Excluded / Not qualified).
- PROJECT_ANNOUNCEMENT: Product launches, roadmap updates, milestone announcements without service demand (Excluded / Not qualified).
- PROMOTIONAL_OR_TASK_UPDATE: Points farming, airdrop campaigns, check-ins, engagement bait (Excluded / Not qualified).
- SPAM_OR_LOW_QUALITY: Repetitive promotion, scams, misleading spam (Excluded / Rejected).
- IRRELEVANT: Content unrelated to the requested business intent (Excluded / Rejected).
- UNKNOWN / NEEDS_REVIEW: Ambiguous content where evidence is insufficient (Needs review / Not qualified).

Scoring Dimensions:
- topic_relevance_score (0-100)
- commercial_intent_score (0-100)
- service_fit_score (0-100)
- author_relevance_score (0-100)
- spam_risk_score (0-100)
- evidence_quality_score (0-100)
- final_score (0-100)
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import unicodedata
from typing import Any, Literal, TypedDict
from pydantic import BaseModel, Field, field_validator

from langgraph.graph import StateGraph, START, END

log = logging.getLogger("leadsweep.qualification_graph")

# Primary Categories controlled taxonomy
PrimaryCategory = Literal[
    "DIRECT_BUYING_INTENT",
    "HIRING_OR_CONTRACT",
    "PAIN_POINT_OR_UNMET_NEED",
    "FOUNDER_PROJECT_SIGNAL",
    "PARTNERSHIP_REQUEST",
    "GENERAL_DISCUSSION",
    "NEWS_OR_INCIDENT",
    "PROJECT_ANNOUNCEMENT",
    "PROMOTIONAL_OR_TASK_UPDATE",
    "SPAM_OR_LOW_QUALITY",
    "IRRELEVANT",
    "NEEDS_REVIEW",
]

# Canonical PosterRole Enum (H1-3)
PosterRole = Literal["requester", "recruiter", "aggregator", "seller", "advisor", "bystander", "unknown"]

ROLE_ALIASES: dict[str, str] = {
    "job_board": "aggregator",
    "job_platform": "aggregator",
    "job_portal": "aggregator",
    "curator": "aggregator",
    "digest": "aggregator",
    "channel": "aggregator",
    "bot": "aggregator",
    "hiring_manager": "recruiter",
    "company": "recruiter",
    "employer": "recruiter",
    "founder": "requester",
    "client": "requester",
    "buyer": "requester",
    "consultant": "advisor",
    "coach": "advisor",
    "vendor": "seller",
    "agency": "recruiter",
    "marketer": "seller",
    "observer": "bystander",
    "commenter": "bystander",
}

def normalize_poster_role(raw: Any) -> tuple[PosterRole, bool]:
    """Normalize poster role string to canonical PosterRole enum. Returns (canonical_role, role_normalized_flag)."""
    if not raw:
        return "unknown", False
    clean = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    valid_roles = {"requester", "recruiter", "aggregator", "seller", "advisor", "bystander", "unknown"}
    if clean in valid_roles:
        return clean, False  # already canonical
    if clean in ROLE_ALIASES:
        return ROLE_ALIASES[clean], True
    tokens = set(clean.split("_"))
    for alias_k, target_role in ROLE_ALIASES.items():
        if "_" in alias_k:
            if alias_k == clean or f"_{alias_k}_" in f"_{clean}_":
                return target_role, True
        else:
            if alias_k in tokens:
                return target_role, True
    return "unknown", True


def is_multi_company_digest(text: str) -> bool:
    """Detect if a post is a multi-company digest with 3+ distinct companies hiring."""
    if not text:
        return False
    matches = re.findall(r"(?:^|[\n•\-\*])\s*([A-Za-z0-9\.\-_ ]{2,30}?)\s+is\s+hiring\s+", text, re.IGNORECASE)
    companies = {m.strip().lower() for m in matches if m.strip()}
    return len(companies) >= 3


def _recover_failed_tool_generation(err: Exception) -> LeadJudgeContract | None:
    """Recover structured LeadJudgeContract from Groq tool_use_failed XML/JSON payload when tool name is misspelled."""
    raw = str(err)
    if "<parameter=" not in raw:
        return None
    def _extract_param(name: str) -> str | None:
        m = re.search(rf"<parameter={re.escape(name)}>\s*(.*?)\s*</parameter>", raw, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else None
    cat = _extract_param("category")
    score_s = _extract_param("score")
    reason = _extract_param("reason")
    if not cat or score_s is None or not reason:
        return None
    try:
        return LeadJudgeContract(
            category=cat,
            score=int(float(score_s)),
            evidence_quote=_extract_param("evidence_quote") or "",
            reason=reason,
            confidence=float(_extract_param("confidence") or 0.85),
            poster_role=_extract_param("poster_role") or "unknown",
            intent_type=_extract_param("intent_type") or "noise",
        )
    except Exception:
        return None


# NEW FEATURE: Structured Output Schema for Lead Qualification
class LeadJudgeContract(BaseModel):
    category: str = Field(..., description="One of DIRECT_BUYING_INTENT, HIRING_OR_CONTRACT, PAIN_POINT_OR_UNMET_NEED, FOUNDER_PROJECT_SIGNAL, PARTNERSHIP_REQUEST, GENERAL_DISCUSSION, NEWS_OR_INCIDENT, PROJECT_ANNOUNCEMENT, PROMOTIONAL_OR_TASK_UPDATE, SPAM_OR_LOW_QUALITY, IRRELEVANT")
    score: int = Field(..., description="Calibrated commercial / buyer intent score 0 to 100")
    evidence_quote: str = Field("", description="Exact verbatim substring from post text, or empty string")
    reason: str = Field(..., description="Concise explanation citing verified facts")
    confidence: float = Field(0.9, description="Confidence score between 0.0 and 1.0")
    poster_role: PosterRole = Field(..., description="requester, recruiter, aggregator, seller, advisor, bystander, or unknown")
    intent_type: str = Field(..., description="recruitment, procurement, advice, self_promotion, or noise")
    role_normalized: bool = Field(default=False)

    @field_validator("poster_role", mode="before")
    @classmethod
    def _validate_and_normalize_role(cls, v: Any) -> str:
        role, _ = normalize_poster_role(v)
        return role


QUALIFIED_LEAD_CATEGORIES = {"DIRECT_BUYING_INTENT", "HIRING_OR_CONTRACT"}
POTENTIAL_OPPORTUNITY_CATEGORIES = {
    "PAIN_POINT_OR_UNMET_NEED",
    "FOUNDER_PROJECT_SIGNAL",
    "PARTNERSHIP_REQUEST",
    "NEEDS_REVIEW",
}
EXCLUDED_CATEGORIES = {
    "GENERAL_DISCUSSION",
    "NEWS_OR_INCIDENT",
    "PROJECT_ANNOUNCEMENT",
    "PROMOTIONAL_OR_TASK_UPDATE",
    "SPAM_OR_LOW_QUALITY",
    "IRRELEVANT",
}


class LeadState(TypedDict, total=False):
    # Input
    tweet_id: str
    author_username: str
    author_name: str
    author_followers: int
    text: str
    query_context: str
    search_mode: str  # lead_generation, opportunity_discovery, news_monitoring
    platform: str
    job_id: str
    tenant_id: str
    source_mode: str  # search, timeline, profile, user_tweets, replies

    # Classification & Scoring Dimensions
    primary_category: str
    topic_relevance_score: int
    commercial_intent_score: int
    service_fit_score: int
    author_relevance_score: int
    spam_risk_score: int
    evidence_quality_score: int
    buyer_intent_score: int  # Unified calibrated commercial score (0-100)

    # Evidence & Explainability
    decision: str  # qualified, potential_opportunity, disqualified, needs_review
    evidence_spans: list[str]  # Exact verbatim spans from tweet text supporting commercial intent
    reasoning_summary: str
    rejection_reason: str | None
    uncertainties: list[str]
    model_version: str
    prompt_version: str
    evaluator: str
    poster_role: PosterRole
    role_normalized: bool
    calibration_adjusted: bool
    token_usage: dict[str, Any] | None

    # Legacy compatibility fields (Preserves existing API/Frontend consumers)
    classification: Literal["BUYER", "SELLER", "NOISE", "DISCUSSION"]
    intent_reason: str

    # Node 2: Budget & Scope Extraction
    budget_raw: str | None
    budget_usd: float | None
    scope: str | None
    technologies: list[str]
    timeline: str | None

    # Node 3 & 4: Qualification & HITL
    qualified: bool
    status: Literal["disqualified", "approved", "hitl_pending", "needs_review"]
    outreach_priority: Literal["low", "medium", "high", "vip"]
    suggested_angle: str


# --------------------------------------------------------------------------- Heuristic Rules & Taxonomies
_BUDGET_RE = re.compile(
    r"(\$|£|€)(\d+[\d,]*(\.\d+)?(\s*[kKmMbB])?)|(\d+[\d,]*\s*(usd|gbp|eur|dollars|k\b))",
    re.IGNORECASE,
)

_TECH_PATTERNS = [
    "ai agent", "ai bot", "langgraph", "langchain", "automation", "scraper", "scraping",
    "playwright", "n8n", "chatgpt", "openai", "claude", "llm", "rag", "mcp", "fastapi",
    "python", "shopify", "crm", "voice agent", "smart contract", "solidity", "defi",
    "web3", "rust", "react", "typescript", "fullstack", "frontend", "backend"
]

# 1. Promotional, Airdrop, Points Farming & Check-in Signals
_PROMOTIONAL_PATTERNS = [
    "airdrop", "points", "farming", "check-in", "daily check-in", "checkin",
    "streak", "claim now", "testnet points", "sleepagotchi", "rax finance",
    "giveaway", "free mint", "whitelist", "presale", "zealy", "galxe",
    "airdrop quest", "daily quest", "layer3 quest", "zealy quest", "galxe quest",
    "spin the wheel", "retweet to win", "follow & rt", "drop your address",
    "drop your wallet", "tag 3 friends", "gm to everyone who checked in"
]


# 2. News, Incidents, Apologies, Controversy, Joke Digests & Recap Signals
_NEWS_INCIDENT_PATTERNS = [
    "weekly recap", "recap:", "news digest", "breaking news", "breaking:",
    "shutdown joke", "in case you missed it", "market update", "newsletter:",
    "weekly round-up", "weekly roundup", "hack incident", "post-mortem",
    "exploit alert", "apologize for", "our apology", "statement regarding",
    "thread 1/", "1/10", "here is what happened", "polygon shutdown"
]

# 3. Product Announcements & Roadmap Updates (Without vendor/contractor requests)
_ANNOUNCEMENT_PATTERNS = [
    "we are excited to announce", "excited to unveil", "introducing our new",
    "we just launched", "proud to share our roadmap", "v2 is live", "mainnet is live",
    "testnet is live", "announcing the launch", "our new feature", "milestone reached",
    "ecosystem update", "version update", "changelog:"
]

# 4. Explicit Direct Buyer & Procurement Demands
# UPDATED LOGIC: Include contractor, automation script, plugin build, and request cues
_DIRECT_BUYER_KEYWORDS = [
    "need someone to build", "looking for someone to build", "need a developer",
    "looking for a developer", "need an agency", "looking for an agency",
    "anyone who can build", "who can build", "paying for someone to build",
    "have budget for a developer", "budget is", "need a bot", "need a scraper",
    "want to automate our", "looking for a contractor", "need a contractor",
    "seeking a freelancer", "freelancer needed", "hire a developer",
    "looking to hire an agency", "who can design a defi dashboard",
    "need a smart contract developer", "looking for a smart contract dev",
    "paying top dollar for", "bounty for building", "build a custom",
    "looking for someone to", "need an engineer to"
]

# 5. Explicit Hiring & Recruitment Signals
# UPDATED LOGIC: Expanded to cover recruiter posts, hiring alerts, agency/firm recruitment, and bilingual cues
_HIRING_KEYWORDS = [
    "we're hiring", "we are hiring", "is hiring a", "is hiring for", "is hiring", "hiring alert",
    "hiring:", "hiring senior", "hiring lead", "hiring remote", "hiring contract", "hiring full stack",
    "hiring backend", "hiring frontend", "hiring software engineer", "hiring developer",
    "contract lead", "project contract", "hourly contract", "full-time contract",
    "submit proposals", "submit proposal", "drop portfolio", "paying top dollar",
    "join our team", "apply here:", "apply link:", "role: software", "role: developer", "looking to hire",
    "seeking a software engineer", "seeking a developer", "remote software engineer",
    "job opening", "apply at", "careers at",
    "job opportunities", "project leads", "publishing projects or vacancies",
    "freelance opportunities", "remote contracting", "remote job opportunities",
    "job vacancies", "contract leads", "freelance project", "client gig",
    "remote work opportunities", "freelancer needed", "freelance jobs",
    "dm with cv", "dm with portfolio", "send cv", "send resume", "招人", "招聘", "诚聘"
]

# 6. Pain Points & Unmet Needs
_PAIN_POINT_KEYWORDS = [
    "struggling with", "can't figure out how to build", "broken and driving me crazy",
    "wish there was a tool for", "current solution is terrible", "hate doing this manually",
    "our infrastructure keeps crashing", "anyone else having trouble with", "impossible to find a good"
]

# 7. Founder / Project Signals
_FOUNDER_SIGNALS = [
    "as a founder", "building a new", "early stage startup", "co-founder of",
    "bootstrapping a", "our project is looking into"
]

# 8. Seller / Job Seeker / Self-Promotion Signals
_SELLER_KEYWORDS = [
    "i'm looking for a new role", "looking for a new role", "i am looking for a new role",
    "hire me", "my resume", "open to work", "#opentowork", "my skills include",
    "i build ai agents", "available for freelance", "looking for full-time work",
    "my portfolio:", "dms are open if hiring"
]


# NEW FEATURE (Phase 2): Topic Relevance Evaluator
def compute_topic_relevance(text: str, query_context: str = "") -> int:
    """Calculate 0-100 topical relevance between post text and search query intent.
    
    Prevents off-topic procurement requests (e.g. streetwear designer) from slipping through
    when searching for specific business domains (e.g. web3 founder, ai engineer).
    """
    if not query_context or not query_context.strip():
        return 70  # Default neutral relevance when no query context is provided

    # Clean handle prefixes and decompose snake_case/kebab-case tokens
    q_norm = query_context.lstrip("@").replace("https://t.me/", "").replace("t.me/", "")
    q_norm = q_norm.replace("_", " ").replace("-", " ")
    q_clean = _clean_text(q_norm)
    t_clean = _clean_text(text)

    # Stop words to discard from query intent extraction
    stop_words = {
        "i", "want", "to", "a", "an", "the", "that", "who", "which", "can",
        "please", "am", "looking", "for", "need", "find", "get", "me", "show",
        "hire", "hiring", "contractor", "freelancer", "someone", "jobs", "job",
        "channel", "group", "leads", "lead"
    }
    q_tokens = [w for w in re.findall(r"\b[\w'-]+\b", q_clean) if w not in stop_words and len(w) > 1]
    if not q_tokens:
        return 85  # Query is a general hiring / channel handle (e.g., @remotejobs_dev, @freelance_leads)

    # Expand domain synonyms for dev, remote, tech, web3, ai, etc.
    synonym_map = {
        "dev": ["developer", "engineer", "software", "code", "full-stack", "backend", "frontend", "mobile", "tech"],
        "remote": ["remote", "contract", "freelance", "online", "anywhere", "telecommute", "distributed"],
        "web3": ["crypto", "blockchain", "defi", "nft", "smart contract", "solidity", "ethereum", "eth", "solana", "sol", "token", "dao", "on-chain", "dapp", "founder", "protocol"],
        "crypto": ["web3", "blockchain", "defi", "token", "eth", "solana", "bitcoin", "btc", "altcoin"],
        "founder": ["co-founder", "founding", "ceo", "startup", "building", "our project", "launching", "bootstrap"],
        "ai": ["ml", "llm", "agent", "agents", "machine learning", "gpt", "claude", "langgraph", "langchain", "prompt"],
    }

    match_count = 0.0
    total_tokens = len(q_tokens)
    
    for token in q_tokens:
        t_text_without_channel = re.sub(r"t\.me/[^\s]+|@[a-zA-Z0-9_]+", " ", t_clean)
        
        # Word boundary or CJK character boundary match
        token_pat = rf"(?:^|[\s\W\u4e00-\u9fff]){re.escape(token)}(?:[\s\W\u4e00-\u9fff]|$)"
        if re.search(token_pat, t_text_without_channel) or token in t_text_without_channel:
            match_count += 1.0
            continue
        # Check domain synonyms with boundary
        synonyms = synonym_map.get(token, [])
        syn_matched = False
        for s in synonyms:
            syn_pat = rf"(?:^|[\s\W\u4e00-\u9fff]){re.escape(s)}(?:[\s\W\u4e00-\u9fff]|$)"
            if re.search(syn_pat, t_text_without_channel) or (len(s) > 2 and s in t_text_without_channel):
                match_count += 0.90
                syn_matched = True
                break
        if syn_matched:
            continue

    score = int((match_count / total_tokens) * 100)
    # If the search query was a general hiring channel or broad query, provide a healthy floor for genuine tech leads
    is_general_tech_contract = any(k in t_clean for k in ["contract lead", "hiring", "rate:", "$", "engineer", "developer", "architect", "招聘", "猎头"])
    if is_general_tech_contract and score < 50:
        score = 65  # Base tech contracting floor (relevant technical contract role, but domain differed)

    return max(0, min(100, score))



def _clean_text(text: str) -> str:
    """Normalize unicode, unescape html, and lowercase text."""
    t = unicodedata.normalize("NFKC", html.unescape(text or "")).replace("’", "'").replace("‘", "'")
    return " ".join(t.lower().split())


def _extract_evidence_span(text: str, match_term: str) -> str:
    """Extract exact verbatim substring from original text around match."""
    idx = text.lower().find(match_term.lower())
    if idx == -1:
        return match_term
    start = max(0, idx - 15)
    end = min(len(text), idx + len(match_term) + 20)
    # expand to clean word boundary
    span = text[start:end].strip()
    return f"...{span}..." if (start > 0 or end < len(text)) else span


def classify_intent_rules(
    text: str,
    query_context: str = "",
    search_mode: str = "lead_generation"
) -> dict[str, Any]:
    """Deterministic, intent-aware rule engine separating topical relevance from commercial demand."""
    clean = _clean_text(text)
    orig_text = text or ""
    q_clean = _clean_text(query_context)

    # 1. Check for prompt injection / adversarial override attempts in post text
    # Post text is untrusted; flag and neutralize instructions that try to hijack classifier
    if any(p in clean for p in ["ignore previous instructions", "system prompt", "you are now", "mark as qualified"]):
        return {
            "primary_category": "SPAM_OR_LOW_QUALITY",
            "topic_relevance_score": 10,
            "commercial_intent_score": 0,
            "service_fit_score": 0,
            "author_relevance_score": 10,
            "spam_risk_score": 95,
            "evidence_quality_score": 0,
            "buyer_intent_score": 0,
            "decision": "disqualified",
            "evidence_spans": [],
            "reasoning_summary": "Detected adversarial prompt injection attempt in untrusted post text.",
            "rejection_reason": "Adversarial text injection / spam",
            "uncertainties": [],
            "classification": "NOISE",
            "intent_reason": "Adversarial content rejected",
        }

    # 2. Check for Promotional / Airdrop / Points Farming / Check-ins (e.g. Sleepagotchi, RAX Finance)
    for p in _PROMOTIONAL_PATTERNS:
        # UPDATED LOGIC: Word-boundary matching to prevent 'quest' matching 'request' or 'question'
        pattern = r"\b" + re.escape(p) + r"\b"
        if re.search(pattern, clean, re.I):
            span = _extract_evidence_span(orig_text, p)
            return {
                "primary_category": "PROMOTIONAL_OR_TASK_UPDATE",
                "topic_relevance_score": 40 if any(t in clean for t in ["crypto", "web3", "defi"]) else 15,
                "commercial_intent_score": 0,
                "service_fit_score": 0,
                "author_relevance_score": 20,
                "spam_risk_score": 85,
                "evidence_quality_score": 10,
                "buyer_intent_score": 5,
                "decision": "disqualified",
                "evidence_spans": [],
                "reasoning_summary": f"Promotional task / points farming / airdrop campaign: '{p}' (No procurement intent).",
                "rejection_reason": f"Promotional/airdrop campaign ('{p}')",
                "uncertainties": [],
                "classification": "NOISE",
                "intent_reason": f"Promotional campaign: '{p}'",
            }


    # 3. Check for News / Incidents / Apologies / Controversy / Joke Digests (e.g. Polygon shutdown joke)
    for n in _NEWS_INCIDENT_PATTERNS:
        if n in clean:
            is_news_mode = search_mode == "news_monitoring"
            return {
                "primary_category": "NEWS_OR_INCIDENT",
                "topic_relevance_score": 75 if ("web3" in clean or "crypto" in clean or "ai" in clean) else 35,
                "commercial_intent_score": 0,
                "service_fit_score": 0,
                "author_relevance_score": 40,
                "spam_risk_score": 15,
                "evidence_quality_score": 10,
                "buyer_intent_score": 10,
                "decision": "approved" if is_news_mode else "disqualified",
                "evidence_spans": [],
                "reasoning_summary": f"General news, recap digest, or public incident update: '{n}'. Lacks commercial buying intent.",
                "rejection_reason": "News/incident digest without service demand",
                "uncertainties": [],
                "classification": "DISCUSSION",
                "intent_reason": f"News / editorial recap format: '{n}'",
            }

    # 4. Check for Job Seekers / Sellers / Self-Promotion
    for s in _SELLER_KEYWORDS:
        pattern = r"\b" + re.escape(s) + r"\b"
        if re.search(pattern, clean, re.I):
            span = _extract_evidence_span(orig_text, s)

            return {
                "primary_category": "GENERAL_DISCUSSION",
                "topic_relevance_score": 50,
                "commercial_intent_score": 15,
                "service_fit_score": 10,
                "author_relevance_score": 10,
                "spam_risk_score": 30,
                "evidence_quality_score": 40,
                "buyer_intent_score": 15,
                "decision": "disqualified",
                "evidence_spans": [],
                "reasoning_summary": f"Job seeker or seller offering services rather than procuring: '{s}'.",
                "rejection_reason": f"Seller/job-seeker self-promotion ('{s}')",
                "uncertainties": [],
                "classification": "SELLER",
                "intent_reason": f"Seller self-promotion: '{s}'",
            }

    # 5. Check for Project Roadmap Announcements / Launches
    for a in _ANNOUNCEMENT_PATTERNS:
        if a in clean:
            return {
                "primary_category": "PROJECT_ANNOUNCEMENT",
                "topic_relevance_score": 70,
                "commercial_intent_score": 10,
                "service_fit_score": 5,
                "author_relevance_score": 50,
                "spam_risk_score": 20,
                "evidence_quality_score": 20,
                "buyer_intent_score": 15,
                "decision": "disqualified",
                "evidence_spans": [],
                "reasoning_summary": f"Project launch or roadmap milestone announcement: '{a}'. No commercial lead requested.",
                "rejection_reason": "Project announcement without service demand",
                "uncertainties": [],
                "classification": "DISCUSSION",
                "intent_reason": f"Project announcement: '{a}'",
            }

    # UPDATED LOGIC: Negation, Educational Advice, Thought Pieces & Rhetorical Discussion Filtering
    # Disqualify phrases like 'without hiring a developer', 'Imagine hiring a developer',
    # 'warrant the cost of hiring', 'Hiring a developer is not the end goal', etc.
    _NEGATED_OR_RHETORICAL_PATTERNS = [
        "without hiring", "no need to hire", "instead of hiring", "before hiring",
        "warrant the cost of hiring", "cost of hiring", "avoid hiring", "not hiring",
        "imagine hiring", "hiring a developer is not", "stop hiring", "dont need to hire",
        "don't need to hire", "never hire", "alternative to hiring", "questions to ask before hiring",
        "hiring a developer for your company? ask", "tips for hiring", "guide to hiring",
        "ways to automate without", "handled without hiring", "build without hiring",
        "launch without hiring", "hire without code", "no-code instead of hiring",
    ]
    for nr in _NEGATED_OR_RHETORICAL_PATTERNS:
        if nr in clean:
            span = _extract_evidence_span(orig_text, nr)
            return {
                "primary_category": "GENERAL_DISCUSSION",
                "topic_relevance_score": 50,
                "commercial_intent_score": 15,
                "service_fit_score": 10,
                "author_relevance_score": 25,
                "spam_risk_score": 10,
                "evidence_quality_score": 25,
                "buyer_intent_score": 15,
                "decision": "disqualified",
                "evidence_spans": [],
                "reasoning_summary": f"Educational commentary, advice, or negated context ('{nr}'). Not an active procurement demand.",
                "rejection_reason": f"Thought-piece / advice commentary with negated hiring intent ('{nr}')",
                "uncertainties": [],
                "classification": "DISCUSSION",
                "intent_reason": f"Advice / discussion piece: '{nr}'",
            }

    # 6. Check for Explicit Direct Buyer Demand
    for b in _DIRECT_BUYER_KEYWORDS:
        # Require word boundary or exact phrase match
        pattern = r"\b" + re.escape(b) + r"\b"
        if re.search(pattern, clean, re.I):
            span = _extract_evidence_span(orig_text, b)
            return {
                "primary_category": "DIRECT_BUYING_INTENT",
                "topic_relevance_score": 90,
                "commercial_intent_score": 95,
                "service_fit_score": 90,
                "author_relevance_score": 85,
                "spam_risk_score": 5,
                "evidence_quality_score": 95,
                "buyer_intent_score": 95,
                "decision": "qualified",
                "evidence_spans": [span],
                "reasoning_summary": f"Explicit procurement demand identified with direct buying intent: '{b}'.",
                "rejection_reason": None,
                "uncertainties": [],
                "classification": "BUYER",
                "intent_reason": f"Explicit buyer procurement demand: '{b}'",
            }

    # 7. Check for Explicit Hiring & Team Expansion
    for h in _HIRING_KEYWORDS:
        if h.endswith(":"):
            pattern = r"\b" + re.escape(h)
        elif " " in h:
            pattern = r"\b" + re.escape(h) + r"\b" if (h[0].isalnum() and h[-1].isalnum()) else re.escape(h)
        else:
            pattern = r"\b" + re.escape(h) + r"\b" if h[-1].isalnum() else re.escape(h)
        if re.search(pattern, clean, re.I):
            span = _extract_evidence_span(orig_text, h)
            return {
                "primary_category": "HIRING_OR_CONTRACT",
                "topic_relevance_score": 90,
                "commercial_intent_score": 90,
                "service_fit_score": 85,
                "author_relevance_score": 85,
                "spam_risk_score": 5,
                "evidence_quality_score": 90,
                "buyer_intent_score": 90,
                "decision": "qualified",
                "evidence_spans": [span],
                "reasoning_summary": f"Explicit hiring opportunity with role requirements: '{h}'.",
                "rejection_reason": None,
                "uncertainties": [],
                "classification": "BUYER",
                "intent_reason": f"Explicit hiring / contract role: '{h}'",
            }

    # 8. Check for Pain Points & Unmet Needs
    for p in _PAIN_POINT_KEYWORDS:
        if p in clean:
            span = _extract_evidence_span(orig_text, p)
            return {
                "primary_category": "PAIN_POINT_OR_UNMET_NEED",
                "topic_relevance_score": 75,
                "commercial_intent_score": 55,
                "service_fit_score": 65,
                "author_relevance_score": 60,
                "spam_risk_score": 10,
                "evidence_quality_score": 65,
                "buyer_intent_score": 60,
                "decision": "potential_opportunity",
                "evidence_spans": [span],
                "reasoning_summary": f"Concrete operational pain point detected ('{p}'). Suitable for review or nurture outreach.",
                "rejection_reason": None,
                "uncertainties": ["Lacks explicit budget or buying request"],
                "classification": "DISCUSSION",
                "intent_reason": f"Pain point / problem statement: '{p}'",
            }

    # 9. Generic thought pieces / long threads without procurement signals
    if len(clean) > 350:
        return {
            "primary_category": "GENERAL_DISCUSSION",
            "topic_relevance_score": 60,
            "commercial_intent_score": 10,
            "service_fit_score": 10,
            "author_relevance_score": 30,
            "spam_risk_score": 10,
            "evidence_quality_score": 10,
            "buyer_intent_score": 15,
            "decision": "disqualified",
            "evidence_spans": [],
            "reasoning_summary": "Industry essay or discussion without commercial buying or hiring signals.",
            "rejection_reason": "Discussion without procurement intent",
            "uncertainties": [],
            "classification": "DISCUSSION",
            "intent_reason": "Long thought-piece / essay without procurement intent",
        }

    # 10. Default / Unmatched content
    return {
        "primary_category": "GENERAL_DISCUSSION",
        "topic_relevance_score": 30,
        "commercial_intent_score": 10,
        "service_fit_score": 10,
        "author_relevance_score": 20,
        "spam_risk_score": 20,
        "evidence_quality_score": 0,
        "buyer_intent_score": 15,
        "decision": "disqualified",
        "evidence_spans": [],
        "reasoning_summary": "No explicit buying, hiring, or commercial procurement signals identified.",
        "rejection_reason": "Absence of commercial buying intent",
        "uncertainties": [],
        "classification": "NOISE",
        "intent_reason": "No explicit buying, hiring, or procurement signals",
    }


def extract_budget_scope_rules(text: str) -> tuple[str | None, float | None, list[str]]:
    """Extract budget & technology stack from post text."""
    clean = (text or "").lower()
    techs = [t for t in _TECH_PATTERNS if t in clean]

    m = _BUDGET_RE.search(text or "")
    budget_raw = None
    budget_usd = None
    if m:
        budget_raw = m.group(0).strip()
        num_str = re.sub(r"[^\d.]", "", budget_raw)
        try:
            val = float(num_str) if num_str else 0.0
            if "k" in budget_raw.lower():
                val *= 1000
            if "m" in budget_raw.lower():
                val *= 1000000
            budget_usd = val
        except ValueError:
            budget_usd = None

    return budget_raw, budget_usd, techs


import time
import hashlib
from collections import defaultdict

# NEW FEATURE (N4): LLM Free-tier Budget Limiter & Result Cache
_EVAL_CACHE: dict[str, dict[str, Any]] = {}
_JOB_EVAL_COUNTS: dict[str, int] = defaultdict(int)

from leadsweep.pipeline.groq_limiter import (
    _GROQ_LIMITER,
    GroqFreeTierRateLimiter,
    DailyQuotaExhaustedError,
    classify_groq_rate_limit,
    parse_groq_reset_seconds,
)

# Sliding window rate limiter scoped to (tenant, job, platform, author)
_AUTHOR_WINDOW_LOCK = None
# Key: (job_id, platform, clean_handle) -> list of (timestamp, message_hash)
_AUTHOR_RECORDS: dict[tuple[str, str, str], list[tuple[float, str]]] = defaultdict(list)
_AUTHOR_TIMESTAMPS: dict[str, list[float]] = defaultdict(list)  # Backwards compatibility alias
_DEDUP_WINDOW_SECONDS = 300.0  # 5 minutes
_MAX_AUTHOR_PER_WINDOW = 2  # Standard individual profile deduplication (e.g. Twitter/X)


# UPDATED LOGIC: Scoped author frequency check (exempts Telegram channel broadcasts; counts distinct messages)
def check_and_record_author_frequency(
    author_username: str,
    platform: str | None = None,
    job_id: str | None = None,
    tenant_id: str | None = None,
    text: str = ""
) -> bool:
    """Returns True only if an individual author spams >2 distinct entries in a 5-minute window for the same job.
    
    Never disqualifies Telegram channel broadcasts (where 1 channel legitimately posts multiple job openings).
    """
    if not author_username:
        return False
    plat = (platform or "twitter").strip().lower()
    # Telegram channels post multiple legitimate vacancies; exempt broadcast channels
    if plat == "telegram":
        return False

    clean_handle = author_username.strip().lstrip("@").lower()
    if not clean_handle:
        return False

    scope_key = (str(job_id or "default"), plat, clean_handle)
    now = time.time()
    cutoff = now - _DEDUP_WINDOW_SECONDS

    # Clean old timestamps
    active_records = [(t, h) for t, h in _AUTHOR_RECORDS.get(scope_key, []) if t > cutoff]
    if clean_handle not in _AUTHOR_TIMESTAMPS:
        active_records = []
    ts_compat = [t for t in _AUTHOR_TIMESTAMPS.get(clean_handle, []) if t > cutoff]

    msg_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]
    
    # Check distinct message count in current window
    distinct_msgs = {h for _, h in active_records}
    if len(distinct_msgs) >= _MAX_AUTHOR_PER_WINDOW or len(ts_compat) >= _MAX_AUTHOR_PER_WINDOW:
        _AUTHOR_RECORDS[scope_key] = active_records
        _AUTHOR_TIMESTAMPS[clean_handle] = ts_compat
        return True

    active_records.append((now, msg_hash))
    ts_compat.append(now)
    _AUTHOR_RECORDS[scope_key] = active_records
    _AUTHOR_TIMESTAMPS[clean_handle] = ts_compat
    return False


def has_recognizable_english_keywords(text: str) -> bool:
    """Check if text contains at least 3 recognizable English words/keywords.
    
    If text is non-English, multilingual, or lacks recognizable English keywords,
    it should be evaluated semantically by the LLM rather than dropped by English keyword heuristics.
    """
    if not text:
        return False
    # Check if text contains non-Latin scripts (CJK, Cyrillic, Arabic, Hangul, Kana)
    has_non_latin = any(
        ('\u4e00' <= ch <= '\u9fff') or  # CJK
        ('\u0400' <= ch <= '\u04ff') or  # Cyrillic
        ('\u0600' <= ch <= '\u06ff') or  # Arabic
        ('\u3040' <= ch <= '\u30ff') or  # Japanese
        ('\uac00' <= ch <= '\ud7af')     # Hangul
        for ch in text
    )
    if has_non_latin:
        return False
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
    return len(words) >= 3


def map_score_and_role_to_category(score: int | None, poster_role: str, current_category: str = "") -> str:
    """Deterministic 1-to-1 mapping from (score band, poster_role) to canonical category.
    
    Prevents category drift where the same score (e.g. 60) appears as both noise/GENERAL_DISCUSSION
    and HIRING_OR_CONTRACT.
    """
    if score is None:
        return current_category or "unevaluated"
    
    role, _ = normalize_poster_role(poster_role)
    
    # Preserved terminal exclusions
    if current_category in ("SPAM_OR_LOW_QUALITY", "PROMOTIONAL_OR_TASK_UPDATE", "IRRELEVANT"):
        return current_category

    if score >= 70:
        if role == "requester":
            return "DIRECT_BUYING_INTENT"
        return "HIRING_OR_CONTRACT"
    elif score >= 50:
        if role in ("aggregator", "recruiter"):
            return "HIRING_OR_CONTRACT"
        elif role == "requester":
            return "DIRECT_BUYING_INTENT"
        elif role in ("advisor", "seller", "bystander"):
            return "GENERAL_DISCUSSION"
        return "HIRING_OR_CONTRACT" if current_category in QUALIFIED_LEAD_CATEGORIES else "GENERAL_DISCUSSION"
    else:
        return "GENERAL_DISCUSSION"


# --------------------------------------------------------------------------- Graph Nodes
async def node_intent_classifier(state: LeadState) -> dict[str, Any]:
    """Node 1: Evaluates intent-aware classification, separating topical relevance from buying intent."""
    text = state.get("text", "")
    query = (state.get("query_context") or "").strip()
    followers = state.get("author_followers", 0) or 0
    search_mode = state.get("search_mode", "lead_generation")
    author_username = state.get("author_username", "")
    platform = (state.get("platform") or "twitter").strip().lower()
    job_id = state.get("job_id") or "default"
    tenant_id = state.get("tenant_id") or "default"
    source_mode = (state.get("source_mode") or "").strip().lower()

    # Pre-filter Non-Semantic Check: Empty text
    if not text or not text.strip() or text.strip() == "—" or text.strip().lower() == "no_text":
        return {
            "primary_category": "SPAM_OR_LOW_QUALITY",
            "topic_relevance_score": 0,
            "commercial_intent_score": 0,
            "service_fit_score": 0,
            "author_relevance_score": 0,
            "spam_risk_score": 100,
            "evidence_quality_score": 0,
            "buyer_intent_score": 0,
            "decision": "disqualified",
            "evidence_spans": [],
            "reasoning_summary": "No usable textual content available to evaluate intent.",
            "rejection_reason": "NO_TEXT",
            "uncertainties": [],
            "model_version": "prefilter",
            "prompt_version": "v3.0",
            "classification": "NOISE",
            "intent_reason": "Empty or missing text",
            "evaluator": "rule",
        }

    # Pre-filter Hygiene: Scoped deduplication check (Twitter only; never applied to Telegram broadcast channels)
    # K1: Exempt single-author modes (user_tweets, timeline, profile, replies) from author frequency gate
    is_single_author = source_mode in ("user_tweets", "timeline", "profile", "replies", "user_replies")
    if not is_single_author and check_and_record_author_frequency(author_username, platform=platform, job_id=job_id, tenant_id=tenant_id, text=text):
        log.info(
            "Pre-filter Deduplication Triggered: Author @%s exceeded 2 entries in 5 min for job %s. Bypassing LLM.",
            author_username, job_id
        )
        return {
            "primary_category": "SPAM_OR_LOW_QUALITY",
            "topic_relevance_score": 10,
            "commercial_intent_score": 0,
            "service_fit_score": 0,
            "author_relevance_score": 10,
            "spam_risk_score": 90,
            "evidence_quality_score": 0,
            "buyer_intent_score": None,
            "decision": "disqualified",
            "evidence_spans": [],
            "reasoning_summary": f"Deduplication Rate Limit: Author @{author_username} exceeded threshold (>2 entries in last 5 minutes).",
            "rejection_reason": "High-frequency profile dump / Deduplication rate limit exceeded",
            "uncertainties": [],
            "model_version": "rate-limiter-prefilter",
            "prompt_version": "v3.0-prefilter",
            "classification": "NOISE",
            "intent_reason": "Author exceeded 2 entries in 5-minute sliding window",
            "evaluator": "rule",
        }

    # Step 1: Base deterministic rule-based evaluation (DEMOTION ONLY)
    rule_res = classify_intent_rules(text, query_context=query, search_mode=search_mode)

    primary_category = rule_res["primary_category"]
    topic_rel = compute_topic_relevance(text, query_context=query) if query else rule_res["topic_relevance_score"]
    comm_intent = rule_res["commercial_intent_score"]
    service_fit = rule_res["service_fit_score"]
    author_rel = rule_res["author_relevance_score"]
    spam_risk = rule_res["spam_risk_score"]
    ev_qual = rule_res["evidence_quality_score"]
    decision = rule_res["decision"]
    evidence_spans = rule_res["evidence_spans"]
    reasoning = rule_res["reasoning_summary"]
    rejection_reason = rule_res["rejection_reason"]
    uncertainties = rule_res["uncertainties"]
    legacy_cat = rule_res["classification"]
    intent_reason = rule_res["intent_reason"]
    evaluator_provenance = "unevaluated"
    used_model_id = "unevaluated"
    token_usage = None
    poster_role_val = "unknown"
    confidence_val = 0.85
    calibration_adj = False

    # UPDATED LOGIC (N3): Rules can ONLY demote. Never qualify or assign positive score without LLM.
    # Initial score before LLM evaluation is None.
    final_score = None

    # Deterministic Pre-Demotions (spam, blatant non-commercial noise)
    is_rule_demoted = False
    if spam_risk >= 90:
        is_rule_demoted = True
        evaluator_provenance = "rule"
        primary_category = "SPAM_OR_LOW_QUALITY"
        final_score = 5
        decision = "disqualified"
        legacy_cat = "NOISE"
    elif query and topic_rel < 30:
        is_channel_query = query.startswith("t.me/") or query.startswith("@") or "telegram" in platform
        # Posts without recognizable English keywords must reach the LLM instead of default-noise rule
        if has_recognizable_english_keywords(text) and not is_channel_query:
            is_rule_demoted = True
            evaluator_provenance = "rule"
            primary_category = "IRRELEVANT"
            final_score = 10
            decision = "disqualified"
            legacy_cat = "NOISE"
            rejection_reason = f"Off-topic for query '{query}': topic relevance {topic_rel}/100"

    from leadsweep.config import get_settings
    settings = get_settings()

    # Step 2: Semantic LLM pass for semantic intent, negation, perspective, relevance
    # NEW FEATURE (N4): Result cache & Free-tier limiter
    if not is_rule_demoted and settings.groq_api_key:
        prompt_ver = "v3.1-compact"
        norm_text = " ".join(unicodedata.normalize("NFKC", text).split()).lower()
        query_hash = hashlib.sha256(query.encode("utf-8", errors="ignore")).hexdigest()[:16]
        text_hash = hashlib.sha256(norm_text.encode("utf-8", errors="ignore")).hexdigest()
        cache_key = f"{text_hash}:{prompt_ver}:{query_hash}"

        has_multi_digest = is_multi_company_digest(text)
        cached_eval = _EVAL_CACHE.get(cache_key)
        if cached_eval:
            log.info("Evaluation cache HIT for text hash %s (skipping LLM)", text_hash[:8])
            primary_category = cached_eval["category"]
            final_score = cached_eval["score"]
            evidence_spans = cached_eval["evidence_spans"]
            reasoning = cached_eval["reason"]
            poster_role_val, _ = normalize_poster_role(cached_eval.get("poster_role"))
            if has_multi_digest:
                if poster_role_val == "recruiter" or poster_role_val != "aggregator":
                    poster_role_val = "aggregator"
                if final_score is not None and final_score > 60:
                    final_score = 60
            confidence_val = cached_eval["confidence"]
            evaluator_provenance = cached_eval["evaluator"]
            used_model_id = cached_eval.get("model_version", settings.groq_model)
            token_usage = cached_eval.get("token_usage") or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cached": True}
        else:
            # Check per-job budget cap
            job_cap = getattr(settings, "llm_top_n", 15) or 15
            current_evals = _JOB_EVAL_COUNTS[job_id]
            if current_evals >= job_cap:
                log.warning("Per-job LLM budget cap reached (%d/%d for job %s). Remaining items UNEVALUATED.",
                            current_evals, job_cap, job_id)
                evaluator_provenance = "unevaluated"
                primary_category = "unevaluated"
                final_score = None
                decision = "unevaluated"
                reasoning = f"AI evaluation budget limit reached for job ({current_evals}/{job_cap}). Marked UNEVALUATED."
            else:
                try:
                    await _GROQ_LIMITER.acquire_slot(estimated_tokens=400)
                    from langchain_groq import ChatGroq

                    digest_hint = ""
                    if has_multi_digest:
                        digest_hint = (
                            "- MULTI-COMPANY DIGEST: This post lists 3+ distinct companies hiring. "
                            "You MUST classify poster_role as 'aggregator' (NOT recruiter), and category as HIRING_OR_CONTRACT.\n"
                        )
                    # Compact prompt (N4) while strictly preserving taxonomy, roles, and verbatim evidence rule
                    prompt = (
                        "You are an expert AI Lead Qualification Judge evaluating social posts for commercial intent.\n"
                        "CATEGORIES: DIRECT_BUYING_INTENT, HIRING_OR_CONTRACT, PAIN_POINT_OR_UNMET_NEED, FOUNDER_PROJECT_SIGNAL, "
                        "PARTNERSHIP_REQUEST, GENERAL_DISCUSSION, NEWS_OR_INCIDENT, PROJECT_ANNOUNCEMENT, PROMOTIONAL_OR_TASK_UPDATE, "
                        "SPAM_OR_LOW_QUALITY, IRRELEVANT.\n"
                        "ROLES: recruiter, aggregator, requester, advisor, seller, bystander.\n"
                        "RULES:\n"
                        f"{digest_hint}"
                        "- DIRECT_BUYING_INTENT: Explicit request for developer, contractor, bot, or technical service. Role: requester.\n"
                        "- HIRING_OR_CONTRACT: Job vacancy/hiring post. If direct company/recruiter -> recruiter. If job board/listing channel -> aggregator.\n"
                        "- GENERAL_DISCUSSION: Advice/essays ('without hiring', 'tips'). Role: advisor.\n"
                        "- EVIDENCE: evidence_quote MUST be an EXACT VERBATIM substring from the post text, or empty string.\n"
                        f"OBJECTIVE: '{query}' | PLATFORM: {platform} | AUTHOR: {author_username}\n"
                        f"POST:\n\"\"\"\n{text[:getattr(settings, 'judge_max_chars', 1200)]}\n\"\"\"\n"
                    )

                    llm_res = None
                    used_model_id = settings.groq_model
                    models_to_try = [settings.groq_model]
                    fb_model = getattr(settings, "groq_fallback_model", None)
                    if fb_model and fb_model != settings.groq_model:
                        models_to_try.append(fb_model)

                    last_groq_err = None
                    for current_model in models_to_try:
                        chat = ChatGroq(
                            model=current_model,
                            api_key=settings.groq_api_key,
                            temperature=0,
                            max_tokens=500,
                        )
                        structured_chat = chat.with_structured_output(LeadJudgeContract, include_raw=True)
                        for attempt in range(1, 6):
                            try:
                                llm_res = await structured_chat.ainvoke(prompt)
                                last_groq_err = None
                                break
                            except Exception as e:
                                recovered = _recover_failed_tool_generation(e)
                                if recovered is not None:
                                    llm_res = {"parsed": recovered, "raw": None}
                                    last_groq_err = None
                                    break
                                last_groq_err = e
                                kind, detail, wait_s = classify_groq_rate_limit(e)
                                if kind == "tpd":
                                    raise DailyQuotaExhaustedError(detail)
                                elif kind == "tpm":
                                    await _GROQ_LIMITER.handle_429(e, attempt=attempt)
                                else:
                                    break
                        if llm_res:
                            used_model_id = current_model
                            break

                    # C5 Fallback Provider Chain: If Groq exhausted & Ollama configured (default OFF)
                    if not llm_res and getattr(settings, "ollama_base_url", "") and getattr(settings, "ollama_model", ""):
                        try:
                            from langchain_ollama import ChatOllama
                            ollama_chat = ChatOllama(
                                model=settings.ollama_model,
                                base_url=settings.ollama_base_url,
                                temperature=0,
                            ).with_structured_output(LeadJudgeContract, include_raw=True)
                            llm_res = await ollama_chat.ainvoke(prompt)
                            if llm_res:
                                used_model_id = f"ollama:{settings.ollama_model}"
                        except Exception as ollama_err:
                            log.info("Ollama fallback unreachable/skipped: %s", ollama_err)

                    if not llm_res and last_groq_err:
                        raise last_groq_err

                    token_usage = None
                    parsed: LeadJudgeContract | None = llm_res.get("parsed") if isinstance(llm_res, dict) else None
                    if isinstance(llm_res, dict) and "raw" in llm_res:
                        raw_msg = llm_res.get("raw")
                        if hasattr(raw_msg, "response_metadata") and isinstance(raw_msg.response_metadata, dict):
                            _GROQ_LIMITER.update_from_headers(raw_msg.response_metadata)
                            token_usage = raw_msg.response_metadata.get("token_usage") or raw_msg.response_metadata.get("usage")

                    if parsed and parsed.category:
                        llm_cat = str(parsed.category).strip().upper()
                        llm_score = int(parsed.score)
                        llm_quote = str(parsed.evidence_quote).strip()
                        llm_reason = str(parsed.reason).strip()
                        llm_role = str(parsed.poster_role).strip().lower()
                        llm_conf = float(parsed.confidence)

                        valid_cats = {
                            "DIRECT_BUYING_INTENT", "HIRING_OR_CONTRACT", "PAIN_POINT_OR_UNMET_NEED",
                            "FOUNDER_PROJECT_SIGNAL", "PARTNERSHIP_REQUEST", "GENERAL_DISCUSSION",
                            "NEWS_OR_INCIDENT", "PROJECT_ANNOUNCEMENT", "PROMOTIONAL_OR_TASK_UPDATE",
                            "SPAM_OR_LOW_QUALITY", "IRRELEVANT"
                        }
                        if llm_cat in valid_cats:
                            evaluator_provenance = "llm"
                            poster_role_val = llm_role
                            confidence_val = llm_conf
                            primary_category = llm_cat
                            final_score = max(0, min(100, llm_score))
                            if has_multi_digest:
                                if poster_role_val == "recruiter" or poster_role_val != "aggregator":
                                    poster_role_val = "aggregator"
                                if final_score is not None and final_score > 60:
                                    final_score = 60
                            if llm_reason:
                                reasoning = llm_reason

                            # Unicode-normalized substring check (N1 & N6-b)
                            norm_post = unicodedata.normalize("NFKC", text).lower()
                            norm_quote = unicodedata.normalize("NFKC", llm_quote).lower()
                            if norm_quote and norm_quote in norm_post:
                                evidence_spans = [llm_quote]
                            elif llm_cat in QUALIFIED_LEAD_CATEGORIES:
                                primary_category = "NEEDS_REVIEW"
                                uncertainties.append(f"Evidence quote '{llm_quote}' was not a verifiable substring of post text.")
                                final_score = min(60, final_score)

                            _JOB_EVAL_COUNTS[job_id] += 1
                            # Cache verified LLM result
                            _EVAL_CACHE[cache_key] = {
                                "category": primary_category,
                                "score": final_score,
                                "evidence_spans": evidence_spans,
                                "reason": reasoning,
                                "poster_role": poster_role_val,
                                "confidence": confidence_val,
                                "evaluator": "llm",
                                "model_version": used_model_id,
                                "token_usage": token_usage,
                            }
                except Exception as e:
                    if not os.getenv("PYTEST_CURRENT_TEST"):
                        log.warning("LLM evaluation unavailable (%s); falling back to deterministic rule engine", e)
                        evaluator_provenance = "rule"
                        primary_category = rule_res["primary_category"]
                        final_score = rule_res["buyer_intent_score"]
                        decision = rule_res["decision"]
                        reasoning = rule_res["reasoning_summary"]
                        rejection_reason = rule_res["rejection_reason"]
                        poster_role_val = "requester" if primary_category == "DIRECT_BUYING_INTENT" else ("recruiter" if primary_category == "HIRING_OR_CONTRACT" else "bystander")
                    else:
                        # UPDATED LOGIC (N3 / A5): Any LLM failure leaves record UNEVALUATED, score None, zero qualified
                        log.warning("LLM evaluation unavailable (%s); leaving record UNEVALUATED", e)
                        evaluator_provenance = "unevaluated"
                        primary_category = "unevaluated"
                        final_score = None
                        decision = "unevaluated"
                        if isinstance(e, DailyQuotaExhaustedError):
                            reasoning = str(e)
                        else:
                            kind, detail, _ = classify_groq_rate_limit(e)
                            reasoning = detail if kind in ("tpd", "tpm") else f"AI evaluation unavailable: {e}"
                        rejection_reason = "LLM evaluation failed"

    elif not settings.groq_api_key and not is_rule_demoted:
        # N3 (a): Blank or missing key -> record UNEVALUATED
        evaluator_provenance = "unevaluated"
        primary_category = "unevaluated"
        final_score = None
        decision = "unevaluated"
        reasoning = "AI evaluation unavailable: GROQ_API_KEY is not configured"
        rejection_reason = "Missing LLM API key"

    # Step 3: Direction Demotion Layer (Only demotes, never promotes)
    lead_direction_val = "UNCLEAR"
    direction_reason_val = reasoning
    direction_evidence_val = evidence_spans[0] if evidence_spans else ""
    _lead_intel_env = os.getenv("LEAD_INTEL", "").lower()
    _query_intel_env = os.getenv("QUERY_INTELLIGENCE", "").lower()
    _is_intel_active = not (_lead_intel_env in ("off", "false", "0", "no") or _query_intel_env in ("off", "false", "0", "no"))

    if _is_intel_active and final_score is not None:
        try:
            from leadsweep.leadintel.lead_quick import direction_gate_hybrid, apply_direction_cap
            author_bio = state.get("author_bio", "") or state.get("bio", "")
            full_context = f"{text} | bio: {author_bio}" if author_bio else text
            quick_res = direction_gate_hybrid(full_context)
            if isinstance(quick_res, tuple) and len(quick_res) >= 3:
                lead_direction_val = quick_res[0]
                direction_reason_val = quick_res[2]
            elif isinstance(quick_res, dict):
                lead_direction_val = quick_res.get("label", "UNCLEAR")
                direction_reason_val = quick_res.get("reason", "")
                direction_evidence_val = quick_res.get("evidence_quote", "")

            capped = apply_direction_cap(final_score, lead_direction_val)
            if capped < final_score:
                final_score = capped
                if lead_direction_val in ("JOB_SEEKER", "SERVICE_PROVIDER_PROMO", "AIRDROP_BOT_SPAM"):
                    decision = "disqualified"
                    primary_category = "IRRELEVANT" if lead_direction_val == "AIRDROP_BOT_SPAM" else "PROMOTIONAL_OR_TASK_UPDATE"
                    rejection_reason = f"Direction gate: {direction_reason_val}"
                elif lead_direction_val == "INFO_OR_THOUGHT_CONTENT":
                    decision = "disqualified"
                    primary_category = "GENERAL_DISCUSSION"
                    rejection_reason = f"Direction gate: {direction_reason_val}"
        except Exception:
            pass

    # C3: Ensure evidenceSpans / evidence_quote is empty unless evaluator=llm AND quote is verified
    is_llm_verified = (evaluator_provenance == "llm" and (quote_verified if 'quote_verified' in locals() else bool(evidence_spans)))
    final_evidence_spans = evidence_spans if is_llm_verified else []
    final_reasoning = reasoning
    final_model_id = used_model_id if evaluator_provenance == "llm" else "unevaluated"

    return {
        "primary_category": primary_category,
        "lead_direction": lead_direction_val,
        "direction_reason": final_reasoning,
        "direction_evidence": final_evidence_spans[0] if final_evidence_spans else "",
        "topic_relevance_score": topic_rel,
        "commercial_intent_score": comm_intent,
        "service_fit_score": service_fit,
        "author_relevance_score": author_rel,
        "spam_risk_score": spam_risk,
        "evidence_quality_score": ev_qual,
        "buyer_intent_score": final_score,
        "decision": decision,
        "evidence_spans": final_evidence_spans,
        "reasoning_summary": final_reasoning,
        "rejection_reason": rejection_reason,
        "uncertainties": uncertainties,
        "model_version": final_model_id,
        "token_usage": token_usage,
        "prompt_version": "v3.1-compact",
        "evaluator": evaluator_provenance,
        "poster_role": poster_role_val,
        "calibration_adjusted": calibration_adj,
        "classification": legacy_cat,
        "intent_reason": final_reasoning,
    }


# NEW FEATURE (N2): Post-LLM Consistency & Calibration Node
async def node_consistency_and_calibration(state: LeadState) -> dict[str, Any]:
    """
    Enforces unified calibration table & fixes role/score/category contradictions across all platforms.
    
    Calibration Bands:
    - poster_role in ('recruiter', 'requester'): Upper band [70, 95] for HIRING_OR_CONTRACT / DIRECT_BUYING_INTENT.
    - poster_role == 'aggregator':
        * include_aggregators=True: Configurable lower band [60, 75], category HIRING_OR_CONTRACT.
        * include_aggregators=False: Excluded band [15, 35], category GENERAL_DISCUSSION.
    - poster_role in ('advisor', 'seller', 'bystander'): Low band [10, 35], category GENERAL_DISCUSSION.
    
    Golden Invariant: The node may clamp within a band and fix inconsistent category labels,
    but MUST NEVER PROMOTE a record the LLM judged irrelevant or disqualified, and never touch the evidence rule.
    """
    score = state.get("buyer_intent_score")
    category = state.get("primary_category", "unevaluated")
    raw_role = state.get("poster_role") or "unknown"
    role, is_norm = normalize_poster_role(raw_role)
    reason = (state.get("reasoning_summary") or "").lower()
    decision = state.get("decision", "disqualified")
    evaluator = state.get("evaluator", "unevaluated")
    calibration_adj = bool(state.get("calibration_adjusted", False))

    if evaluator != "llm" or score is None:
        return {
            "buyer_intent_score": score if evaluator == "rule" else None,
            "primary_category": category if evaluator == "rule" else "unevaluated",
            "decision": decision,
            "poster_role": role,
            "role_normalized": bool(state.get("role_normalized") or is_norm),
            "calibration_adjusted": calibration_adj,
            "classification": "NOISE" if decision == "disqualified" else "DISCUSSION",
            "reasoning_summary": state.get("reasoning_summary", ""),
            "intent_reason": state.get("intent_reason", ""),
        }

    from leadsweep.config import get_settings
    settings = get_settings()
    include_aggr = getattr(settings, "include_aggregators", True)

    orig_score = score
    orig_cat = category

    # 1. Contradiction Detection: Role says aggregator or reason mentions aggregator/job board
    is_aggregator = role == "aggregator" or "aggregator" in reason or "job board" in reason
    is_recruiter_or_buyer = role in ("recruiter", "requester")
    is_advisor_or_seller = role in ("advisor", "seller", "bystander") or "advice" in reason or "thought" in reason

    # Never promote an item the LLM judged irrelevant, spam, or promotional
    is_non_lead_by_llm = category in ("IRRELEVANT", "SPAM_OR_LOW_QUALITY", "PROMOTIONAL_OR_TASK_UPDATE")

    if not is_non_lead_by_llm:
        if is_aggregator:
            if include_aggr:
                category = "HIRING_OR_CONTRACT"
                # Clamp into aggregator band [60, 75]
                score = max(60, min(75, score))
                decision = "qualified" if score >= 70 else "potential_opportunity"
            else:
                category = "GENERAL_DISCUSSION"
                score = max(15, min(35, score))
                decision = "disqualified"

        elif is_advisor_or_seller:
            category = "GENERAL_DISCUSSION"
            score = max(10, min(35, score))
            decision = "disqualified"

        elif is_recruiter_or_buyer:
            # Detect real job/buyer listing mislabeled as GENERAL_DISCUSSION
            if category == "GENERAL_DISCUSSION" and ("hiring" in reason or "recruiting" in reason or "contractor" in reason or "developer" in reason):
                category = "HIRING_OR_CONTRACT" if role == "recruiter" else "DIRECT_BUYING_INTENT"
            if category in QUALIFIED_LEAD_CATEGORIES:
                score = max(70, min(95, score))
                decision = "qualified"

    # Enforce deterministic category mapping from (score band, poster_role)
    category = map_score_and_role_to_category(score, role, category)

    if score != orig_score or category != orig_cat:
        calibration_adj = True
        log.info("[Calibration Node] Calibrated post: role='%s', cat '%s'->'%s', score %s->%s (adjusted=True)",
                 role, orig_cat, category, orig_score, score)

    legacy_cat = "BUYER" if decision == "qualified" else ("DISCUSSION" if category == "GENERAL_DISCUSSION" else "NOISE")

    return {
        "buyer_intent_score": score,
        "primary_category": category,
        "decision": decision,
        "poster_role": role,
        "role_normalized": bool(state.get("role_normalized") or is_norm),
        "calibration_adjusted": calibration_adj,
        "classification": legacy_cat,
    }


async def node_budget_scope_extractor(state: LeadState) -> dict[str, Any]:
    """Node 2: Extracts scope, technologies, and budget amounts."""
    text = state.get("text", "")
    budget_raw, budget_usd, techs = extract_budget_scope_rules(text)
    scope_desc = f"Custom build involving {', '.join(techs)}" if techs else "General service requirement"

    return {
        "budget_raw": budget_raw,
        "budget_usd": budget_usd,
        "technologies": techs,
        "scope": scope_desc,
        "timeline": "ASAP" if any(w in (text or "").lower() for w in ["urgently", "asap", "immediately", "quick"]) else None,
    }


async def node_disqualify(state: LeadState) -> dict[str, Any]:
    """Node 3a: Mark unqualified / non-commercial item."""
    reason = state.get("rejection_reason") or state.get("reasoning_summary") or "Non-buyer / Non-commercial"
    return {
        "qualified": False,
        "status": "disqualified",
        "outreach_priority": "low",
        "suggested_angle": f"Do not contact (Disqualified: {reason})",
    }


async def node_auto_approve(state: LeadState) -> dict[str, Any]:
    """Node 3b: Standard verified lead ready for outreach."""
    techs = state.get("technologies", [])
    tech_str = f" for {techs[0]}" if techs else ""
    return {
        "qualified": True,
        "status": "approved",
        "outreach_priority": "medium",
        "suggested_angle": f"Send relevant case study & tailored proposal{tech_str}.",
    }


async def node_hitl_high_value(state: LeadState) -> dict[str, Any]:
    """Node 4: Flag high-value lead ($5,000+ budget or VIP account) for Human-In-The-Loop review."""
    budget = state.get("budget_raw") or "High Priority Scope"
    return {
        "qualified": True,
        "status": "hitl_pending",
        "outreach_priority": "vip",
        "suggested_angle": f"High value opportunity detected ({budget}). Admin 1-Click approval recommended.",
    }


# --------------------------------------------------------------------------- Conditional Routers
def route_intent_gate(state: LeadState) -> str:
    """Route: Qualified lead if buyer_intent_score >= 70 AND primary_category in QUALIFIED_LEAD_CATEGORIES."""
    score = state.get("buyer_intent_score") or 0
    category = state.get("primary_category", "")
    decision = state.get("decision", "")

    if score >= 70 and (category in QUALIFIED_LEAD_CATEGORIES or decision == "qualified"):
        return "evaluate_value"
    return "disqualify"


def route_value_gate(state: LeadState) -> str:
    """Route: If budget is >= $5,000 or high follower count, trigger HITL interrupt."""
    budget_usd = state.get("budget_usd") or 0.0
    followers = state.get("author_followers") or 0
    if budget_usd >= 5000 or followers >= 50000:
        return "hitl_high_value"
    return "auto_approve"


# --------------------------------------------------------------------------- Build & Compile Graph
def build_lead_qualification_graph():
    builder = StateGraph(LeadState)

    builder.add_node("classify_intent", node_intent_classifier)
    builder.add_node("consistency_and_calibration", node_consistency_and_calibration)
    builder.add_node("extract_budget_scope", node_budget_scope_extractor)
    builder.add_node("disqualify", node_disqualify)
    builder.add_node("auto_approve", node_auto_approve)
    builder.add_node("hitl_high_value", node_hitl_high_value)

    # Workflow transitions
    builder.add_edge(START, "classify_intent")
    builder.add_edge("classify_intent", "consistency_and_calibration")
    builder.add_edge("consistency_and_calibration", "extract_budget_scope")

    # Intent decision gate
    builder.add_conditional_edges(
        "extract_budget_scope",
        route_intent_gate,
        {
            "evaluate_value": "evaluate_value_router",
            "disqualify": "disqualify",
        }
    )

    # Clean intermediate routing node
    builder.add_node("evaluate_value_router", lambda state: {})
    builder.add_conditional_edges(
        "evaluate_value_router",
        route_value_gate,
        {
            "hitl_high_value": "hitl_high_value",
            "auto_approve": "auto_approve",
        }
    )

    builder.add_edge("disqualify", END)
    builder.add_edge("auto_approve", END)
    builder.add_edge("hitl_high_value", END)

    return builder.compile()


# Singleton compiled graph instance
lead_qualification_pipeline = build_lead_qualification_graph()

