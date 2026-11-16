# NEW FEATURE: Query Intelligence Lead Brief Builder
"""
Builds and persists structured LeadBrief objects from raw queries,
reusing stored user sales profiles or extracting structured intent via LLM/rules.
"""
import os
import json
import uuid
import logging
from typing import Optional, Dict, Any, List
from leadsweep.intel.models import LeadBrief, ICPProfile

logger = logging.getLogger("leadsweep.intel.brief")

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


def init_intel_tables(conn) -> None:
    """Additive SQLite tables for Query Intelligence."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_sales_profiles (
            user_id TEXT PRIMARY KEY,
            offer TEXT NOT NULL,
            icp_target TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lead_briefs (
            brief_id TEXT PRIMARY KEY,
            job_id TEXT,
            user_id TEXT,
            raw_query TEXT NOT NULL,
            offer TEXT NOT NULL,
            icp JSON,
            need_signals JSON,
            exclusions JSON,
            assumptions JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS query_variant_stats (
            id TEXT PRIMARY KEY,
            brief_id TEXT,
            query_string TEXT NOT NULL,
            strategy TEXT NOT NULL,
            probe_count INTEGER DEFAULT 0,
            buyers_found INTEGER DEFAULT 0,
            precision_rate REAL DEFAULT 0.0,
            learned_negatives JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lead_feedback_learned (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            term TEXT NOT NULL,
            feedback_type TEXT NOT NULL, -- 'reject' or 'approve'
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()


def get_user_sales_profile(conn, user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve existing 'What I sell' profile for user."""
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, offer, icp_target FROM user_sales_profiles WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            return {"user_id": row[0], "offer": row[1], "icp_target": row[2]}
    except Exception as e:
        logger.warning(f"Failed to fetch user sales profile: {e}")
    return None


def save_user_sales_profile(conn, user_id: str, offer: str, icp_target: Optional[str] = None) -> None:
    """Save or update 'What I sell' profile."""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO user_sales_profiles (user_id, offer, icp_target, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                offer = excluded.offer,
                icp_target = excluded.icp_target,
                updated_at = CURRENT_TIMESTAMP;
        """, (user_id, offer, icp_target))
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to save user sales profile: {e}")


def get_learned_negatives(conn, user_id: str) -> List[str]:
    """Retrieve learned negative rejection terms from past feedback."""
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT term FROM lead_feedback_learned WHERE user_id = ? AND feedback_type = 'reject'", (user_id,))
        rows = cursor.fetchall()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []


def build_lead_brief_heuristic(raw_query: str, user_offer: Optional[str] = None) -> LeadBrief:
    """
    Deterministic rule-based Lead Brief builder for 100% reliability, speed, and $0 cost.
    """
    cleaned = raw_query.strip().lower()
    brief_id = str(uuid.uuid4())
    
    # Infer or fallback offer
    offer = user_offer or f"B2B service/product addressing {raw_query.strip()}"
    assumptions = []
    
    if not user_offer:
        if "web3" in cleaned or "solidity" in cleaned or "crypto" in cleaned:
            offer = "Web3 Development, Smart Contract Audits, and Growth Services"
            assumptions.append("Assuming user offers Web3/blockchain technical or growth services to founders.")
        elif "shopify" in cleaned or "ecommerce" in cleaned:
            offer = "Shopify/E-commerce Development, CRO, and Marketing Services"
            assumptions.append("Assuming user offers E-commerce development or optimization services.")
        elif "developer" in cleaned or "dev" in cleaned:
            offer = "Software Engineering, Dev Agency, and Technical Staffing"
            assumptions.append("Assuming user is a software agency or engineering provider.")
        elif "marketing" in cleaned:
            offer = "B2B Marketing, Lead Generation, and Growth Strategy"
            assumptions.append("Assuming user provides growth and marketing services.")
        elif "ai" in cleaned:
            offer = "AI Implementation, LLM Engineering, and AI Automation"
            assumptions.append("Assuming user offers AI/ML development and integration.")
        else:
            assumptions.append(f"Derived general B2B provider offer for target query: '{raw_query}'.")

    # Roles and ICP
    roles = ["founder", "co-founder", "CEO", "CTO", "builder", "head of product"]
    industries = [raw_query.replace("founder", "").replace("store", "").strip() or "Tech"]
    
    icp = ICPProfile(
        roles=roles,
        industries=industries,
        company_stage="Seed / Growth",
        geography="Global",
        language="en"
    )
    
    return LeadBrief(
        brief_id=brief_id,
        raw_query=raw_query,
        offer=offer,
        icp=icp,
        need_signals=DEFAULT_NEED_SIGNALS.copy(),
        exclusions=DEFAULT_EXCLUSIONS.copy(),
        recency_days=30,
        volume_target=50,
        quality_bar=0.7,
        assumptions=assumptions
    )


async def build_lead_brief(
    raw_query: str,
    conn=None,
    user_id: str = "default_user",
    job_id: Optional[str] = None
) -> LeadBrief:
    """
    Main entrypoint: creates a structured Lead Brief.
    Checks user profile first, enriches with learned negatives, and builds brief.
    """
    user_offer = None
    learned_negatives = []
    
    if conn:
        profile = get_user_sales_profile(conn, user_id)
        if profile and profile.get("offer"):
            user_offer = profile["offer"]
        learned_negatives = get_learned_negatives(conn, user_id)

    brief = build_lead_brief_heuristic(raw_query, user_offer=user_offer)
    
    # Merge learned negatives
    for neg in learned_negatives:
        if neg not in brief.exclusions:
            brief.exclusions.append(neg)

    # Persist in lead_briefs table if conn is present
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO lead_briefs (
                    brief_id, job_id, user_id, raw_query, offer, icp, need_signals, exclusions, assumptions
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                brief.brief_id,
                job_id,
                user_id,
                brief.raw_query,
                brief.offer,
                json.dumps(brief.icp.model_dump()),
                json.dumps(brief.need_signals),
                json.dumps(brief.exclusions),
                json.dumps(brief.assumptions)
            ))
            conn.commit()
        except Exception as e:
            logger.warning(f"Could not persist lead brief: {e}")

    return brief
