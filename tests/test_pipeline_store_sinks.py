import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from leadsweep.pipeline.fakes import mk
from leadsweep.pipeline.models import LeadScore, ScoredTweet
from leadsweep.pipeline.sinks import export_csv, export_json, format_leads, post_webhook
from leadsweep.pipeline.store import Store


def scored(id, score, cat="lead"):
    return ScoredTweet(tweet=mk(id, f"tweet {id} looking for dev", user=f"u{id}"), queries=["q1"], query_type="lead",
                       score=LeadScore(score=score, category=cat, reason="because"), heuristic_score=score, scored_by="heuristic")


def test_store_roundtrip(tmp_path):
    st = Store(tmp_path / "a.db")
    st.save_scored("r1", [scored("1", 90), scored("2", 40), scored("3", 95, "noise")])
    assert st.known_ids(["1", "2", "9"]) == {"1", "2"}
    rows = st.top_leads(min_score=50)
    assert [r["score"] for r in rows] == [90]  # 40 below threshold, noise excluded
    st.start_run("r1", "heuristic", 2)
    st.finish_run("r1", "ok", {"a": 1}, [])
    assert st.get_run("r1")["status"] == "ok"
    st.save_scored("r2", [scored("1", 10)])  # re-save replaces score, tweet row stays
    assert st.db.execute("SELECT COUNT(*) c FROM tweets").fetchone()["c"] == 3


def test_csv_json_and_format(tmp_path):
    items = [scored("1", 90)]
    c = export_csv(items, tmp_path / "x.csv").read_text(encoding="utf-8-sig")
    assert "score,category" in c and "tweet 1" in c
    j = json.loads(export_json(items, "r1", tmp_path / "x.json").read_text())
    assert j["count"] == 1 and j["leads"][0]["author"] == "u1"
    assert "@u1" in format_leads(items)


def test_webhook_delivers_payload():
    got = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            got["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    assert post_webhook(f"http://127.0.0.1:{srv.server_port}/hook", [scored("1", 90)], "r1") == 200
    assert got["body"]["run_id"] == "r1" and got["body"]["count"] == 1
    srv.server_close()


# ---------------------------------------------------------------- P3.1: Ollama preflight must catch a broken install
class _FakeOllama(BaseHTTPRequestHandler):
    mode = "ok"

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, {"models": [{"name": "qwen2.5:3b"}]})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.mode == "broken":
            self._send(500, {"error": "error starting llama-server: llama-server binary not found (checked: /usr/local/lib/ollama/llama-server)"})
        else:
            self._send(200, {"response": "OK", "done": True})

    def log_message(self, *a):
        pass


def _ollama(mode):
    handler = type("H", (_FakeOllama,), {"mode": mode})
    srv = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_ollama_ready_detects_broken_runner_like_the_users_machine():
    from leadsweep.pipeline.scoring import ollama_ready
    srv = _ollama("broken")
    ok, msg = ollama_ready(f"http://127.0.0.1:{srv.server_port}", "qwen2.5:3b", probe_timeout=5)
    srv.shutdown()
    assert not ok and "install.sh" in msg and "ollama run qwen2.5:3b" in msg


def test_ollama_ready_ok_when_model_answers_and_wrong_model_reported():
    from leadsweep.pipeline.scoring import ollama_ready
    srv = _ollama("ok")
    base = f"http://127.0.0.1:{srv.server_port}"
    assert ollama_ready(base, "qwen2.5:3b", probe_timeout=5)[0] is True
    ok, msg = ollama_ready(base, "other-model", probe_timeout=5)
    srv.shutdown()
    assert not ok and "ollama pull other-model" in msg
