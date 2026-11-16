"""H2-5 Tests: Grammar, GraphQL Fixtures for Profile Timeline, and Search Regression."""
import pytest
from datetime import datetime, timezone
from leadsweep.target_grammar import parse_x_target, XTarget
from leadsweep.parser import parse_user_tweets, parse_search_timeline, parse_tweet_result
from leadsweep.exceptions import UserNotFoundError, SessionExpiredError, RateLimitedError
from leadsweep.scraper import XScraper, _Collector


# ==============================================================================
# 1. Target Grammar Tests
# ==============================================================================

def test_grammar_urls():
    for url in [
        "https://x.com/nextjs",
        "http://twitter.com/nextjs",
        "x.com/nextjs",
        "www.x.com/nextjs",
        "https://twitter.com/nextjs/",
    ]:
        t = parse_x_target(url)
        assert t.kind == "profile"
        assert t.handle == "nextjs"
        assert t.with_replies is False


def test_grammar_with_replies():
    for url in [
        "https://x.com/nextjs/with_replies",
        "x.com/nextjs/with_replies",
        "@nextjs/with_replies",
        "nextjs/with_replies",
    ]:
        t = parse_x_target(url)
        assert t.kind == "profile"
        assert t.handle == "nextjs"
        assert t.with_replies is True


def test_grammar_at_handle():
    t = parse_x_target("@nextjs")
    assert t.kind == "profile"
    assert t.handle == "nextjs"
    assert t.with_replies is False


def test_grammar_reserved_paths():
    for reserved in ["home", "explore", "search", "i", "settings", "intent", "notifications"]:
        t = parse_x_target(f"https://x.com/{reserved}")
        assert t.kind == "invalid"
        assert "reserved" in (t.error or "").lower()

        t2 = parse_x_target(f"@{reserved}")
        assert t2.kind == "invalid"


def test_grammar_status_urls():
    t = parse_x_target("https://x.com/nextjs/status/1845123456789012345")
    assert t.kind == "status"
    assert t.status_id == "1845123456789012345"

    t2 = parse_x_target("https://twitter.com/i/web/status/9876543210")
    assert t2.kind == "status"
    assert t2.status_id == "9876543210"


def test_grammar_plain_words_stay_search():
    # Plain search queries must NOT be hijacked as profiles
    t = parse_x_target("hiring python developer", wizard_type="search")
    assert t.kind == "search"
    assert t.query == "hiring python developer"

    t2 = parse_x_target("nextjs", wizard_type="search")
    assert t2.kind == "search"
    assert t2.query == "nextjs"

    # Only when wizard explicitly selects profile/timeline does a single word become a handle
    t3 = parse_x_target("nextjs", wizard_type="profile")
    assert t3.kind == "profile"
    assert t3.handle == "nextjs"


def test_grammar_handle_validation():
    # Max 15 chars, alphanumeric or underscore
    assert parse_x_target("toolonghandlethatisgreaterthan15", wizard_type="profile").kind == "invalid"
    assert parse_x_target("invalid-char!", wizard_type="profile").kind == "invalid"
    assert parse_x_target("https://x.com/invalid-char!").kind == "invalid"


# ==============================================================================
# 2. GraphQL Fixtures Tests
# ==============================================================================

def _make_tweet_node(tid: str, text: str, user: str = "nextjs", is_rt: bool = False):
    legacy = {
        "full_text": text,
        "created_at": "Sun Oct 18 01:00:00 +0000 2026",
        "favorite_count": 42,
        "retweet_count": 10,
        "reply_count": 5,
        "lang": "en",
    }
    if is_rt:
        legacy["retweeted_status_result"] = {
            "result": {
                "__typename": "Tweet",
                "rest_id": "999",
                "legacy": {"full_text": "Original tweet"},
                "core": {"user_results": {"result": {"core": {"screen_name": "someone_else"}}}},
            }
        }
    return {
        "__typename": "Tweet",
        "rest_id": tid,
        "legacy": legacy,
        "views": {"count": "5000"},
        "core": {
            "user_results": {
                "result": {
                    "core": {"screen_name": user, "name": "Next.js"},
                    "legacy": {"followers_count": 500000},
                }
            }
        },
    }


def test_normal_timeline_fixture():
    payload = {
        "data": {
            "user": {
                "result": {
                    "timeline_v2": {
                        "timeline": {
                            "instructions": [
                                {
                                    "type": "TimelineAddEntries",
                                    "entries": [
                                        {
                                            "entryId": "tweet-1001",
                                            "content": {
                                                "itemContent": {
                                                    "tweet_results": {"result": _make_tweet_node("1001", "Next.js 15 is out!")}
                                                }
                                            },
                                        },
                                        {
                                            "entryId": "tweet-1002",
                                            "content": {
                                                "itemContent": {
                                                    "tweet_results": {"result": _make_tweet_node("1002", "Turbopack improvements")}
                                                }
                                            },
                                        },
                                        {
                                            "entryId": "cursor-bottom-1",
                                            "content": {"value": "CURSOR_BOTTOM_PAGE_2"},
                                        },
                                    ],
                                }
                            ]
                        }
                    }
                }
            }
        }
    }
    tweets, cursor = parse_user_tweets(payload)
    assert len(tweets) == 2
    assert tweets[0].id == "1001"
    assert tweets[0].text == "Next.js 15 is out!"
    assert tweets[0].is_pinned is False
    assert tweets[0].is_retweet is False
    assert tweets[1].id == "1002"
    assert cursor == "CURSOR_BOTTOM_PAGE_2"


