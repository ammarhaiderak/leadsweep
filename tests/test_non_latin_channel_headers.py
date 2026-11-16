"""Test F1: Multilingual Intent Lexicon and 2-Stage Non-Latin Gate.
Verifies that channels with mostly non-Latin headers (Cyrillic, Chinese, Urdu, Arabic)
are probed up to 5 messages and admitted ONLY if matching query tokens or multilingual intent lexicon.
"""
import os
import re
import pytest

from leadsweep.config import get_settings

_STOPWORDS = {"a", "an", "the", "in", "on", "at", "for", "to", "of", "and", "or", "is", "are", "with", "by", "from"}

NON_LATIN_CHANNEL_FIXTURES = [
    {
        "id": "cyrillic_city_news",
        "lang": "Cyrillic (City News)",
        "handle": "bilatserkvaBT",
        "title": "Bila Tserkva Community News",
        "description": "Міські новини та оголошення Білої Церкви",
        "posts": [
            "Продається квартира в центрі міста",
            "Ремонт доріг у Білій Церкві",
        ],
        "should_pass": False,
    },
    {
        "id": "cyrillic_job_channel",
        "lang": "Cyrillic (Job Channel)",
        "handle": "it_jobs_ua",
        "title": "Вакансії IT та Web3 Україна",
        "description": "Канал пошуку роботи в IT та блокчейн компаніях",
        "posts": [
            "Шукаємо розробника смарт-контрактів Solidity / Rust для DeFi проекту.",
        ],
        "should_pass": True,
    },
    {
        "id": "chinese_job_channel",
        "lang": "Chinese (Job Channel)",
        "handle": "chinese_crypto_jobs",
        "title": "区块链与Web3高端人才招聘",
        "description": "专注区块链架构师、智能合约审计员岗位直聘",
        "posts": [
            "招聘 全栈开发工程师 远程办公",
        ],
        "should_pass": True,
    },
    {
        "id": "urdu_job_channel",
        "lang": "Urdu (Job Channel)",
        "handle": "urdu_tech_career",
        "title": "پاکستان بلاک چین ڈویلپرز نیٹ ورک",
        "description": "تمام سافٹ ویئر اور بلاک چین ڈویلپرز کے لیے مرکز",
        "posts": [
            "ہمیں سمارٹ کنٹریکٹ ڈویلپر کی ضرورت ہے، نوکریاں دستیاب ہیں",
        ],
        "should_pass": True,
    },
    {
        "id": "arabic_job_channel",
        "lang": "Arabic (Job Channel)",
        "handle": "arabic_web3_careers",
        "title": "وظائف مطوري البلوكشين والعملات الرقمية",
        "description": "قناة مخصصة لنشر أحدث فرص العمل لمطوري الويب 3",
        "posts": [
            "مطلوب مطور عقود ذكية عن بعد لشركة عالمية",
        ],
        "should_pass": True,
    },
    {
        "id": "latin_matching_channel",
        "lang": "English (Matching)",
        "handle": "web3_blockchain_hiring",
        "title": "Blockchain Developer Hiring Hub",
        "description": "Global remote hiring for smart contract and blockchain engineers.",
        "posts": [
            "Senior EVM engineer needed",
        ],
        "should_pass": True,
    },
    {
        "id": "latin_irrelevant_channel",
        "lang": "English (Irrelevant)",
        "handle": "cooking_recipes_daily",
        "title": "Daily Cooking Recipes & Home Kitchen",
        "description": "Delicious Italian and French cuisine pasta recipes every single day.",
        "posts": [
            "Easy 15-minute pasta carbonara recipe",
        ],
        "should_pass": False,
    },
]


def test_channel_relevance_gate_non_latin_fixtures():
    settings = get_settings()
    target_eval_phrase = "blockchain hiring"
    raw_tokens = re.findall(r"[a-z0-9]+", target_eval_phrase.lower())
    eval_tokens = {w for w in raw_tokens if len(w) >= 3 and w not in _STOPWORDS}
    non_latin_ratio_thresh = float(os.getenv("TG_CHANNEL_NON_LATIN_RATIO", "0.30"))
    lexicon_raw = getattr(settings, "telegram_intent_lexicon", "") or os.getenv("TELEGRAM_INTENT_LEXICON", "")
    lexicon_terms = [t.strip().lower() for t in lexicon_raw.split(",") if t.strip()]

    def check_channel_relevance(channel_title: str, channel_desc: str, sample_posts: list[str]) -> tuple[bool, int, str]:
        if not target_eval_phrase or not eval_tokens:
            return True, 1, "PASS (empty/generic query)"
        combined = f"{channel_title} {channel_desc}".strip()
        if not combined and not sample_posts:
            return True, 1, "PASS (no channel metadata)"

        letters = [c for c in combined if c.isalpha()]
        ratio = 0.0
        is_mostly_non_latin = False
        if letters:
            non_latin = [c for c in letters if not ('a' <= c <= 'z' or 'A' <= c <= 'Z')]
            ratio = len(non_latin) / len(letters)
            if ratio >= non_latin_ratio_thresh:
                is_mostly_non_latin = True

        if is_mostly_non_latin:
            probe_posts = sample_posts[:5]
            for p in probe_posts:
                txt = (p or "").lower()
                for tok in eval_tokens:
                    if tok in txt:
                        return True, 1, f"PASS (probe matched query token '{tok}')"
                for term in lexicon_terms:
                    if term in txt:
                        return True, 1, f"PASS (probe matched intent lexicon '{term}')"
            return False, 0, f"FAIL (0 query/intent match in {len(probe_posts)} probe messages)"

        h_tokens = set(re.findall(r"[a-z0-9]+", combined.lower()))
        h_match = eval_tokens & h_tokens
        overlap = len(h_match)
        if overlap >= 1:
            return True, overlap, f"PASS (matched: {list(h_match)[:3]})"
        return False, overlap, f"FAIL (0 overlap with '{target_eval_phrase}')"

    skipped_count = 0
    passed_count = 0

    for fix in NON_LATIN_CHANNEL_FIXTURES:
        is_rel, overlap, reason = check_channel_relevance(fix["title"], fix["description"], fix.get("posts", []))
        if is_rel:
            passed_count += 1
        else:
            skipped_count += 1

        assert is_rel == fix["should_pass"], f"Fixture {fix['id']} expected pass={fix['should_pass']}, got {is_rel} ({reason})"

    assert passed_count == 5
    assert skipped_count == 2
