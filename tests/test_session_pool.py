import json

import pytest

from leadsweep.exceptions import NoSessionAvailableError
from leadsweep.session_pool import SessionPool


def _pool(tmp_path, n=2):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"sessions": [{"id": f"a{i}", "auth_token": "t", "ct0": "c"} for i in range(n)]}))
    return SessionPool(f, tmp_path / "state.json")


def test_round_robin(tmp_path):
    p = _pool(tmp_path)
    first = p.acquire().id
    p.mark_used(first)
    assert p.acquire().id != first


def test_cooldown_and_dead(tmp_path):
    p = _pool(tmp_path)
    p.mark_cooldown("a0", 600)
    assert p.acquire().id == "a1"
    p.mark_dead("a1", "expired")
    with pytest.raises(NoSessionAvailableError):
        p.acquire()
