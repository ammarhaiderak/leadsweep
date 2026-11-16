# NEW FEATURE: Lead Intelligence LLM Layer & Local Tracing
"""
LangChain LLM manager with:
- Groq primary (model from env, default openai/gpt-oss-120b)
- Optional Gemini fallback via with_fallbacks
- Heuristic fallback as last resort
- Token budget governor & rate limiter
- Local SQLite caching and tracing (zero paid LangSmith)
"""
import os
import time
import json
import hashlib
import logging
import sqlite3
from typing import Optional, Dict, Any, List
from pydantic import BaseModel

from leadsweep.leadintel.models import LeadIntelTrace
from leadsweep.leadintel.heuristics import classify_direction_rules

log = logging.getLogger("leadsweep.leadintel.llm")

# Rate limiters & tracking
_CALLS_THIS_MINUTE = 0
_LAST_MINUTE_TS = time.time()
MAX_RPM = int(os.getenv("GROQ_RPM", "30"))


def record_trace(
    conn: Optional[sqlite3.Connection],
    run_id: str,
    node_name: str,
    model_used: str,
    tokens_used: int = 0,
    latency_ms: float = 0.0,
    cache_hit: bool = False,
    fallback_used: bool = False
) -> None:
    """Log LLM execution telemetry directly into SQLite li_trace table."""
    if not conn:
        return
    try:
        import uuid
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO li_trace (id, run_id, node_name, model_used, tokens_used, latency_ms, cache_hit, fallback_used)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4()), run_id, node_name, model_used, tokens_used, latency_ms,
            1 if cache_hit else 0, 1 if fallback_used else 0
        ))
        conn.commit()
    except Exception as e:
        log.warning(f"Could not record local trace: {e}")


def get_cached_classification(conn: Optional[sqlite3.Connection], content_hash: str) -> Optional[Dict[str, Any]]:
    """Look up post in SQLite classification cache."""
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT result_json FROM li_classification_cache WHERE content_hash = ?", (content_hash,))
        row = cursor.fetchone()
        if row:
            return json.loads(row[0])
    except Exception:
        pass
    return None


def store_cached_classification(conn: Optional[sqlite3.Connection], content_hash: str, model_ver: str, result_dict: Dict[str, Any]) -> None:
    """Store result in SQLite classification cache."""
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO li_classification_cache (content_hash, model_version, result_json)
            VALUES (?, ?, ?)
        """, (content_hash, model_ver, json.dumps(result_dict)))
        conn.commit()
    except Exception as e:
        log.warning(f"Could not cache classification: {e}")


def get_configured_chat_model(model_name: Optional[str] = None):
    """
    Returns ChatGroq client with structured output support.
    Falls back gracefully to None if unconfigured.
    """
    from leadsweep.config import get_settings
    settings = get_settings()
    api_key = settings.groq_api_key or os.getenv("GROQ_API_KEY") or os.getenv("LEADSWEEP_GROQ_API_KEY")
    
    if not api_key:
        return None

    try:
        from langchain_groq import ChatGroq
        m = model_name or settings.groq_model or "openai/gpt-oss-120b"
        return ChatGroq(
            model=m,
            api_key=api_key,
            temperature=0,
            max_tokens=600,
            timeout=15.0
        )
    except Exception as e:
        log.warning(f"Failed to initialize ChatGroq: {e}")
        return None
