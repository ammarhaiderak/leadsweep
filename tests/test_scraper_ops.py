import asyncio
from types import SimpleNamespace

from leadsweep.config import Settings
from leadsweep.parser import parse_user_tweets
from leadsweep.scraper import _OP_ALIASES, XScraper, _Collector

_RESULT = {"__typename": "Tweet", "rest_id": "7", "legacy": {"full_text": "hi"},
           "core": {"user_results": {"result": {"core": {"screen_name": "gh"}}}}}
_ENTRY = {"entryId": "tweet-7", "content": {"itemContent": {"tweet_results": {"result": _RESULT}}}}
PAYLOAD = {"data": {"user": {"result": {"timeline": {"timeline": {"instructions": [{"entries": [_ENTRY]}]}}}}}}


def _resp(op, status=200):
    async def _json():
        return PAYLOAD
    return SimpleNamespace(url=f"https://x.com/i/api/graphql/HASH/{op}?variables=1", status=status,
                           request=SimpleNamespace(method="GET"), json=_json)


def _setup():
    sc = XScraper.__new__(XScraper)
    sc.settings = Settings()
    return sc, _Collector(op="UserTweets", parse=parse_user_tweets, accept=_OP_ALIASES["UserTweets"])


def test_renamed_profile_op_is_accepted():
    sc, col = _setup()
    asyncio.run(sc._on_response(_resp("UserOriginalsTimeline"), col))
    assert list(col.tweets) == ["7"] and col.wake.is_set()


def test_old_name_still_accepted_and_lookalike_ops_ignored():
    sc, col = _setup()
    asyncio.run(sc._on_response(_resp("UserTweetsAndReplies"), col))
    assert not col.tweets and not col.wake.is_set()
    asyncio.run(sc._on_response(_resp("UserTweets"), col))
    assert list(col.tweets) == ["7"]
