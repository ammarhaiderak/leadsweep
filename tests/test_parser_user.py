from leadsweep.parser import parse_user_tweets, user_exists


def _res(rest_id, text, screen="bob"):
    return {"__typename": "Tweet", "rest_id": rest_id,
            "legacy": {"full_text": text, "created_at": "Wed Oct 10 20:19:24 +0000 2018", "favorite_count": 1},
            "core": {"user_results": {"result": {"core": {"screen_name": screen, "name": "Bob"}}}}}


def _entry(rest_id, text):
    return {"entryId": f"tweet-{rest_id}", "content": {"itemContent": {"tweet_results": {"result": _res(rest_id, text)}}}}


def _payload(key):
    return {"data": {"user": {"result": {key: {"timeline": {"instructions": [
        {"type": "TimelinePinEntry", "entry": _entry("9", "pinned")},
        {"type": "TimelineAddEntries", "entries": [
            _entry("1", "one"),
            {"entryId": "profile-conversation-5", "content": {"items": [
                {"item": {"itemContent": {"tweet_results": {"result": _res("2", "thread a")}}}},
                {"item": {"itemContent": {"tweet_results": {"result": _res("3", "thread b")}}}}]}},
            {"entryId": "cursor-bottom-1", "content": {"value": "CUR"}},
        ]},
    ]}}}}}}


def test_both_timeline_key_variants():
    for key in ("timeline", "timeline_v2"):
        tweets, cursor = parse_user_tweets(_payload(key))
        assert [t.id for t in tweets] == ["9", "1", "2", "3"]  # pinned + single + thread module
        assert cursor == "CUR"


def test_garbage_never_raises():
    assert parse_user_tweets({}) == ([], None)
    assert parse_user_tweets({"data": {"user": {}}}) == ([], None)


def test_user_exists():
    assert user_exists({"data": {"user": {"result": {"rest_id": "1", "__typename": "User"}}}})
    assert not user_exists({"data": {"user": {"result": {"__typename": "UserUnavailable"}}}})
    assert not user_exists({"data": {}})


def test_renamed_timeline_key_and_entry_ids():
    """P2.1: unknown container key + unknown entryId prefix + promoted entry must still parse."""
    payload = {"data": {"user": {"result": {"timeline_originals": {"wrapper": {"instructions": [
        {"type": "TimelineAddEntries", "entries": [
            {"entryId": "originals-1", "content": {"itemContent": {"tweet_results": {"result": _res("7", "orig")}}}},
            {"entryId": "promoted-tweet-2", "content": {"itemContent": {"tweet_results": {"result": _res("8", "ad")}}}},
            {"entryId": "cursor-bottom-3", "content": {"value": "C2"}},
        ]}]}}}}}}
    tweets, cursor = parse_user_tweets(payload)
    assert [t.id for t in tweets] == ["7"] and cursor == "C2"
