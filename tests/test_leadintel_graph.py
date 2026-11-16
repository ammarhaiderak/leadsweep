import os
import pytest
from leadsweep.leadintel.memory import (
    record_lead_feedback,
    get_feedback_history,
    update_calibrated_weights,
    generate_lookalike_queries,
)
from leadsweep.leadintel.graph import (
    build_lead_intel_graph,
    run_lead_intelligence,
    is_lead_intel_enabled,
)
from leadsweep.leadintel.profile import save_user_sales_profile


def test_feedback_and_model_calibration():
    # Record approvals and rejections
    record_lead_feedback(
        post_id="post_app_1",
        author_username="valid_buyer",
        action="approved",
        post_text="Need an experienced smart contract auditor urgently",
        author_bio="Founder @Web3Security",
        score_at_action=88.0,
    )
    record_lead_feedback(
        post_id="post_rej_1",
        author_username="spam_shill",
        action="rejected",
        rejection_reason="freelancer_promo",
        post_text="I am available for hire as solidity dev! DM me",
        author_bio="Freelance Web3 builder",
        score_at_action=45.0,
    )

    history = get_feedback_history(limit=10)
    assert len(history) >= 2
    usernames = [h["author_username"] for h in history]
    assert "valid_buyer" in usernames
    assert "spam_shill" in usernames

    # Calibration weights
    weights = update_calibrated_weights()
    assert "direction_weight" in weights
    assert "topic_weight" in weights
    assert weights["direction_weight"] > 0


def test_lookalike_query_generation():
    # Generate lookalikes based on recorded approvals
    from leadsweep.leadintel.models import StrategyType
    lookalikes = generate_lookalike_queries(brief_core_terms=["solidity"], max_variants=2)
    assert isinstance(lookalikes, list)
    if lookalikes:
        assert lookalikes[0].strategy == StrategyType.S7_LOOKALIKE
        assert "solidity" in lookalikes[0].query_string.lower()


def test_full_graph_execution_with_candidates():
    # Setup seller profile so graph does not interrupt for clarification
    save_user_sales_profile(
        offering="Smart contract auditing and formal verification",
        target_customer="Web3 and DeFi founders launching protocols",
        deal_size_tier="mid",
    )

    sample_candidates = [
        {
            "id": "1",
            "text": "Looking for a reliable team to audit our lending protocol before mainnet launch",
            "author_username": "defi_founder",
            "author_name": "DeFi Builder",
            "author_bio": "Founder & CEO @DeFiProtocol. Launching on Arbitrum.",
            "rule_score": 85.0,
        },
        {
            "id": "2",
            "text": "Open for work! 3 years experience building smart contracts. Hire me!",
            "author_username": "freelancer_dev",
            "author_name": "Junior Dev",
            "author_bio": "Seeking web3 jobs. Solidity intern.",
            "rule_score": 80.0,
        },
        {
            "id": "3",
            "text": "Join our 50,000 $AIRDROP giveaway! Drop your wallet address and retweet",
            "author_username": "crypto_drop_bot",
            "author_name": "Airdrop Alert",
            "author_bio": "Free tokens daily!",
            "rule_score": 75.0,
        },
    ]

    result = run_lead_intelligence(
        raw_query="web3 founder",
        candidates=sample_candidates,
        max_budget=30,
    )

    assert result["status"] == "completed"
    assert len(result["linted_variants"]) >= 3
    final_leads = result["final_leads"]

    # Genuine buyer should be top ranked and uncapped
    assert len(final_leads) > 0
    top_lead = final_leads[0]
    assert top_lead["author_username"] == "defi_founder"
    assert top_lead["direction_label"] == "BUYER_SIGNAL"
    assert top_lead["score_v2"] >= 70

    # Job seeker and airdrop bot should be capped or excluded
    for lead in final_leads:
        if lead["author_username"] == "freelancer_dev":
            assert lead["score_v2"] <= 20
        if lead["author_username"] == "crypto_drop_bot":
            assert lead["score_v2"] <= 5


def test_ambiguity_clarification_interrupt():
    # Clear profile to simulate new user with no profile and vague query
    import sqlite3
    from leadsweep.leadintel.db import get_connection
    with get_connection() as conn:
        conn.execute("DELETE FROM li_profile")

    result = run_lead_intelligence(
        raw_query="web3",
        candidates=[],
    )

    # High ambiguity query without profile should request clarification
    assert result["needs_clarification"] is True
    assert result["status"] == "awaiting_clarification"
    assert len(result["clarification_options"]) > 0


def test_feature_flag_bypass():
    os.environ["LEAD_INTEL"] = "off"
    try:
        assert not is_lead_intel_enabled()
        sample = [{"id": "1", "text": "test post"}]
        result = run_lead_intelligence(
            raw_query="shopify store",
            candidates=sample,
        )
        assert result["status"] == "bypassed_lead_intel_off"
        assert result["final_leads"] == sample
    finally:
        os.environ["LEAD_INTEL"] = "on"
