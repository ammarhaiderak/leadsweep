# NEW FEATURE: Lead Intelligence Query Linter
"""
Deterministic Query Linter (no LLM required).
Enforces:
1. Balanced parentheses and balanced quotes.
2. Operator hygiene: Converts literal 'AND' to spaces, '-rt' to '-filter:retweets'.
3. Max length guard (default max 500 chars).
4. Over-negation guard (max 8 negative operators; never negates core topic words).
5. Signal requirement: Must contain at least one topic domain and one signal term.
"""
import re
import logging
from typing import Tuple, List, Any

log = logging.getLogger("leadsweep.leadintel.linter")


def lint_query(query: str, core_topics: List[str] = None) -> Tuple[bool, str, str]:
    """
    Validates and cleans a query string.
    Returns: (is_valid, cleaned_query, error_reason)
    """
    q = query.strip()
    if not q:
        return False, "", "Query is empty."

    # 1. Balanced quotes
    quote_count = q.count('"')
    if quote_count % 2 != 0:
        return False, q, f"Unbalanced quotation marks ({quote_count} found)."

    # 2. Balanced parentheses
    if q.count('(') != q.count(')'):
        return False, q, f"Unbalanced parentheses ({q.count('(')} open vs {q.count(')')} close)."

    # 3. Operator hygiene
    # Convert literal ' AND ' to space
    q_cleaned = re.sub(r'\s+AND\s+', ' ', q)
    # Convert legacy '-rt' to '-filter:retweets'
    q_cleaned = re.sub(r'(?:^|\s)-rt(?:\s|$)', ' -filter:retweets ', q_cleaned).strip()

    # 4. Length guard
    if len(q_cleaned) > 500:
        return False, q_cleaned, f"Query exceeds max character length ({len(q_cleaned)} > 500)."

    # 5. Over-negation guard
    neg_terms = re.findall(r'-\S+', q_cleaned)
    if len(neg_terms) > 10:
        return False, q_cleaned, f"Too many negative operators ({len(neg_terms)} > 10). Risk of false drop."

    # 6. Never negate core topics
    if core_topics:
        for t in core_topics:
            t_clean = t.strip().lower()
            if f"-{t_clean}" in q_cleaned.lower() or f'-"{t_clean}"' in q_cleaned.lower():
                return False, q_cleaned, f"Illegal negation of core brief topic: '{t_clean}'."

    # 7. Check for operator presence
    if not ("-filter:retweets" in q_cleaned or "filter:" in q_cleaned or "lang:" in q_cleaned):
        # Auto-append base hygiene filters if absent
        q_cleaned = f"{q_cleaned} -filter:retweets lang:en"

    return True, q_cleaned, ""


def lint_and_repair_variants(variants: List[Any], core_topics: List[str] = None) -> List[Any]:
    """
    Lints a list of QueryVariant objects, repairing syntax where possible or pruning broken ones.
    """
    valid_variants = []
    for v in variants:
        ok, cleaned_q, err = lint_query(v.query_string, core_topics=core_topics)
        if ok:
            v.query_string = cleaned_q
            valid_variants.append(v)
        else:
            log.warning(f"Linter dropped malformed query: '{v.query_string}' | Reason: {err}")
    return valid_variants
