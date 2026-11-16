# NEW FEATURE: Lead Intelligence Phase E Tests
"""
Unit and integration tests for Phase E:
1. Author profile enrichment (decision maker, contact link, bot detection).
2. Near-duplicate deduplication (dropping bot copy-pastes while keeping genuine leads).
3. Lookalike boost calculation (positive boost for approved leads, penalty for rejected leads).
4. Account-level lead aggregation (consolidating multiple posts by same author).
"""
import pytest
from leadsweep.leadintel.enrichment import (
    enrich_author_profile,
    deduplicate_near_duplicates,
    calculate_lookalike_boost,
    aggregate_account_leads
)


def test_author_enrichment():
    author_founder = {
        "description": "Founder & CEO @DeFiProtocol. Contact: https://defiprotocol.io or t.me/founder",
        "followers_count": 8500,
        "username": "defi_ceo"
    }
    enriched = enrich_author_profile(author_founder)
    assert enriched["is_decision_maker"] is True
    assert enriched["has_contact_link"] is True
    assert enriched["is_likely_bot"] is False
    assert enriched["followers_tier"] == "high"

    author_bot = {
        "description": "",
        "followers_count": 0,
        "username": "user192837482"
    }
    enriched_bot = enrich_author_profile(author_bot)
    assert enriched_bot["is_likely_bot"] is True


def test_near_duplicate_deduplication():
    # 3 posts: post 1 and 2 are near-duplicate bot tweets; post 3 is unique
    posts = [
        {"id": "1", "text": "5000 USDT giveaway! Retweet, follow, and drop your wallet address below to enter!"},
        {"id": "2", "text": "5000 USDT giveaway! Retweet, follow, and drop your wallet address below to enter now!"},
        {"id": "3", "text": "We need a Solidity developer to audit our liquidity contract, budget $10k."}
    ]
    deduped = deduplicate_near_duplicates(posts, similarity_threshold=0.85)
    assert len(deduped) == 2
    # Genuine buyer post must be preserved
    assert any("Solidity developer" in p["text"] for p in deduped)


def test_lookalike_similarity_boost():
    approved = [
        "Looking for a Solidity smart contract developer to build our DEX.",
        "Need an experienced Rust backend engineer for blockchain indexer."
    ]
    rejected = [
        "5000 USDT giveaway presale airdrop drop wallet.",
        "Seeking opportunities as a junior developer hire me."
    ]

    # Candidate resembles approved lead
    cand_good = "Looking for an engineer to audit our Solana smart contract."
    boost_good = calculate_lookalike_boost(cand_good, approved, rejected)
    assert boost_good > 0.0

    # Candidate resembles rejected airdrop
    cand_bad = "Giveaway alert! Retweet and claim your token presale."
    boost_bad = calculate_lookalike_boost(cand_bad, approved, rejected)
    assert boost_bad < 0.0


def test_account_level_lead_aggregation():
    # Author @alice posted twice: one general post (score 45), one urgent procurement post (score 85)
    items = [
        {"id": "1", "author_username": "alice", "final_score": 45, "text": "Building in public today!"},
        {"id": "2", "author_username": "alice", "final_score": 85, "text": "Urgently hiring a Solidity auditor. Budget $20k."},
        {"id": "3", "author_username": "bob", "final_score": 75, "text": "Need a React developer for our dApp."}
    ]
    aggregated = aggregate_account_leads(items)
    assert len(aggregated) == 2  # Alice and Bob
    
    alice_lead = next(l for l in aggregated if l["author_username"] == "alice")
    assert alice_lead["final_score"] == 85
    assert alice_lead["total_posts_seen"] == 2
    assert len(alice_lead["post_history_snippets"]) == 2
