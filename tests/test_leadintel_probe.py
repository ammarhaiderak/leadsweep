# NEW FEATURE: Lead Intelligence Phase D Tests
"""
Unit and integration tests for Phase D:
1. Candidate judging: Direction classification, topic gate, Score v2 calculation.
2. Hard caps enforcement: Job seeker capped <= 20, promo <= 20, airdrop <= 5, buyer >= 70.
3. Probe evaluation & precision rate calculation per variant.
4. Bandit allocator: Pruning variants below floor and allocating winners.
5. Learning from noise: Extracting recurring noise terms as negatives.
"""
import pytest
import sqlite3
from leadsweep.leadintel.models import DirectionLabel, StrategyType, QueryVariant
from leadsweep.leadintel.db import init_leadintel_tables
from leadsweep.leadintel.brief import build_brief_heuristic
from leadsweep.leadintel.judge import judge_candidate
from leadsweep.leadintel.probe import evaluate_probe_batch, allocate_bandit_winners, extract_learned_negatives_from_noise


def test_judge_candidate_scoring_and_caps():
    brief = build_brief_heuristic("web3 founder")

    # 1. @Web3temple job seeker post
    seeker_text = "Seeking opportunities Founder / BD in | Investment | VC Syndicate | Liquidity | Funding | Token | Web3"
    score_seeker = judge_candidate(seeker_text, author_bio="Web3 builder", brief=brief)
    assert score_seeker.direction == DirectionLabel.JOB_SEEKER
    assert score_seeker.final_score <= 20
    assert "Disqualified: Author is seeking opportunities" in score_seeker.why_text

    # 2. Freelancer self-promo post
    promo_text = "Check out my portfolio! Available for freelance smart contract development. DM me!"
    score_promo = judge_candidate(promo_text, author_bio="Solidity dev", brief=brief)
    assert score_promo.direction == DirectionLabel.SERVICE_PROVIDER_PROMO
    assert score_promo.final_score <= 20

    # 3. Airdrop bot post
    airdrop_text = "5000 USDT GIVEAWAY! Retweet, follow, and drop wallet below!"
    score_air = judge_candidate(airdrop_text, brief=brief)
    assert score_air.direction == DirectionLabel.AIRDROP_BOT_SPAM
    assert score_air.final_score <= 5

    # 4. Genuine Buyer
    buyer_text = "We are launching next month and need a Solidity developer to audit our contracts. Budget $20k."
    score_buyer = judge_candidate(buyer_text, author_bio="DeFi Founder", author_followers=2500, brief=brief)
    assert score_buyer.direction == DirectionLabel.BUYER_SIGNAL
    assert score_buyer.final_score >= 70
    assert score_buyer.quote_verified is True


def test_judge_topic_relevance_gate_enforcement():
    brief = build_brief_heuristic("web3 founder")
    # Streetwear designer hiring (off-topic for Web3 query)
    streetwear_text = "Need a developer to design streetwear clothing Shopify store urgently."
    # When topic_rel_score < 40, must be hard capped at <= 15
    score_off = judge_candidate(streetwear_text, topic_rel_score=20, brief=brief)
    assert score_off.final_score <= 15


def test_probe_evaluation_and_stats(tmp_path):
    db_file = tmp_path / "test_probe.db"
    conn = sqlite3.connect(str(db_file))
    init_leadintel_tables(conn)

    brief = build_brief_heuristic("web3 founder")
    variant = QueryVariant(
        strategy=StrategyType.S1_NEED_SIGNAL,
        query_string='(web3) "need a developer" lang:en',
        rationale="Direct need search"
    )

    items = [
        {"text": "Need a developer to audit our smart contract, budget available. DM me!"},
        {"text": "Seeking opportunities Founder / BD in Web3. Open to work."},
        {"text": "5000 USDT giveaway! Retweet and drop wallet."}
    ]

    total, buyers, prec, rejected = evaluate_probe_batch(variant, items, brief, conn=conn)
    assert total == 3
    assert buyers == 1
    assert prec == 0.333
    assert len(rejected) == 2

    conn.close()


def test_bandit_allocation():
    v1 = QueryVariant(strategy=StrategyType.S1_NEED_SIGNAL, query_string="q1", rationale="r1", measured_precision=0.75)
    v2 = QueryVariant(strategy=StrategyType.S2_PAIN_POINT, query_string="q2", rationale="r2", measured_precision=0.10)
    v3 = QueryVariant(strategy=StrategyType.S3_ICP_BIO, query_string="q3", rationale="r3", measured_precision=0.60)

    winners = allocate_bandit_winners([v1, v2, v3], min_precision_floor=0.4, max_winners=2)
    assert len(winners) == 2
    assert winners[0].query_string == "q1"
    assert winners[1].query_string == "q3"


def test_extract_learned_negatives_from_noise():
    brief = build_brief_heuristic("web3 founder")
    rejected = [
        "Huge giveaway! Retweet and drop wallet for our token whitelist.",
        "Whitelist presale giveaway now live! Claim airdrop.",
        "Check out my portfolio, looking for work."
    ]
    learned = extract_learned_negatives_from_noise(rejected, brief, min_occurrences=2)
    assert "giveaway" in learned
    assert "whitelist" in learned
