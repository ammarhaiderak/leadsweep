import asyncio
from pathlib import Path

import pytest

from leadsweep.pipeline.fakes import mk
from leadsweep.pipeline.models import AgencyProfile, Candidate, LeadScore, load_pipeline_config
from leadsweep.pipeline.scoring import OllamaScorer, heuristic_score, ollama_ready, prefilter_reason

PROFILE = AgencyProfile(services=["AI agents", "workflow automation"])


def cand(text, qtype="lead", **kw):
    return Candidate(tweet=mk("1", text, **kw), queries=["q"], query_type=qtype)


def test_strong_buyer_is_lead():
    s = heuristic_score(cand("We're looking for an AI developer to build a LangChain chatbot. Budget $3k, DM me."), PROFILE)
    assert s.score >= 70 and s.category == "lead"


def test_rfp_category():
    s = heuristic_score(cand("RFP: we need an automation agency for n8n workflows. Proposals due Friday."), PROFILE)
    assert s.category == "rfp" and s.score >= 70


def test_job_seeker_is_noise():
    s = heuristic_score(cand("Open to work! AI engineer with LangChain and n8n experience #opentowork"), PROFILE)
    assert s.category == "noise" and s.score <= 20


def test_needs_buying_signal_and_service_term():
    assert heuristic_score(cand("Great weather today, going for a long walk in the park"), PROFILE).score <= 30
    assert heuristic_score(cand("I love automation and LangChain, such cool tech stack today"), PROFILE).score <= 30  # no buying intent


def test_word_boundaries_and_prefix_and_html_entities():
    assert "'rag'" not in heuristic_score(cand("need storage and a drag racing fragile thing please"), PROFILE).reason
    s = heuristic_score(cand("we need workflow integrations &amp; automation, looking for an agency"), PROFILE)
    reason_lower = s.reason.lower()
    assert "workflow" in reason_lower and "integration" in reason_lower  # prefix match: 'integrations' -> integration
    assert s.score >= 50


def test_trend_scoring_uses_engagement():
    hot = heuristic_score(cand("MCP servers and AI agents are changing automation", "trend", likes=300, rts=50, views=60000), PROFILE)
    cold = heuristic_score(cand("MCP servers and AI agents are changing automation", "trend"), PROFILE)
    assert hot.category == "trend" and hot.score > cold.score


def test_prefilter_rules():
    assert prefilter_reason(mk("1", "x" * 40, retweet=True), "lead") == "retweet"
    assert prefilter_reason(mk("1", "short"), "lead") == "too_short"
    assert prefilter_reason(mk("1", "Join the airdrop and whitelist for AI agents now"), "lead") == "spam"
    assert prefilter_reason(mk("1", "Join the airdrop and whitelist for AI agents now"), "trend") is None
    assert prefilter_reason(mk("1", "Looking for an AI developer for our project"), "lead") is None


class FakeChain:
    def __init__(self, out):
        self.out = out

    async def ainvoke(self, messages):
        assert messages[0][0] == "system" and "Agency services" in messages[0][1]
        return self.out


@pytest.mark.parametrize("out", [LeadScore(score=80, category="lead"), {"score": 80, "category": "lead", "reason": "r"}])
def test_ollama_scorer_accepts_model_or_dict(out):
    r = asyncio.run(OllamaScorer("m", "http://x", chain=FakeChain(out)).score(cand("hello world looking for dev"), PROFILE))
    assert r.score == 80


def test_ollama_scorer_rejects_empty_output():
    with pytest.raises(ValueError):
        asyncio.run(OllamaScorer("m", "http://x", chain=FakeChain(None)).score(cand("hello world looking for dev"), PROFILE))


def test_leadscore_clamps_and_coerces():
    s = LeadScore(score=250, category="lead", intent_signals="budget")
    assert s.score == 100 and s.intent_signals == ["budget"]


def test_ollama_ready_reports_unreachable():
    ok, msg = ollama_ready("http://127.0.0.1:9", "qwen2.5:3b", timeout=0.5)
    assert not ok and "ollama serve" in msg


def test_shipped_queries_file_is_valid():
    cfg = load_pipeline_config(Path("config/queries.toml"))
    assert cfg.queries and all(len(q.q) <= 512 for q in cfg.queries)
    assert {q.type for q in cfg.queries} >= {"lead", "rfp", "trend"}


# ---------------------------------------------------------------- P3.1 regression set (false positives seen in the first live run)
SERVICES = AgencyProfile(services=["AI agents", "LLM apps", "workflow automation", "web scraping and data pipelines",
                                   "MCP integrations", "computer vision"])
