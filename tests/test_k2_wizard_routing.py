import pytest
from leadsweep.target_grammar import parse_x_target

def test_k2_wizard_type_routing_rules():
    # 1. Profile URL with wizard_type='profile'
    t1 = parse_x_target("https://x.com/nextjs", wizard_type="profile")
    assert t1.kind == "profile"
    assert t1.handle == "nextjs"

    # 2. @handle with wizard_type='profile'
    t2 = parse_x_target("@nextjs", wizard_type="profile")
    assert t2.kind == "profile"
    assert t2.handle == "nextjs"

    # 3. Plain word with wizard_type='profile'
    t3 = parse_x_target("nextjs", wizard_type="profile")
    assert t3.kind == "profile"
    assert t3.handle == "nextjs"

    # 4. Profile URL with wizard_type='timeline'
    t4 = parse_x_target("https://x.com/nextjs", wizard_type="timeline")
    assert t4.kind == "profile"
    assert t4.handle == "nextjs"

    # 5. type=search with profile URL routes to kind='profile'
    t5 = parse_x_target("https://x.com/nextjs", wizard_type="search")
    assert t5.kind == "profile"
    assert t5.handle == "nextjs"

    # 6. type=search with @handle routes to kind='profile'
    t6 = parse_x_target("@nextjs", wizard_type="search")
    assert t6.kind == "profile"
    assert t6.handle == "nextjs"

    # 7. Plain-word search stays SEARCH
    t7 = parse_x_target("nextjs", wizard_type="search")
    assert t7.kind == "search"
    assert t7.query == "nextjs"

    t8 = parse_x_target("solana hiring", wizard_type="search")
    assert t8.kind == "search"
    assert t8.query == "solana hiring"

def test_k2_actor_dispatch_routing():
    # Simulate API actor resolution logic
    def resolve_actor(clean_query: str, req_type: str):
        target = parse_x_target(clean_query, wizard_type=req_type)
        routed_detail = None
        if target.kind == "profile":
            if req_type == "profile":
                actor_name = "profile"
            else:
                actor_name = "user_tweets"
                if req_type == "search":
                    routed_detail = f"Routed @{target.handle} profile to timeline scraper"
        elif target.kind == "search":
            actor_name = "search"
        elif target.kind == "status":
            actor_name = "replies"
        else:
            actor_name = "search"
        return actor_name, routed_detail

    # Profile
    act, detail = resolve_actor("https://x.com/nextjs", "profile")
    assert act == "profile"
    assert detail is None

    # Timeline
    act, detail = resolve_actor("https://x.com/nextjs", "timeline")
    assert act == "user_tweets"
    assert detail is None

    # Search with profile URL
    act, detail = resolve_actor("https://x.com/nextjs", "search")
    assert act == "user_tweets"
    assert detail == "Routed @nextjs profile to timeline scraper"

    # Search with @handle
    act, detail = resolve_actor("@nextjs", "search")
    assert act == "user_tweets"
    assert detail == "Routed @nextjs profile to timeline scraper"

    # Plain word search
    act, detail = resolve_actor("nextjs", "search")
    assert act == "search"
    assert detail is None

    act, detail = resolve_actor("ai engineer hiring", "search")
    assert act == "search"
    assert detail is None
