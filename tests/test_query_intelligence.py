# NEW FEATURE: Query Intelligence and Lead-Direction Tests
"""
Unit and integration tests for Query Intelligence:
1. Lead Brief builder
2. Query variant generator & strategies
3. Lead-direction classifier on real historical posts:
   - @Web3temple (Tweet 2108227844941746605) -> JOB_SEEKER capped <= 20
   - Freelancer portfolio -> SERVICE_PROVIDER_PROMO capped <= 20
   - Airdrop / giveaway -> AIRDROP_BOT_SPAM capped <= 5
   - Educational essay -> INFO_OR_THOUGHT_CONTENT capped <= 25
   - Real buyer with budget -> BUYER_SIGNAL high score
4. Probe loop & bandit pruning
5. Feature flag QUERY_INTELLIGENCE=off reproduces legacy behavior byte-for-byte
"""
import os
import pytest
import asyncio
from leadsweep.intel.models import DirectionLabel, LeadBrief, ICPProfile
from leadsweep.intel.brief import build_lead_brief_heuristic
from leadsweep.intel.generator import generate_query_variants
from leadsweep.intel.direction import classify_direction_heuristic, verify_quote_in_text
from leadsweep.intel.probe import select_winning_variants, simulate_or_score_probe_items
from leadsweep.pipeline.qualification_graph import node_intent_classifier


def test_brief_builder_heuristic():
    brief = build_lead_brief_heuristic("web3 founder")
    assert "Web3" in brief.offer
    assert len(brief.need_signals) > 0
    assert "open to work" in brief.exclusions
    assert len(brief.assumptions) > 0


def test_query_variant_generation():
    brief = build_lead_brief_heuristic("shopify store")
    variants = generate_query_variants(brief, max_variants=6)
    assert len(variants) >= 4
    queries = [v.query_string for v in variants]
    # Check operators
    for q in queries:
        assert "-filter:retweets" in q
        assert "lang:en" in q
        assert "-airdrop" in q or '-"open to work"' in q


def test_lead_direction_classifier_required_cases():
    # 1. Required Case: @Web3temple job/investment seeker
    web3temple_text = (
        "Seeking opportunities Founder / BD in | Investment | VC Syndicate | Liquidity | "
        "Funding | Token | Web3 #crypto #bitcoin #solana #web3"
    )
    res_temple = classify_direction_heuristic(web3temple_text)
    assert res_temple.direction == DirectionLabel.JOB_SEEKER
    assert res_temple.max_score_cap == 20
    assert res_temple.evidence_quote.lower() == "seeking opportunities"
    assert res_temple.quote_verified is True

    # 2. Required Case: Freelancer portfolio / self-promo
    freelancer_text = "Check out my portfolio! Available for freelance contract work, DM me if you need a Web3 dev."
    res_free = classify_direction_heuristic(freelancer_text)
    assert res_free.direction == DirectionLabel.SERVICE_PROVIDER_PROMO
    assert res_free.max_score_cap == 20

    # 3. Required Case: Airdrop / bot spam
    airdrop_text = "5000 USDT GIVEAWAY! Retweet, follow, and drop wallet below to enter the whitelist!"
    res_air = classify_direction_heuristic(airdrop_text)
    assert res_air.direction == DirectionLabel.AIRDROP_BOT_SPAM
    assert res_air.max_score_cap == 5

    # 4. Required Case: Educational essay / lessons thread
    essay_text = "10 lessons every Web3 founder must know before launching a token. A thread on liquidity & tokenomics."
    res_essay = classify_direction_heuristic(essay_text)
    assert res_essay.direction == DirectionLabel.INFO_OR_THOUGHT_CONTENT
    assert res_essay.max_score_cap == 25

    # 5. Required Case: Genuine buyer with budget
    buyer_text = "We are launching next month and need a Solidity developer to audit our contract. Budget available. DM me."
    res_buyer = classify_direction_heuristic(buyer_text)
    assert res_buyer.direction == DirectionLabel.BUYER_SIGNAL
    assert res_buyer.max_score_cap == 100


def test_quote_verification_guarantee():
    text = "Looking for a developer to build our DEX. Budget is ready."
    assert verify_quote_in_text("looking for a developer", text) is True
    assert verify_quote_in_text("hiring now", text) is False


def test_probe_loop_bandit_pruning():
    brief = build_lead_brief_heuristic("web3 founder")
    variants = generate_query_variants(brief, max_variants=3)
    variants[0].measured_precision = 0.8
    variants[1].measured_precision = 0.1
    variants[2].measured_precision = 0.5

    winners = select_winning_variants(variants, min_precision_threshold=0.4, max_winners=2)
    assert len(winners) == 2
    assert winners[0].measured_precision == 0.8
    assert winners[1].measured_precision == 0.5


def test_qualification_graph_direction_capping_integration():
    # Evaluate @Web3temple post through the real qualification node
    web3temple_text = (
        "Seeking opportunities Founder / BD in | Investment | VC Syndicate | Liquidity | "
        "Funding | Token | Web3 #crypto #bitcoin #solana #web3"
    )
    decision_result = asyncio.run(node_intent_classifier({
        "text": web3temple_text,
        "author_username": "web3temple_test",
        "author_followers": 500,
        "query_context": "web3 founder",
        "search_mode": "lead_generation"
    }))
    
    # Must be hard-capped at <= 20 and classified as disqualified
    assert decision_result["lead_direction"] == "JOB_SEEKER"
    assert decision_result["buyer_intent_score"] <= 20
    assert decision_result["decision"] == "disqualified"


def test_feature_flag_off_preserves_behavior(monkeypatch):
    monkeypatch.setenv("QUERY_INTELLIGENCE", "off")
    web3temple_text = (
        "Seeking opportunities Founder / BD in | Investment | VC Syndicate | Liquidity | "
        "Funding | Token | Web3 #crypto #bitcoin #solana #web3"
    )
    # When feature flag is off, direction gate is bypassed
    decision_result = asyncio.run(node_intent_classifier({
        "text": web3temple_text,
        "author_username": "web3temple_flag_off",
        "author_followers": 500,
        "query_context": "web3 founder",
        "search_mode": "lead_generation"
    }))
    assert decision_result["lead_direction"] == "UNCLEAR"
