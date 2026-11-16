"""Base Actor class, RunContext, and Actor Registry (Apify-class $0 Stack).

Every Actor exposes:
- name: Unique identifier (e.g. 'search', 'profile', 'timeline')
- version: Semantic versioning
- input_schema: Pydantic model for parameter validation
- estimate(input): Pre-flight computation of items, runtime, and risk
- run(input, ctx): Asynchronous generator yielding items with checkpointing
- risk_level: 'low', 'medium', 'high' (triggers HITL guard if high)
"""
# NEW FEATURE (Phase B): Actor interface & lifecycle
from __future__ import annotations

import abc
import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Generic, Type, TypeVar

from pydantic import BaseModel

log = logging.getLogger("leadsweep.actors.base")

TInput = TypeVar("TInput", bound=BaseModel)
TOutput = TypeVar("TOutput", bound=BaseModel)


@dataclass
class ActorEstimate:
    estimated_items: int
    estimated_seconds: float
    risk_level: str  # 'low', 'medium', 'high'
    cost_dollars: float = 0.0  # Strict $0 baseline


@dataclass
class RunContext:
    """Per-run execution context handed to every Actor.

    PHASE 5 (scraper lifecycle): ``scraper`` is an optional, caller-supplied
    :class:`~leadsweep.scraper.XScraper`. When present, Actors MUST reuse it instead of opening
    their own browser. That lets one caller own the browser for the whole run - the same
    discipline the MCP server already applies - so N actors in one run produce one Chromium
    rather than N. When absent, Actors fall back to their historical behaviour of opening a
    scoped ``async with XScraper()``, which keeps every existing call site working.
    """

    run_id: str
    dataset_id: str
    checkpoint: dict[str, Any] = field(default_factory=dict)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    logger: logging.Logger = field(default_factory=lambda: log)
    scraper: Any | None = None

    def save_checkpoint(self, data: dict[str, Any]) -> None:
        """Update in-memory and persisted checkpoint for zero-loss resumption."""
        self.checkpoint.update(data)

    def is_cancelled(self) -> bool:
        return self.cancelled.is_set()

    @asynccontextmanager
    async def use_scraper(self) -> AsyncIterator[Any]:
        """Yield the shared scraper, or a self-managed one when none was injected.

        Actors call this instead of ``async with XScraper()`` directly::

            async with ctx.use_scraper() as scraper:
                tweets = await scraper.search_tweets(...)

        The returned object works identically in both cases, so an Actor never needs to
        know whether it is running standalone or as part of a shared-lifecycle run.
        """
        if self.scraper is not None:
            yield self.scraper
            return
        from leadsweep.scraper import XScraper

        async with XScraper() as scraper:
            yield scraper


class Actor(Generic[TInput, TOutput], abc.ABC):
    name: str = ""
    version: str = "1.0.0"
    input_schema: Type[TInput] = BaseModel  # type: ignore[assignment]
    risk_level: str = "low"

    @abc.abstractmethod
    def estimate(self, input_data: TInput) -> ActorEstimate:
        """Estimate execution volume, duration, and safety risk prior to running."""
        pass

    @abc.abstractmethod
    async def run(self, input_data: TInput, ctx: RunContext) -> AsyncIterator[TOutput]:
        """Execute extraction, yielding standardized output items with periodic checkpointing."""
        if False:
            yield  # type: ignore[misc]


class ActorRegistry:
    """Central discovery catalog for all pluggable scraper actors."""

    _actors: dict[str, Actor[Any, Any]] = {}

    @classmethod
    def register(cls, actor_cls: Type[Actor[Any, Any]]) -> None:
        actor = actor_cls()
        if not actor.name:
            raise ValueError(f"Actor class {actor_cls.__name__} must define a unique 'name'")
        cls._actors[actor.name] = actor
        log.info("Registered Actor: %s (v%s, risk=%s)", actor.name, actor.version, actor.risk_level)

    @classmethod
    def get(cls, name: str) -> Actor[Any, Any]:
        if name not in cls._actors:
            raise KeyError(f"Actor '{name}' is not registered. Available: {list(cls._actors.keys())}")
        return cls._actors[name]

    @classmethod
    def list_all(cls) -> list[dict[str, Any]]:
        return [
            {
                "name": a.name,
                "version": a.version,
                "risk_level": a.risk_level,
                "input_schema": a.input_schema.model_json_schema() if hasattr(a.input_schema, "model_json_schema") else {},
            }
            for a in cls._actors.values()
        ]
