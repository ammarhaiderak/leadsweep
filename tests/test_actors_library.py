"""Unit and integration tests for Full Actor Library (Phase C)."""
import pytest
from leadsweep.actors import ActorRegistry, RunContext
from leadsweep.actors.search import SearchActorInput
from leadsweep.actors.profile import ProfileActorInput
from leadsweep.actors.user_tweets import UserTweetsActorInput
from leadsweep.actors.followers import FollowersActorInput
from leadsweep.actors.replies import RepliesActorInput
from leadsweep.actors.likers import LikersActorInput


def test_actor_registry_discovery():
    actors = ActorRegistry.list_all()
    names = {a["name"] for a in actors}
    assert {"search", "profile", "user_tweets", "followers", "replies", "likers"}.issubset(names)


def test_actor_preflight_estimates():
    # 1. Search
    search = ActorRegistry.get("search")
    est_s = search.estimate(SearchActorInput(query="LangChain", max_results=30))
    assert est_s.estimated_items == 30
    assert est_s.cost_dollars == 0.0
    assert est_s.risk_level == "low"

    # 2. Profile
    profile = ActorRegistry.get("profile")
    est_p = profile.estimate(ProfileActorInput(handle="karpathy"))
    assert est_p.estimated_items == 1
    assert est_p.cost_dollars == 0.0

    # 3. UserTweets
    ut = ActorRegistry.get("user_tweets")
    est_ut = ut.estimate(UserTweetsActorInput(handle="sama", max_results=15))
    assert est_ut.estimated_items == 15
    assert est_ut.risk_level == "low"

    # 4. Followers
    fol = ActorRegistry.get("followers")
    est_fol = fol.estimate(FollowersActorInput(handle="elonmusk", max_results=50))
    assert est_fol.estimated_items == 50
    assert est_fol.risk_level == "medium"

    # 5. Replies
    rep = ActorRegistry.get("replies")
    est_rep = rep.estimate(RepliesActorInput(tweet_id="1234567890", max_results=20))
    assert est_rep.estimated_items == 20

    # 6. Likers
    likers = ActorRegistry.get("likers")
    est_lik = likers.estimate(LikersActorInput(tweet_id="1234567890", max_results=20))
    assert est_lik.estimated_items == 20
    assert est_lik.risk_level == "medium"


def test_run_context_checkpointing():
    ctx = RunContext(run_id="run_test_1", dataset_id="ds_test_1")
    assert not ctx.is_cancelled()
    ctx.save_checkpoint({"page": 1, "cursor": "cur_123"})
    assert ctx.checkpoint["cursor"] == "cur_123"
    ctx.cancelled.set()
    assert ctx.is_cancelled()
