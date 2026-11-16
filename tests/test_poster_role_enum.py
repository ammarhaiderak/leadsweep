import pytest
from leadsweep.pipeline.qualification_graph import (
    LeadJudgeContract,
    normalize_poster_role,
    node_consistency_and_calibration,
    LeadState,
)


def test_normalize_poster_role_aliases():
    cases = [
        ("requester", "requester", False),
        ("recruiter", "recruiter", False),
        ("aggregator", "aggregator", False),
        ("seller", "seller", False),
        ("advisor", "advisor", False),
        ("bystander", "bystander", False),
        ("unknown", "unknown", False),
        # Known Aliases
        ("job_board", "aggregator", True),
        ("job_platform", "aggregator", True),
        ("hiring_manager", "recruiter", True),
        ("company", "recruiter", True),
        ("founder", "requester", True),
        ("client", "requester", True),
        ("consultant", "advisor", True),
        ("vendor", "seller", True),
        ("observer", "bystander", True),
        # Unrecognized
        ("some_random_role_xyz", "unknown", True),
        (None, "unknown", False),
    ]
    for raw, expected_role, expected_norm in cases:
        role, is_norm = normalize_poster_role(raw)
        assert role == expected_role, f"Failed for {raw}: got {role}, expected {expected_role}"
        assert is_norm == expected_norm, f"Norm flag mismatch for {raw}: got {is_norm}, expected {expected_norm}"


def test_lead_judge_contract_validates_and_normalizes_poster_role():
    # Model returns job_board
    contract = LeadJudgeContract(
        category="HIRING_OR_CONTRACT",
        score=85,
        evidence_quote="hiring engineers",
        reason="job board posting",
        confidence=0.9,
        poster_role="job_board",
        intent_type="recruitment",
    )
    assert contract.poster_role == "aggregator"

    # Model returns hiring_manager
    contract2 = LeadJudgeContract(
        category="HIRING_OR_CONTRACT",
        score=85,
        evidence_quote="hiring engineers",
        reason="hiring manager post",
        confidence=0.9,
        poster_role="hiring_manager",
        intent_type="recruitment",
    )
    assert contract2.poster_role == "recruiter"


@pytest.mark.asyncio
async def test_calibration_runs_after_normalization_and_clamps_aggregator():
    # Aggregator item scored 85 by model with role 'job_board'
    state: LeadState = {
        "tweet_id": "test_tg_1",
        "primary_category": "HIRING_OR_CONTRACT",
        "buyer_intent_score": 85,
        "poster_role": "job_board",  # un-normalized alias
        "reasoning_summary": "Digest of open positions",
        "evaluator": "llm",
        "decision": "qualified",
    }
    result = await node_consistency_and_calibration(state)
    assert result["poster_role"] == "aggregator"
    assert result["role_normalized"] is True
    # Clamped into aggregator band [60, 75]
    assert result["buyer_intent_score"] <= 75
    assert result["buyer_intent_score"] >= 60
    assert result["calibration_adjusted"] is True
