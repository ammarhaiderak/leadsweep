"""Unit tests for Stage 3: ICP qualification bio rules, scoring service, and overlap analytics."""
from leadsweep.models import XUser
from leadsweep.pipeline.store import Store
from leadsweep.services.followers import FollowersService
from leadsweep.services.icp_scoring import ICPScoringService, calculate_rules_score


def test_calculate_rules_score_decision_maker():
    founder = XUser(
        rest_id="u1",
        handle="sarah_cto",
        name="Sarah Chen",
        bio="Co-founder & CTO at AI Startup. Building workflow automation agents. Hiring engineers! YC W24.",
        followers_count=3500,
        is_blue_verified=True,
    )
    score, persona, signals = calculate_rules_score(founder)
    assert score >= 70
    assert persona == "Founder / Executive"
    assert any("founder" in s for s in signals)
    assert any("automation" in s or "agent" in s for s in signals)


def test_calculate_rules_score_negative_signals():
    student = XUser(
        rest_id="u2",
        handle="john_student",
        name="John Doe",
        bio="Student and crypto trader. Looking for airdrop and memecoin 100x.",
        followers_count=45,
    )
    score, persona, signals = calculate_rules_score(student)
    assert score <= 30
    assert any("neg:" in s for s in signals)


def test_icp_scoring_service_persist(tmp_path):
    store = Store(tmp_path / "test.db")
    svc = ICPScoringService(store)
    user = XUser(
        rest_id="u3",
        handle="alex_vp",
        name="Alex V",
        bio="VP of Engineering. Scaling SaaS infrastructure and AI pipelines.",
        followers_count=1200,
    )
    res = svc.score_heuristically(user)
    assert res["icp_score"] >= 50
    assert res["scored_by"] == "rules"

    # Query directly from DB
    row = store.db.execute("SELECT * FROM user_scores WHERE user_id = 'u3'").fetchone()
    assert row is not None
    assert row["icp_score"] == res["icp_score"]
    store.close()


def test_followers_overlap_analytics(tmp_path):
    store = Store(tmp_path / "test.db")
    f_svc = FollowersService(store)
    icp_svc = ICPScoringService(store)

    # Create targets
    t1 = f_svc.get_or_create_target("stripe")
    t2 = f_svc.get_or_create_target("openai")

    # Insert user
    user = XUser(
        rest_id="u10",
        handle="multi_follower",
        name="Tech Lead",
        bio="Lead Architect building AI agents",
        followers_count=2000,
    )
    # Store user
    store.db.execute(
        "INSERT INTO x_users (rest_id, handle, name, bio, followers_count, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        (user.rest_id, user.handle, user.name, user.bio, user.followers_count)
    )
    # Add edges to both targets
    store.db.execute("INSERT INTO follow_edges VALUES (?, ?, 'r1', 'r1', 1)", (t1["id"], user.rest_id))
    store.db.execute("INSERT INTO follow_edges VALUES (?, ?, 'r1', 'r1', 1)", (t2["id"], user.rest_id))
    store.db.commit()

    # Score user
    icp_svc.score_heuristically(user)

    # Query with overlap_only=True
    overlap_rows = f_svc.list_followers(overlap_only=True)
    assert len(overlap_rows) == 1
    assert overlap_rows[0]["handle"] == "multi_follower"
    assert overlap_rows[0]["overlap_targets"] == 2
    assert "stripe" in overlap_rows[0]["followed_targets"]
    assert "openai" in overlap_rows[0]["followed_targets"]
    store.close()
