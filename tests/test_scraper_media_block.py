"""Media blocking must drop CDN images/video/fonts but never the GraphQL data requests."""
import pytest

from leadsweep.config import Settings
from leadsweep.scraper import _MEDIA_URL_RE


@pytest.mark.parametrize("url", [
    "https://pbs.twimg.com/media/abc?format=jpg&name=small",
    "https://pbs.twimg.com/profile_images/1/x_normal.jpg",
    "https://video.twimg.com/ext_tw_video/1/pu/vid/a.mp4",
    "https://abs.twimg.com/fonts/chirp-regular.woff2",
])
def test_blocks_media(url):
    assert _MEDIA_URL_RE.search(url)


@pytest.mark.parametrize("url", [
    "https://x.com/i/api/graphql/abc/SearchTimeline?variables=%7B%7D",
    "https://x.com/i/api/graphql/abc/UserTweets?variables=%7B%7D",
    "https://abs.twimg.com/responsive-web/client-web/main.js",
    "https://abs.twimg.com/responsive-web/client-web/main.css",
    "https://x.com/search?q=hiring&src=typed_query",
])
def test_keeps_data_and_app(url):
    assert not _MEDIA_URL_RE.search(url)


def test_block_media_default_on():
    assert Settings(_env_file=None).block_media is True
