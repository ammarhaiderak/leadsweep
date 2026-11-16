"""Actors package initialization and catalog discovery."""
# NEW FEATURE (Phase B & C): Complete Actor Catalog
from __future__ import annotations

from leadsweep.actors.base import Actor, ActorEstimate, ActorRegistry, RunContext
from leadsweep.actors.followers import FollowersActor, FollowersActorInput
from leadsweep.actors.likers import LikersActor, LikersActorInput
from leadsweep.actors.profile import ProfileActor, ProfileActorInput
from leadsweep.actors.replies import RepliesActor, RepliesActorInput
from leadsweep.actors.search import SearchActor, SearchActorInput
from leadsweep.actors.user_tweets import UserTweetsActor, UserTweetsActorInput

# Register complete catalog of 6 core actors
ActorRegistry.register(SearchActor)
ActorRegistry.register(ProfileActor)
ActorRegistry.register(UserTweetsActor)
ActorRegistry.register(FollowersActor)
ActorRegistry.register(RepliesActor)
ActorRegistry.register(LikersActor)

__all__ = [
    "Actor",
    "ActorEstimate",
    "ActorRegistry",
    "RunContext",
    "SearchActor",
    "SearchActorInput",
    "ProfileActor",
    "ProfileActorInput",
    "UserTweetsActor",
    "UserTweetsActorInput",
    "FollowersActor",
    "FollowersActorInput",
    "RepliesActor",
    "RepliesActorInput",
    "LikersActor",
    "LikersActorInput",
]
