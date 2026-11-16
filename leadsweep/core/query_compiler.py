"""
leadsweep/core/query_compiler.py -- Intent Query Compiler

Compiles buyer-voice families, community allowlists, and negative packs into source-native DSL queries.
Stamps query_pack_hash on every compiled pack.
"""
from __future__ import annotations

import hashlib
import json
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from .contract_models import QueryPack


DEFAULT_NEGATIVE_PACK = [
    "hiring", "job opening", "apply now", "we are hiring", "careers",
    "homework", "giveaway", "airdrop", "bounty", "meme",
    "fiverr.com", "upwork.com", "freelancer.com", "t.co"
]


class CompilerInput(BaseModel):
    icp_id: str
    product_offer: str
    competitors: List[str] = Field(default_factory=list)
    target_roles: List[str] = Field(default_factory=list)
    communities: List[str] = Field(default_factory=list)  # Community allowlist
    custom_negatives: List[str] = Field(default_factory=list)


class QueryCompiler:
    """Compiles ICP + offer into Buyer-Voice families and Source-Specific Query DSLs."""

    @classmethod
    def compile_pack(cls, input_data: CompilerInput, version: str = "1.0.0") -> QueryPack:
        # Require community allowlist
        if not input_data.communities:
            raise ValueError("Community allowlist is required by contract. Queries without community scope cannot run.")

        # 1. Buyer-voice families (not brand keywords)
        families: List[str] = []
        for comp in input_data.competitors:
            families.append(f"alternative to {comp}")
            families.append(f"{comp} too expensive")
            families.append(f"{comp} slow")
            families.append(f"{comp} buggy")
            families.append(f"migrating off {comp}")

        families.append(f"looking for a tool that {input_data.product_offer}")
        families.append(f"recommend a {input_data.product_offer}")
        for role in input_data.target_roles:
            families.append(f"how do {role} handle {input_data.product_offer}")

        # 2. Negatives pack
        negatives = list(set(DEFAULT_NEGATIVE_PACK + input_data.custom_negatives))

        # 3. Source-specific compilation
        compiled: Dict[str, str] = {}

        # HN Algolia format: phrases with tags and NOT terms
        hn_queries = []
        for f in families[:4]:
            neg_clause = " ".join([f"-{n}" for n in negatives[:4]])
            hn_queries.append(f'"{f}" {neg_clause}')
        compiled["hn"] = " OR ".join(hn_queries)

        # Bluesky / Lobsters / Dev.to search query
        compiled["bluesky"] = f'"{families[0]}"' if families else input_data.product_offer
        compiled["lobsters"] = input_data.communities[0] if input_data.communities else "ask"
        compiled["devto"] = f"tag:{input_data.communities[0]}" if input_data.communities else "discuss"
        compiled["github"] = f"{input_data.product_offer} in:title,description"
        compiled["stackexchange"] = f"[{input_data.communities[0]}]" if input_data.communities else "questions"
        compiled["reddit"] = f"disabled_unlicensed"

        # Deterministic Hash
        raw_repr = json.dumps({
            "version": version,
            "icp_id": input_data.icp_id,
            "families": sorted(families),
            "communities": sorted(input_data.communities),
            "negatives": sorted(negatives),
            "compiled": compiled,
        }, sort_keys=True)
        pack_hash = hashlib.sha256(raw_repr.encode("utf-8")).hexdigest()[:16]

        return QueryPack(
            version=version,
            hash=pack_hash,
            icp_id=input_data.icp_id,
            families=families,
            communities=input_data.communities,
            negatives=negatives,
            compiled_per_source=compiled,
        )