def test_pinned_and_retweets_fixture():
    payload = {
        "data": {
            "user": {
                "result": {
                    "timeline_v2": {
                        "timeline": {
                            "instructions": [
                                {
                                    "type": "TimelinePinEntry",
                                    "entry": {
                                        "entryId": "pinned-tweet-9999",
                                        "content": {
                                            "itemContent": {
                                                "tweet_results": {"result": _make_tweet_node("9999", "Important Pinned Announcement")}
                                            }
                                        },
                                    },
                                },
                                {
                                    "type": "TimelineAddEntries",
                                    "entries": [
                                        {
                                            "entryId": "tweet-1003",
                                            "content": {
                                                "itemContent": {
                                                    "tweet_results": {"result": _make_tweet_node("1003", "RT @someone_else: Original tweet", is_rt=True)}
                                                }
                                            },
                                        },
                                    ],
                                },
                            ]
                        }
                    }
                }
            }
        }
    }
    tweets, cursor = parse_user_tweets(payload)
    assert len(tweets) == 2
    pinned = [t for t in tweets if t.id == "9999"][0]
    assert pinned.is_pinned is True
    rt = [t for t in tweets if t.is_retweet][0]
    assert rt.is_retweet is True
    assert rt.id == "999"


def test_empty_timeline_fixture():
    payload = {
        "data": {
            "user": {
                "result": {
                    "timeline_v2": {
                        "timeline": {
                            "instructions": [
                                {
                                    "type": "TimelineAddEntries",
                                    "entries": [
                                        {"entryId": "cursor-bottom-1", "content": {"value": "CURSOR_EMPTY"}}
                                    ],
                                }
                            ]
                        }
                    }
                }
            }
        }
    }
    tweets, cursor = parse_user_tweets(payload)
    assert tweets == []
    assert cursor == "CURSOR_EMPTY"


def test_collector_flags_protected_notfound_suspended():
    # 1. Protected
    col_prot = _Collector(op="UserTweets")
    col_prot.user_protected = True
    with pytest.raises(UserNotFoundError) as exc:
        XScraper._raise_flags(col_prot)
    assert "PROTECTED" in str(exc.value)

    # 2. Not Found
    col_missing = _Collector(op="UserTweets")
    col_missing.user_missing = True
    with pytest.raises(UserNotFoundError) as exc:
        XScraper._raise_flags(col_missing)
    assert "NOT_FOUND" in str(exc.value)

    # 3. Suspended
    col_susp = _Collector(op="UserTweets")
    col_susp.user_suspended = True
    with pytest.raises(UserNotFoundError) as exc:
        XScraper._raise_flags(col_susp)
    assert "SUSPENDED" in str(exc.value)

    # 4. Rate Limited
    col_rl = _Collector(op="UserTweets")
    col_rl.rate_limited = True
    with pytest.raises(RateLimitedError):
        XScraper._raise_flags(col_rl)

    # 5. Session Expired
    col_se = _Collector(op="UserTweets")
    col_se.unauthorized = True
    with pytest.raises(SessionExpiredError):
        XScraper._raise_flags(col_se)


# ==============================================================================
# 3. Search Regression (Scraping-level output identical)
# ==============================================================================

def test_search_parser_regression_identical():
    # Standard SearchTimeline payload must parse 100% identically
    search_payload = {
        "data": {
            "search_by_raw_query": {
                "search_timeline": {
                    "timeline": {
                        "instructions": [
                            {
                                "type": "TimelineAddEntries",
                                "entries": [
                                    {
                                        "entryId": "tweet-5555",
                                        "content": {
                                            "itemContent": {
                                                "tweet_results": {
                                                    "result": _make_tweet_node("5555", "hiring python developer for web3 team")
                                                }
                                            }
                                        },
                                    },
                                    {
                                        "entryId": "cursor-bottom-5555",
                                        "content": {"value": "SEARCH_CURSOR_VAL"},
                                    },
                                ],
                            }
                        ]
                    }
                }
            }
        }
    }
    tweets, cursor = parse_search_timeline(search_payload)
    assert len(tweets) == 1
    assert tweets[0].id == "5555"
    assert tweets[0].text == "hiring python developer for web3 team"
    assert tweets[0].author_username == "nextjs"
    assert cursor == "SEARCH_CURSOR_VAL"
