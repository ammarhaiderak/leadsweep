"""Export sinks: CSV, JSON, webhook (n8n/Slack/Discord-compatible generic JSON). All stdlib, $0."""
from __future__ import annotations

import csv
import json
import urllib.request
from pathlib import Path
from typing import Any

from .models import ScoredTweet

COLUMNS = ["score", "category", "queries", "author", "followers", "likes", "reposts", "views", "created_at",
           "url", "text", "reason", "suggested_action", "scored_by"]


def lead_row(s: ScoredTweet) -> dict[str, Any]:
    t = s.tweet
    return {
        "score": s.score.score, "category": s.score.category, "queries": ",".join(s.queries),
        "author": t.author_username, "followers": t.author_followers, "likes": t.like_count,
        "reposts": t.retweet_count, "views": t.view_count,
        "created_at": t.created_at.isoformat() if t.created_at else None, "url": t.url, "text": t.text,
        "reason": s.score.reason, "suggested_action": s.score.suggested_action, "scored_by": s.scored_by,
    }


def export_csv(items: list[ScoredTweet], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: opens cleanly in Excel
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(lead_row(s) for s in items)
    return path


def export_json(items: list[ScoredTweet], run_id: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"run_id": run_id, "count": len(items), "leads": [lead_row(s) for s in items]},
                               indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def post_webhook(url: str, items: list[ScoredTweet], run_id: str, timeout: float = 15.0) -> int:
    body = json.dumps({"run_id": run_id, "count": len(items), "leads": [lead_row(s) for s in items]}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if not 200 <= r.status < 300:
            raise RuntimeError(f"webhook returned HTTP {r.status}")
        return r.status


def format_leads(items: list[ScoredTweet], width: int = 100) -> str:
    """Console-friendly lead list."""
    out = []
    for s in items:
        t = s.tweet
        out.append(f"  {s.score.score:3d} {s.score.category:<5} @{t.author_username} ({t.author_followers if t.author_followers is not None else '?'} followers) via {s.scored_by}\n"
                   f"      {' '.join(t.text.split())[:width]!r}\n      {t.url}\n      why: {s.score.reason[:140]}")
    return "\n".join(out) or "  (none)"
