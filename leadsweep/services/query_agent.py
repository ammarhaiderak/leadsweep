"""Query Intelligence Agent (Pre-Scraping Optimization Layer).

Transforms user raw/conversational queries into high-precision, platform-native
search strings using rule-based decomposition and Groq LLM intelligence.
Ensures zero noise, high procurement intent, and genuine real-time matching.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from pydantic import BaseModel, Field

from leadsweep.config import get_settings

log = logging.getLogger("leadsweep.services.query_agent")


class OptimizedQueryPlan(BaseModel):
    raw_query: str
    platform: str = "twitter"
    target_role: str | None = None
    industry_domain: str | None = None
    search_queries: list[str] = Field(default_factory=list)
    relevance_keywords: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)
    explanation: str = ""


class QueryOptimizationAgent:
    """Pre-Scraping Agent Layer that prepares exact platform-native query expansions."""

    @classmethod
    async def optimize(cls, raw_query: str, platform: str = "twitter") -> OptimizedQueryPlan:
        q_clean = raw_query.strip().strip('"').strip("'")
        platform_lower = platform.lower()

        # Step 1: Rule-based fast path decomposition
        plan = cls._heuristic_decompose(q_clean, platform_lower)

        # Step 2: Try LLM expansion if Groq is available for deep query intent
        settings = get_settings()
        if settings.groq_api_key:
            try:
                llm_plan = await cls._llm_decompose(q_clean, platform_lower, settings)
                if llm_plan and llm_plan.search_queries:
                    # Merge queries prioritizing LLM precision while keeping robust fallbacks
                    merged_queries = []
                    for q in llm_plan.search_queries + plan.search_queries:
                        q_str = q.strip()
                        if q_str and q_str not in merged_queries:
                            merged_queries.append(q_str)
                    plan.search_queries = merged_queries[:4]
                    if llm_plan.relevance_keywords:
                        plan.relevance_keywords = list(set(plan.relevance_keywords + llm_plan.relevance_keywords))
                    if llm_plan.explanation:
                        plan.explanation = llm_plan.explanation
            except Exception as exc:
                log.warning("Query Optimization Agent LLM pass failed, using heuristic: %s", exc)

        log.info(
            "QueryOptimizationAgent created plan for '%s': %d search queries -> %s",
            raw_query, len(plan.search_queries), plan.search_queries
        )
        return plan

    @classmethod
    def _heuristic_decompose(cls, query: str, platform: str) -> OptimizedQueryPlan:
        q_lower = query.lower()
        words = re.findall(r"\b[\w'-]+\b", q_lower)
        stop_words = {
            "i", "want", "to", "a", "an", "the", "that", "who", "which", "can",
            "please", "am", "looking", "for", "need", "find", "get", "me", "show"
        }
        meaningful = [w for w in words if w not in stop_words]

        queries: list[str] = []
        rel_kw: list[str] = list(meaningful)

        # 1. Exact quoted phrase (searches actual tweet text body)
        queries.append(f'"{query}"')

        # 2. Check for founder / web3 founder queries
        if "founder" in q_lower or "co-founder" in q_lower or "ceo" in q_lower or "cto" in q_lower:
            target = "web3" if ("web3" in q_lower or "crypto" in q_lower) else ("ai" if "ai" in q_lower else "")
            if target:
                queries.append(f'("{target} founder" OR "{target} co-founder") -filter:links -filter:replies')
                queries.append(f'"{target} founder" (building OR hiring OR launch)')
                queries.append(f'"{query}" -filter:replies')
                rel_kw.extend([f"{target} founder", "founder", "building", "launching", "startup"])
            else:
                queries.append(f'"{query}" -filter:links -filter:replies')
                queries.append(f'"{query}" (building OR hiring OR "looking for")')

        # UPDATED LOGIC: Intent-phrased query planner with negative exclusions and first-person cues
        # 3. Hiring & procurement patterns
        is_hiring = any(h in q_lower for h in ["hire", "hiring", "looking for", "need a", "job", "developer", "engineer", "builder"])
        if is_hiring:
            role_words = [w for w in meaningful if w not in {"hire", "hiring", "looking", "need", "someone", "to"}]
            role_phrase = " ".join(role_words) if role_words else "developer"

            # Exclusion terms for commentary/advice/thought-pieces
            exclusions = '-"without hiring" -"tips for" -"guide to" -"how to" -"before hiring" -"imagine hiring"'
            
            # 4-8 Intent phrasings:
            queries.append(f'"looking for a {role_phrase}" {exclusions}')
            queries.append(f'"need a {role_phrase}" {exclusions}')
            queries.append(f'"hiring a {role_phrase}" {exclusions}')
            queries.append(f'("need someone to build" OR "who can build") "{role_phrase}" {exclusions}')
            queries.append(f'("hire a {role_phrase}" OR "hiring a {role_phrase}") ("DM me" OR "my budget" OR "paid project") {exclusions}')
            queries.append(f'"can anyone recommend a {role_phrase}" {exclusions}')
            
            rel_kw.extend(["hiring", "looking for", "need a", role_phrase, "budget", "paid project", "dm me"])
        else:
            # Generic conversational cleanup
            if len(meaningful) >= 2:
                phrase = " ".join(meaningful)
                queries.append(f'"{phrase}"')
                queries.append(f'("looking for" OR "need") "{phrase}"')

        # De-duplicate queries
        seen = set()
        clean_queries = []
        for q in queries:
            if q not in seen:
                seen.add(q)
                clean_queries.append(q)

        return OptimizedQueryPlan(
            raw_query=query,
            platform=platform,
            search_queries=clean_queries,
            relevance_keywords=list(set(rel_kw)),
            negative_keywords=["without hiring", "tips for", "guide to", "how to", "imagine hiring", "crypto airdrop"],
            explanation="Intent-phrased query planning with negative commentary exclusions"
        )

    @classmethod
    async def _llm_decompose(cls, query: str, platform: str, settings: Any) -> OptimizedQueryPlan | None:
        from langchain_groq import ChatGroq
        import json

        chat = ChatGroq(
            model=settings.groq_model,
            api_key=settings.groq_api_key,
            temperature=0.1,
            max_tokens=300,
        )

        prompt = (
            f"You are an AI Search Intelligence Agent for social media platforms ({platform}).\n"
            f"The user entered the search prompt: '{query}'\n\n"
            f"Generate 3 optimized search queries tailored for {platform} search syntax that will return "
            f"HIGH QUALITY, REAL, LATEST procurement leads/posts (e.g. users explicitly hiring, buying, or requesting services matching the user query).\n"
            f"CRITICAL RULES for {platform} syntax:\n"
            f"1. DO NOT use advanced operators like min_faves, min_retweets, or -filter:replies as they cause 0 search results on modern X/Twitter web.\n"
            f"2. Keep queries clean and natural, e.g. \"{query}\" (hiring OR \"looking for\") or {query} founder or hiring {query}.\n"
            f"3. Avoid deep nested parentheses or complex boolean chaining.\n\n"
            f"Respond STRICTLY in JSON with keys:\n"
            f'{{"queries": ["query 1", "query 2", "query 3"], "relevance_keywords": ["word1", "word2"], "explanation": "brief note"}}'
        )

        resp = await chat.ainvoke(prompt)
        text = str(resp.content).strip()
        
        # Extract json object
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        
        data = json.loads(m.group(0))
        queries = [str(q).strip() for q in data.get("queries", []) if str(q).strip()]
        kw = [str(k).strip().lower() for k in data.get("relevance_keywords", []) if str(k).strip()]
        
        return OptimizedQueryPlan(
            raw_query=query,
            platform=platform,
            search_queries=queries,
            relevance_keywords=kw,
            explanation=data.get("explanation", "LLM Intent optimized")
        )
