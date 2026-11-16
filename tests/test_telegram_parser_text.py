# NEW FEATURE: Telegram Parser Spacing & Normalized Formatting Tests (N1)
import pytest
from leadsweep.services.telegram_public_scraper import TelegramPublicScraper


def test_telegram_html_text_spacing_and_linebreaks():
    scraper = TelegramPublicScraper()
    raw_html = """
    <div class="tgme_channel_info_header_title">Web3 Job Board</div>
    <div class="tgme_widget_message_wrap">
        <div class="tgme_widget_message" data-post="web3hiring/1001">
            <div class="tgme_widget_message_text js-message_text" dir="auto">
                💼<b>Crypto.com</b>is hiring<a href="https://example.com/apply">Senior/Principal Product Manager</a><br>
                📍<i>Location: Remote</i><br><br>
                💰 Salary: $180k - $240k<br>
                DM with CV to apply!
            </div>
            <time datetime="2026-10-17T10:00:00+00:00">10:00 AM</time>
            <span class="tgme_widget_message_views">1.5K</span>
        </div>
    </div>
    """
    messages, oldest_id, channel_title = scraper.parse_page_html(raw_html, "web3hiring")
    assert len(messages) == 1
    msg = messages[0]
    
    # 1. Assert inline tags have space separation
    assert "Crypto.com is hiring Senior/Principal Product Manager" in msg.text
    # 2. Assert <br> tags are converted to newlines
    assert "\n" in msg.text
    assert "Location: Remote" in msg.text
    # 3. Assert emojis and symbols are preserved
    assert "💼" in msg.text
    assert "💰" in msg.text
    # 4. Assert no trailing squashed text
    assert "Crypto.comis hiring" not in msg.text
    assert "hiringSenior/Principal" not in msg.text


def test_telegram_bold_links_and_multiple_breaks():
    scraper = TelegramPublicScraper()
    raw_html = """
    <div class="tgme_widget_message_wrap">
        <div class="tgme_widget_message" data-post="web3hiring/1002">
            <div class="tgme_widget_message_text js-message_text" dir="auto">
                <b>Stripe</b>is hiring<b>Backend Engineer</b><br><br><br><br>
                <a href="https://stripe.com">Apply here</a>or contact <code>recruiter@stripe.com</code>
            </div>
            <time datetime="2026-10-17T11:00:00+00:00">11:00 AM</time>
        </div>
    </div>
    """
    messages, _, _ = scraper.parse_page_html(raw_html, "web3hiring")
    assert len(messages) == 1
    text = messages[0].text
    assert "Stripe is hiring Backend Engineer" in text
    assert "Apply here or contact recruiter@stripe.com" in text
    assert "\n\n\n" not in text  # Collapsed excessive newlines
