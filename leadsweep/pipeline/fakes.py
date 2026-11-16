"""Offline test doubles + sample data, so the whole graph can be verified with no browser and no LLM."""
from __future__ import annotations

from ..models import Tweet
from ..schemas import ErrorInfo, SearchResponse


def mk(id: str, text: str, user: str = "someone", followers: int = 500, likes: int = 0, rts: int = 0,
       views: int | None = None, retweet: bool = False) -> Tweet:
    return Tweet(id=id, url=f"https://x.com/{user}/status/{id}", text=text, author_username=user, author_followers=followers,
                 like_count=likes, retweet_count=rts, view_count=views, is_retweet=retweet)


def sample_responses() -> list[SearchResponse]:
    lead = mk("101", "We're looking for an AI developer to build a LangChain chatbot for our support team. Budget $3k, DM me.", "buyer1")
    rfp = mk("102", "RFP: we need an automation agency to build n8n workflows and integrations for our logistics business. Proposals due Friday.", "ops_lead")
    seeker = mk("103", "Open to work! AI engineer with LangChain, RAG and n8n experience. DM for work #opentowork", "dev_jane")
    spam = mk("104", "AI agents + TRON = the next 100x. Airdrop soon, join the whitelist now!!", "shill")
    retweet = mk("106", "RT @x: we are hiring an AI engineer for a long contract project", "rter", retweet=True)
    short = mk("107", "gm AI", "gm_bot")
    weak = mk("109", "Anyone know a good freelancer for a web scraper project?", "smallbiz")
    trend = mk("105", "MCP servers are becoming the standard way to connect AI agents to tools. What this means for automation agencies.",
               "analyst", followers=20000, likes=250, rts=40, views=50000)
    return [
        SearchResponse(ok=True, query="q1", count=4, tweets=[lead, seeker, spam, short]),
        SearchResponse(ok=True, query="q2", count=3, tweets=[lead, rfp, weak]),  # `lead` repeats -> dedupe
        SearchResponse(ok=True, query="q3", count=2, tweets=[trend, retweet]),
    ]


class FakeScrapeClient:
    """Returns the given responses in call order (empty ok-response once exhausted)."""

    def __init__(self, responses: list[SearchResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, max_results: int) -> SearchResponse:
        self.calls.append((query, max_results))
        if self.responses:
            return self.responses.pop(0)
        return SearchResponse(ok=True, query=query, count=0)


def error_response(code: str, message: str = "boom") -> SearchResponse:
    return SearchResponse(ok=False, query="q", count=0,
                          error=ErrorInfo(code=code, message=message, retryable=False))  # type: ignore[arg-type]
