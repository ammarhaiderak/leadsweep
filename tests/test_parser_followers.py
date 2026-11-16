"""Unit tests for XUser and parse_followers_timeline."""
from leadsweep.models import XUser
from leadsweep.parser import parse_followers_timeline, parse_user_profile


def _user_res(rest_id="101", handle="tech_lead", name="Tech Lead", desc="Building AI agents", followers=5000):
    return {
        "__typename": "User",
        "rest_id": rest_id,
        "legacy": {
            "screen_name": handle,
            "name": name,
            "description": desc,
            "location": "San Francisco, CA",
            "url": "https://example.com",
            "followers_count": followers,
            "friends_count": 350,
            "statuses_count": 1200,
            "listed_count": 45,
            "created_at": "Mon Oct 01 12:00:00 +0000 2021",
            "verified": True,
            "protected": False,
            "profile_image_url_https": "https://pbs.twimg.com/profile_images/avatar.jpg",
        },
        "is_blue_verified": True,
        "professional": {
            "category": [{"name": "Software Development"}],
        },
    }


def _user_entry(rest_id, handle):
    return {
        "entryId": f"user-{rest_id}",
        "content": {
            "itemContent": {
                "user_results": {
                    "result": _user_res(rest_id, handle)
                }
            }
        },
    }


def _followers_payload(entries, cursor="CUR_NEXT_PAGE"):
    return {
        "data": {
            "user": {
                "result": {
                    "timeline": {
                        "timeline": {
                            "instructions": [
                                {
                                    "type": "TimelineAddEntries",
                                    "entries": entries + [
                                        {"entryId": "cursor-bottom-0", "content": {"value": cursor}}
                                    ],
                                }
                            ]
                        }
                    }
                }
            }
        }
    }


def test_parse_user_profile_fields():
    res = _user_res()
    u = parse_user_profile(res)
    assert isinstance(u, XUser)
    assert u.rest_id == "101"
    assert u.handle == "tech_lead"
    assert u.name == "Tech Lead"
    assert u.bio == "Building AI agents"
    assert u.location == "San Francisco, CA"
    assert u.followers_count == 5000
    assert u.following_count == 350
    assert u.tweets_count == 1200
    assert u.is_blue_verified is True
    assert u.professional_category == "Software Development"
    assert u.content_hash is not None


def test_parse_followers_timeline():
    entries = [
        _user_entry("1", "alice"),
        _user_entry("2", "bob"),
        _user_entry("3", "charlie"),
    ]
    payload = _followers_payload(entries, cursor="CURSOR_PAGE_2")
    users, cursor = parse_followers_timeline(payload)
    assert len(users) == 3
    assert [u.handle for u in users] == ["alice", "bob", "charlie"]
    assert cursor == "CURSOR_PAGE_2"


def test_parse_followers_timeline_empty_and_garbage():
    users, cursor = parse_followers_timeline({})
    assert users == []
    assert cursor is None

    users, cursor = parse_followers_timeline({"data": {"user": {"result": {}}}})
    assert users == []
    assert cursor is None


def test_parse_followers_tolerates_nested_user_container():
    """Test user node directly in itemContent or UserWithVisibilityResults."""
    payload = {
        "data": {
            "timeline": {
                "instructions": [
                    {
                        "entries": [
                            {
                                "entryId": "user-99",
                                "content": {
                                    "itemContent": {
                                        "user": _user_res("99", "dana")
                                    }
                                },
                            },
                            {
                                "entryId": "cursor-bottom-1",
                                "content": {"value": "CUR_BOT"},
                            },
                        ]
                    }
                ]
            }
        }
    }
    users, cursor = parse_followers_timeline(payload)
    assert len(users) == 1
    assert users[0].handle == "dana"
    assert cursor == "CUR_BOT"
