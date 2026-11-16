from leadsweep.parser import parse_search_timeline


def _tweet_entry(rest_id, text, screen_name="alice", **legacy_extra):
    legacy = {"full_text": text, "created_at": "Wed Oct 10 20:19:24 +0000 2018", "favorite_count": 5,
              "retweet_count": 2, "reply_count": 1, "quote_count": 0, "lang": "en", **legacy_extra}
    return {
        "entryId": f"tweet-{rest_id}",
        "content": {"itemContent": {"tweet_results": {"result": {
            "__typename": "Tweet", "rest_id": rest_id, "legacy": legacy, "views": {"count": "1200"},
            "core": {"user_results": {"result": {"core": {"screen_name": screen_name, "name": "Alice"},
                                                 "legacy": {"followers_count": 999}}}},
        }}}},
    }


PAYLOAD = {"data": {"search_by_raw_query": {"search_timeline": {"timeline": {"instructions": [
    {"type": "TimelineAddEntries", "entries": [
        _tweet_entry("1", "Need an AI automation dev for our agency"),
        _tweet_entry("2", "short"),
        {"entryId": "tweet-3", "content": {"itemContent": {"tweet_results": {"result": {"__typename": "TweetTombstone"}}}}},
        {"entryId": "cursor-bottom-99", "content": {"value": "CURSOR123"}},
    ]},
]}}}}}


def test_parses_tweets_and_cursor():
    tweets, cursor = parse_search_timeline(PAYLOAD)
    assert [t.id for t in tweets] == ["1", "2"]          # tombstone skipped
    assert cursor == "CURSOR123"
    t = tweets[0]
    assert t.author_username == "alice" and t.author_followers == 999
    assert t.view_count == 1200 and t.like_count == 5
    assert t.url == "https://x.com/alice/status/1"
    assert t.created_at is not None


def test_note_tweet_long_text_preferred():
    e = _tweet_entry("4", "truncated…")
    e["content"]["itemContent"]["tweet_results"]["result"]["note_tweet"] = {
        "note_tweet_results": {"result": {"text": "the full long text"}}}
    payload = {"data": {"search_by_raw_query": {"search_timeline": {"timeline": {"instructions": [
        {"entries": [e]}]}}}}}
    tweets, _ = parse_search_timeline(payload)
    assert tweets[0].text == "the full long text"


def test_garbage_payload_never_raises():
    assert parse_search_timeline({}) == ([], None)
    assert parse_search_timeline({"data": {"x": 1}}) == ([], None)


def test_followers_found_in_new_and_old_locations():
    from leadsweep.parser import parse_tweet_result

    def tw(user):
        return {"__typename": "Tweet", "rest_id": "5", "legacy": {"full_text": "hello"},
                "core": {"user_results": {"result": {"core": {"screen_name": "a"}, **user}}}}

    assert parse_tweet_result(tw({"legacy": {"followers_count": 12}})).author_followers == 12
    assert parse_tweet_result(tw({"relationship_counts": {"followers": 34}})).author_followers == 34
    assert parse_tweet_result(tw({"stats": {"deep": {"followers_count": "56"}}})).author_followers == 56
    assert parse_tweet_result(tw({})).author_followers is None


def test_created_at_fallback_to_snowflake_id():
    from leadsweep.parser import parse_tweet_result
    from datetime import datetime, timezone

    # moledao_io tweet ID 2111645944814993481 -> Oct 18 2026 02:30:00 UTC
    tid = "2111645944814993481"
    raw = {
        "__typename": "Tweet",
        "rest_id": tid,
        "legacy": {"full_text": "Hiring Director of Operations"},
        "core": {"user_results": {"result": {"core": {"screen_name": "moledao_io"}}}},
    }
    tweet = parse_tweet_result(raw)
    assert tweet is not None
    assert tweet.created_at is not None
    expected_ms = (int(tid) >> 22) + 1288834974657
    expected_dt = datetime.fromtimestamp(expected_ms / 1000.0, tz=timezone.utc)
    assert tweet.created_at == expected_dt
    assert tweet.created_at.strftime("%Y-%m-%d %H:%M:%S") == "2026-10-18 02:30:00"

