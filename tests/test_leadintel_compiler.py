# NEW FEATURE: Lead Intelligence Phase C Tests
"""
Unit and integration tests for Phase C:
1. User sales profile store & retrieval
2. LeadBrief building (deterministic + LLM fallback)
3. Ambiguity calculation and clarify interrupt triggering
4. Strategy portfolio selection across S1..S6
5. Query compilation (portfolio of 6-12 strategic variants)
6. Deterministic Query Linter hygiene, quote/parenthesis balancing, operator repair
"""
import pytest
import sqlite3
from leadsweep.leadintel.models import StrategyType, LeadBrief
from leadsweep.leadintel.db import init_leadintel_tables
from leadsweep.leadintel.profile import save_user_profile, get_user_profile
from leadsweep.leadintel.brief import build_brief_heuristic, compute_query_ambiguity
from leadsweep.leadintel.strategies import select_strategies_for_brief
from leadsweep.leadintel.compiler import compile_queries
from leadsweep.leadintel.linter import lint_query, lint_and_repair_variants


def test_user_sales_profile_store(tmp_path):
    db_file = tmp_path / "test_prof.db"
    conn = sqlite3.connect(str(db_file))
    init_leadintel_tables(conn)

    save_user_profile(
        conn,
        user_id="alice@example.com",
        offer="Web3 Smart Contract Audits & Protocol Engineering",
        offer_type="services",
        icp_roles=["founder", "CTO"],
        icp_domains=["DeFi", "Web3"]
    )

    p = get_user_profile(conn, "alice@example.com")
    assert p is not None
    assert "Smart Contract Audits" in p["offer"]
    assert "founder" in p["icp_roles"]
    assert "DeFi" in p["icp_domains"]
    conn.close()


def test_brief_ambiguity_calculation():
    # Vague query with unknown offer -> high ambiguity
    amb_vague = compute_query_ambiguity("web3 founder", offer_known=False)
    assert amb_vague >= 0.6

    # Vague query with known offer -> low ambiguity
    amb_known = compute_query_ambiguity("web3 founder", offer_known=True)
    assert amb_known <= 0.4


def test_brief_builder_heuristic():
    brief = build_brief_heuristic("shopify store")
    assert "Shopify" in brief.offer
    assert len(brief.need_signals) > 0
    assert len(brief.exclusions) > 0
    assert "open to work" in brief.exclusions


def test_strategy_portfolio_selection():
    brief = build_brief_heuristic("web3 founder")
    strategies = select_strategies_for_brief(brief)
    assert StrategyType.S1_NEED_SIGNAL in strategies
    assert StrategyType.S2_PAIN_POINT in strategies
    assert StrategyType.S3_ICP_BIO in strategies
    assert StrategyType.S5_TRIGGER_EVENTS in strategies


def test_query_compilation_and_portfolio():
    brief = build_brief_heuristic("web3 founder")
    strategies = select_strategies_for_brief(brief)
    variants = compile_queries(brief, strategies, target_count=8)

    assert len(variants) >= 5
    for v in variants:
        q = v.query_string
        assert "lang:en" in q
        assert "-filter:retweets" in q
        assert "AND" not in q  # Space used as AND


def test_query_linter_validation_and_repair():
    # 1. Unbalanced quotes
    ok, _, err = lint_query('("web3) dev')
    assert ok is False
    assert "Unbalanced quotation marks" in err

    # 2. Unbalanced parentheses
    ok, _, err = lint_query('(web3 OR crypto dev')
    assert ok is False
    assert "Unbalanced parentheses" in err

    # 3. Clean query with -rt conversion
    ok, clean_q, _ = lint_query('web3 -rt "looking for a dev"')
    assert ok is True
    assert "-filter:retweets" in clean_q
    assert "-rt" not in clean_q

    # 4. Over-negation prevention
    too_many_negs = 'web3 -a -b -c -d -e -f -g -h -i -j -k'
    ok, _, err = lint_query(too_many_negs)
    assert ok is False
    assert "Too many negative operators" in err

    # 5. Core topic negation prevention
    ok, _, err = lint_query('web3 -web3 "looking for dev"', core_topics=["web3"])
    assert ok is False
    assert "Illegal negation of core brief topic" in err