LONG_MARKETING = ("AI has become extraordinarily good at telling us things. Explain this. Summarize that. Research this. "
                  "But we are still looking for the next layer: agents that do the work. Who can build this? We need a new workflow "
                  "automation stack where every AI agent can integrate with every tool, and teams are hiring for it. ") * 3
SELECTED = 80  # default heuristic_min_score


def _score(text, qtype="lead", **kw):
    return heuristic_score(cand(text, qtype, **kw), SERVICES)


@pytest.mark.parametrize("text", [
    "We're looking for an AI developer to build a LangChain chatbot for our support team. Budget $3k, DM me.",
    "We’re looking for someone to build an n8n automation for our agency. Need a freelancer, budget is $1500.",  # curly quote
    "Need an automation expert to build a web scraper for real estate listings. Who can help? DM me",
])
def test_true_leads_clear_the_rule_based_bar(text):
    s = _score(text)
    assert s.category == "lead" and s.score >= SELECTED


@pytest.mark.parametrize("text", [
    LONG_MARKETING,  # long AI-marketing essay full of buzzwords
    "🚨 We’re Hiring: Full-Stack AI Engineer at Titan Capital. We’re looking for a Full-Stack AI Engineer to build LLM automation. Full-time, apply now.",
    "🚨 A company is offering $120–$170/hour for senior AI engineers who can build and deploy real AI agent systems. Who can apply?",
    "🚨 𝗦𝗔𝗧𝗨𝗥𝗗𝗔𝗬 𝗕𝗔𝗡𝗚𝗘𝗥! 𝟱 𝗙𝗥𝗘𝗘 𝗙𝗨𝗟𝗟 𝗙𝗨𝗡𝗡𝗘𝗟 𝗕𝗨𝗜𝗟𝗗𝗦 𝗧𝗛𝗔𝗧 𝗚𝗘𝗧 𝗬𝗢𝗨 𝗣𝗔𝗜𝗗 using n8n and Claude automation agency tips",
    "An automation agency doesn’t need better prompts. It needs someone who can spot a $10K problem and fix the LLM workflow.",
    "OneByZero just raised a $20M Series A. We are hiring AI engineers to build AI agents across Singapore.",
])
def test_live_false_positives_stay_below_the_bar(text):
    s = _score(text)
    assert s.score < SELECTED or s.category == "noise"


@pytest.mark.parametrize("text", [
    "In case you forgot $NEAR is not a moonboy number. near.com is now packing AI agent payments and onchain identity into one app",
    "Melius upgraded $MSFT to Buy saying enterprises increasingly want a secure AI agent platform",
    "WHAT IF YOUR CRYPTO DOMAIN WASN'T JUST A NAME? What if it could become your on-chain identity, powering AI agent payments",
])
def test_crypto_and_cashtag_posts_are_not_trends(text):
    s = _score(text, "trend", likes=60, rts=5, views=9000)
    assert s.score < SELECTED


def test_good_trend_still_selected():
    s = _score("MCP servers are becoming the standard way to connect AI agents to tools. What this means for automation agencies.",
               "trend", likes=250, rts=40, views=50000)
    assert s.category == "trend" and s.score >= SELECTED


def test_rfp_aggregator_post_is_rfp():
    s = _score("Let's analyze this new opportunity: A university is looking for a company to rebuild its portal. RFP open, integration with AI chatbot.", "rfp")
    assert s.category == "rfp" and s.score >= SELECTED


def test_unicode_fancy_fonts_are_folded():
    from leadsweep.pipeline.scoring import norm
    assert norm("𝗕𝗔𝗡𝗚𝗘𝗥 We’re") == "banger we're"


def test_groq_scorer_with_fake_chain():
    from leadsweep.pipeline.scoring import GroqScorer
    gs = GroqScorer(model="openai/gpt-oss-20b", api_key="dummy", chain=FakeChain(LeadScore(score=88, category="lead", reason="strong")))
    res = asyncio.run(gs.score(cand("Need AI dev"), PROFILE))
    assert res.score == 88 and res.category == "lead"


def test_pick_scorer_groq():
    from leadsweep.config import Settings
    from leadsweep.pipeline.scoring import pick_scorer
    st = Settings(groq_api_key="test_key", groq_model="openai/gpt-oss-20b")
    scorer, label = asyncio.run(pick_scorer("groq", st))
    assert scorer is not None and "groq:" in label

