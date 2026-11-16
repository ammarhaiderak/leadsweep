# NEW FEATURE: Query Intelligence Orchestrator
"""
Main pipeline coordinator for Query Intelligence.
Safely hooks into pre-search query generation and manages Lead Briefs and variants.
Controlled by QUERY_INTELLIGENCE=on|off.
"""
import os
import json
import logging
from typing import List, Optional, Dict, Any, Tuple
from leadsweep.intel.brief import init_intel_tables, build_lead_brief
from leadsweep.intel.generator import generate_query_variants
from leadsweep.intel.probe import select_winning_variants
from leadsweep.intel.models import LeadBrief, QueryVariant

logger = logging.getLogger("leadsweep.intel.orchestrator")


def is_query_intelligence_enabled() -> bool:
    """Check feature flag QUERY_INTELLIGENCE (default 'on')."""
    val = os.getenv("QUERY_INTELLIGENCE", "on").strip().lower()
    return val in ("on", "true", "1", "yes")


async def run_query_intelligence_pre_search(
    raw_queries: List[str],
    job_id: Optional[str] = None,
    user_id: str = "default_user",
    conn=None
) -> Tuple[List[str], Optional[LeadBrief]]:
    """
    Transforms vague raw queries into targeted, high-precision search variants.
    If disabled via feature flag, returns raw_queries unchanged.
    """
    if not is_query_intelligence_enabled() or not raw_queries:
        return raw_queries, None

    try:
        if conn:
            init_intel_tables(conn)

        compiled_queries = []
        first_brief = None

        for raw_q in raw_queries:
            # Build structured Lead Brief
            brief = await build_lead_brief(raw_q, conn=conn, user_id=user_id, job_id=job_id)
            if not first_brief:
                first_brief = brief

            # Generate strategic query variants
            variants = generate_query_variants(brief, max_variants=6)
            
            # Select top variants
            winning = select_winning_variants(variants, max_winners=3)
            for w in winning:
                compiled_queries.append(w.query_string)

        logger.info(f"Query Intelligence compiled {len(raw_queries)} raw queries into {len(compiled_queries)} targeted variants.")
        return compiled_queries if compiled_queries else raw_queries, first_brief

    except Exception as e:
        logger.error(f"Query Intelligence pre-search failed gracefully: {e}", exc_info=True)
        return raw_queries, None
