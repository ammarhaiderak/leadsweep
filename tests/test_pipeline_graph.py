import asyncio
from pathlib import Path

import pytest

from leadsweep.config import Settings
from leadsweep.pipeline.fakes import FakeScrapeClient, error_response, sample_responses
from leadsweep.pipeline.graph import Deps, describe, run_graph
from leadsweep.pipeline.models import LeadScore, PipelineConfig, QuerySpec
from leadsweep.pipeline.store import Store

CFG = PipelineConfig(queries=[QuerySpec(name="a", q="x", type="lead"), QuerySpec(name="b", q="x", type="rfp"),
                              QuerySpec(name="c", q="x", type="trend")])


class FakeScorer:
    label = "fake:llm"

    def __init__(self, fn):
        self.fn, self.calls = fn, []

    async def score(self, c, profile):
        self.calls.append(c.tweet.id)
        return self.fn(c)


def deps(tmp_path, responses, scorer=None, **settings):
    st = Settings(min_score=70, llm_top_n=settings.pop("llm_top_n", 40), **settings)
    store = Store(tmp_path / "t.db")
    return Deps(FakeScrapeClient(responses), store, CFG, st, scorer=scorer,
                scorer_label=scorer.label if scorer else "heuristic", out_dir=tmp_path / "out", webhook_url=settings.get("webhook_url")), store


def run(d):
    return asyncio.run(run_graph(d))


def test_full_offline_run(tmp_path):
    d, store = deps(tmp_path, sample_responses())
    r = run(d)
    assert r["status"] == "ok"
    assert {s.tweet.id for s in r["selected"]} == {"101", "102", "105"}
    assert r["stats"]["candidates"] == 5 and r["stats"]["dropped"]["duplicate"] == 1
    assert store.get_run(r["run_id"])["status"] == "ok"
    assert store.known_ids(["101", "103", "109"]) == {"101", "103", "109"}  # noise + weak stored too
    assert len(list((tmp_path / "out").glob("leads_*"))) == 2
    r2 = run(Deps(FakeScrapeClient(sample_responses()), store, CFG, d.settings, out_dir=tmp_path / "out"))
    assert r2["candidates"] == [] and r2["status"] == "ok" and "selected" not in r2


@pytest.mark.parametrize("code", ["RATE_LIMITED", "SESSION_EXPIRED", "ENDPOINT_CHANGED"])
def test_abort_codes_stop_fetching_but_finish_cleanly(tmp_path, code):
    d, store = deps(tmp_path, [error_response(code)] + sample_responses())
    r = run(d)
    assert r["status"] == "aborted" and len(d.client.calls) == 1
    assert store.get_run(r["run_id"])["status"] == "aborted" and any(code in e for e in r["errors"])


def test_non_fatal_error_continues(tmp_path):
    d, _ = deps(tmp_path, [error_response("INVALID_INPUT")] + sample_responses()[1:])
    r = run(d)
    assert r["status"] == "partial" and len(d.client.calls) == 3 and r["selected"]


def test_llm_scores_top_n_only_and_is_used(tmp_path):
    sc = FakeScorer(lambda c: LeadScore(score=95, category="lead", reason="llm says so"))
    d, _ = deps(tmp_path, sample_responses(), scorer=sc, llm_top_n=2)
    r = run(d)
    assert len(sc.calls) == 2 and r["stats"]["llm_scored"] == 2 and r["stats"]["heuristic_scored"] == 3
    assert {s.scored_by for s in r["scored"]} == {"fake:llm", "heuristic"}


def test_llm_failures_fall_back_and_disable(tmp_path):
    def boom(c):
        raise RuntimeError("ollama down")

    sc = FakeScorer(boom)
    d, _ = deps(tmp_path, sample_responses(), scorer=sc)
    r = run(d)
    assert len(sc.calls) == 3  # disabled after 3 consecutive failures
    assert any("LLM disabled" in e for e in r["errors"]) and r["status"] == "partial"
    assert {s.tweet.id for s in r["selected"]} == {"101", "102", "105"}  # heuristic still delivers
    assert all(s.scored_by.startswith("heuristic") for s in r["scored"])


def test_webhook_failure_is_non_fatal(tmp_path):
    d, store = deps(tmp_path, sample_responses(), webhook_url="http://127.0.0.1:9/hook")
    r = run(d)
    assert r["status"] == "partial" and any("webhook failed" in e for e in r["errors"])
    assert len(list((tmp_path / "out").glob("leads_*"))) == 2 and store.known_ids(["101"]) == {"101"}


def test_describe_covers_all_nodes():
    for n in ["start_run", "fetch_next", "prefilter", "score", "select", "export", "finish"]:
        assert isinstance(describe(n, {}), str)


def test_rule_scored_posts_face_a_stricter_threshold_than_llm_scored(tmp_path):
    # LLM judges only the top-1 candidate and gives it 75 (>= 70 LLM bar -> selected);
    # everything else is rule-scored and must reach 80
    sc = FakeScorer(lambda c: LeadScore(score=75, category="lead", reason="llm"))
    d, _ = deps(tmp_path, sample_responses(), scorer=sc, llm_top_n=1)
    r = run(d)
    by = {s.tweet.id: s for s in r["scored"]}
    llm_ids = {i for i, s in by.items() if s.scored_by == "fake:llm"}
    assert len(llm_ids) == 1 and llm_ids <= {s.tweet.id for s in r["selected"]}
    assert r["stats"]["thr_llm"] == 70 and r["stats"]["thr_heuristic"] == 80
    assert all(s.score.score >= 80 for s in r["selected"] if s.scored_by.startswith("heuristic"))


def test_rescore_flag_reprocesses_seen_tweets_and_updates_scores(tmp_path):
    d, store = deps(tmp_path, sample_responses())
    run(d)
    d2 = Deps(FakeScrapeClient(sample_responses()), store, CFG, d.settings, out_dir=tmp_path / "out", rescore=True)
    r2 = run(d2)
    assert len(r2["candidates"]) == 5 and r2["stats"]["dropped"]["already_seen"] == 0
    assert store.db.execute("SELECT COUNT(*) c FROM scores").fetchone()["c"] == 5  # replaced, not duplicated
