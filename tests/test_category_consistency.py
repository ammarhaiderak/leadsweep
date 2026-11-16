import pytest
from leadsweep.pipeline.qualification_graph import map_score_and_role_to_category

def test_category_consistency_mapping():
    # Score 60 with aggregator role must ALWAYS map to HIRING_OR_CONTRACT
    cat_aggr = map_score_and_role_to_category(60, "aggregator")
    assert cat_aggr == "HIRING_OR_CONTRACT"

    # Score 60 with recruiter role must map to HIRING_OR_CONTRACT
    cat_rec = map_score_and_role_to_category(60, "recruiter")
    assert cat_rec == "HIRING_OR_CONTRACT"

    # Score 60 with advisor or bystander role must map to GENERAL_DISCUSSION (not HIRING_OR_CONTRACT)
    cat_adv = map_score_and_role_to_category(60, "advisor")
    assert cat_adv == "GENERAL_DISCUSSION"

    # High score (>= 70) with requester role maps to DIRECT_BUYING_INTENT
    cat_req = map_score_and_role_to_category(85, "requester")
    assert cat_req == "DIRECT_BUYING_INTENT"

    # Low score (< 50) maps to GENERAL_DISCUSSION
    cat_low = map_score_and_role_to_category(30, "recruiter")
    assert cat_low == "GENERAL_DISCUSSION"

    # Preserved spam exclusions
    cat_spam = map_score_and_role_to_category(60, "aggregator", "SPAM_OR_LOW_QUALITY")
    assert cat_spam == "SPAM_OR_LOW_QUALITY"
