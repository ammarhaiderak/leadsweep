# NEW FEATURE: Lead Intelligence Brief Builder
"""
Builds a structured LeadBrief from a raw user query.
Features:
1. Checks user profile table (`li_profile`) first for existing 'What I sell' configuration.
2. Ingests learned negatives from `li_negatives` table.
3. Calculates query ambiguity (0.0 to 1.0). If ambiguity > 0.5 and offer unknown, triggers clarify interrupt.
4. Uses Pydantic structured output with ChatGroq (or heuristic fallback on outage).
5. Persists brief in `li_brief_cache`.
"""
import json
import uuid
import logging
import sqlite3
from typing import Optional, Dict, Any, List, Tuple
from pydantic import BaseModel

from leadsweep.leadintel.models import LeadBrief
from leadsweep.leadintel.profile import get_user_profile
from leadsweep.leadintel.llm import get_configured_chat_model

log = logging.getLogger("leadsweep.leadintel.brief")

DEFAULT_EXCLUSIONS = [
    "open to work",
    "looking for work",
    "hire me",
    "my portfolio",
    "available for hire",
    "seeking opportunities",
    "airdrop",
    "giveaway",
    "whitelist",
    "presale",
    "follow me",
    "drop wallet"
]

DEFAULT_NEED_SIGNALS = [
    "looking for",
    "need a",
    "anyone recommend",
    "who can build",
    "hiring",
    "RFP",
    "budget available",
    "DM me your rates",
    "need help with"
]

DEFAULT_PAIN_POINTS = [
    "struggling with",
    "contract got exploited",
    "can't find a reliable",
    "tired of",
    "our dev left",
    "broken integration"
]


def compute_query_ambiguity(query: str, offer_known: bool) -> float:
    """Computes ambiguity score (0.0 = clear, 1.0 = completely vague)."""
    q = query.strip()
    words = q.split()
    if not offer_known:
        if len(words) <= 2:
            return 0.8  # e.g. "web3 founder" with no offer
        elif len(words) <= 4:
            return 0.6
    else:
        if len(words) <= 2:
            return 0.3
    return 0.1


def build_brief_heuristic(raw_query: str, user_offer: Optional[str] = None, offer_type: str = "services") -> LeadBrief:
    """Deterministic fallback LeadBrief generator."""
    q_lower = raw_query.strip().lower()
    assumptions = []
    
    if user_offer:
        offer = user_offer
    else:
        if any(w in q_lower for w in ["web3", "crypto", "blockchain", "solidity"]):
            offer = "Web3 smart contract development, protocol engineering, and security audits"
            assumptions.append("Inferred Web3 development and audit service provider.")
        elif any(w in q_lower for w in ["shopify", "ecommerce", "store"]):
            offer = "Shopify development, headless e-commerce, and CRO optimization"
            assumptions.append("Inferred Shopify & e-commerce agency offer.")
        elif any(w in q_lower for w in ["developer", "dev", "engineer"]):
            offer = "Full-stack software engineering and developer staffing"
            assumptions.append("Inferred custom software engineering services.")
        elif any(w in q_lower for w in ["ai", "startup"]):
            offer = "AI implementation, LLM integration, and autonomous agents development"
            assumptions.append("Inferred AI consulting and engineering offer.")
        else:
            offer = f"B2B service providing solutions for {raw_query.strip()}"
            assumptions.append(f"Derived general B2B provider offer for target query: '{raw_query}'.")

    roles = ["founder", "CEO", "CTO", "co-founder", "builder", "head of product"]
    domains = [raw_query.replace("founder", "").replace("store", "").strip() or "Tech"]

    ambiguity = compute_query_ambiguity(raw_query, offer_known=bool(user_offer))

    return LeadBrief(
        offer=offer,
        offer_type=offer_type,
        icp_roles=roles,
        icp_domains=domains,
        geo=[],
        language="en",
        need_signals=DEFAULT_NEED_SIGNALS.copy(),
        pain_points=DEFAULT_PAIN_POINTS.copy(),
        include_hiring_posts=True,
        exclusions=DEFAULT_EXCLUSIONS.copy(),
        recency_days=14,
        target_count=50,
        quality_bar=0.6,
        assumptions=assumptions,
        ambiguity=ambiguity
    )


async def build_lead_brief(
    raw_query: str,
    conn: Optional[sqlite3.Connection] = None,
    user_id: str = "default_user",
    allow_interrupt: bool = False
) -> Tuple[LeadBrief, bool]:
    """
    Main entrypoint:
    Builds a LeadBrief using user profile or structured LLM synthesis.
    Returns: (LeadBrief, requires_clarification)
    """
    user_offer = None
    offer_type = "services"
    icp_roles = []
    icp_domains = []
    learned_negs = []

    # 1. Check existing user sales profile in SQLite
    if conn:
        profile = get_user_profile(conn, user_id)
        if profile and profile.get("offer"):
            user_offer = profile["offer"]
            offer_type = profile.get("offer_type", "services")
            icp_roles = profile.get("icp_roles", [])
            icp_domains = profile.get("icp_domains", [])

        # Fetch learned negatives
        try:
            cur = conn.cursor()
            cur.execute("SELECT term FROM li_negatives WHERE is_safe = 1 AND reject_count >= 1")
            learned_negs = [r[0] for r in cur.fetchall()]
        except Exception:
            pass

    # 2. Check if ambiguity requires clarify interrupt
    ambiguity = compute_query_ambiguity(raw_query, offer_known=bool(user_offer))
    requires_clarification = (ambiguity > 0.5 and not user_offer and allow_interrupt)

    # 3. Build brief via LLM or deterministic fallback
    chat = get_configured_chat_model()
    brief = None

    if chat and not requires_clarification:
        try:
            prompt = (
                "You are a Lead Intelligence Engine planning agent.\n"
                "Analyze this search query and extract a structured B2B Lead Brief targeting real buyers.\n\n"
                f"RAW SEARCH QUERY: '{raw_query}'\n"
                f"USER OFFER (If known): '{user_offer or 'Not specified'}'\n\n"
                "Return a complete LeadBrief schema."
            )
            structured_llm = chat.with_structured_output(LeadBrief)
            brief = await structured_llm.ainvoke(prompt)
        except Exception as e:
            log.warning(f"LLM structured brief generation failed: {e}. Falling back to deterministic rules.")

    if not brief:
        brief = build_brief_heuristic(raw_query, user_offer=user_offer, offer_type=offer_type)

    # Enrich with learned negatives
    for neg in learned_negs:
        if neg not in brief.exclusions:
            brief.exclusions.append(neg)

    # Persist in li_brief_cache if conn present
    if conn:
        try:
            brief_id = str(uuid.uuid4())
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO li_brief_cache (brief_id, raw_query, brief_json)
                VALUES (?, ?, ?)
            """, (brief_id, raw_query, brief.model_dump_json()))
            conn.commit()
        except Exception as e:
            log.warning(f"Failed to cache brief: {e}")

    return brief, requires_clarification


calculate_query_ambiguity = compute_query_ambiguity


def build_lead_brief_sync(raw_query: str, user_profile: Optional[Dict[str, Any]] = None) -> LeadBrief:
    """Synchronous builder for LeadBrief used by LangGraph nodes and offline tools."""
    user_offer = user_profile.get("offer") if user_profile else None
    offer_type = user_profile.get("offer_type", "services") if user_profile else "services"
    return build_brief_heuristic(raw_query, user_offer=user_offer, offer_type=offer_type)

