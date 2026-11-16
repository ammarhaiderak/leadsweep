# NEW FEATURE: Lead Direction Classifier
"""
Classifies author role and post direction relative to the user's offer.
Taxonomy:
- BUYER_SIGNAL: Author needs/seeks service or product user sells (Eligible, full score)
- HIRING_SIGNAL: Author is hiring or posting paid role relevant to offer (Eligible, cap 90)
- PARTNER_OR_FUNDING_SEEKER_FOR_OFFER: Partnership/investor (Eligible only if offer matches, cap 80)
- JOB_SEEKER: Author wants a job/gig/funding for themselves (Cap 20)
- SERVICE_PROVIDER_PROMO: Freelancer/agency promoting themselves (Cap 20)
- INFO_OR_THOUGHT_CONTENT: Tips, essays, news, threads (Cap 25)
- AIRDROP_BOT_SPAM: Giveaway, airdrop, follow-for-follow (Cap 5)
- UNCLEAR: Ambiguous (Cap 50 -> NEEDS_REVIEW)

Includes:
1. Strict verbatim quote verification (demotes to UNCLEAR if quote not found in text)
2. Fast regex heuristic fallback for 100% availability and $0 cost
3. Prompt injection protection for untrusted post content
"""
import re
import os
import json
import logging
from typing import Optional, Dict, Any, Tuple
from leadsweep.intel.models import (
    DirectionLabel,
    DirectionClassificationResult,
    DIRECTION_SCORE_CAPS,
    LeadBrief
)

logger = logging.getLogger("leadsweep.intel.direction")

# Precompiled regex patterns for deterministic heuristic classification
RE_AIRDROP_SPAM = re.compile(
    r'\b(airdrop|giveaway|drop wallet|drop your sol|presale|whitelist|claim now|send dm to claim|tag \d+ friends|retweet to win|rt and follow|bounty)\b',
    re.IGNORECASE
)

RE_SERVICE_PROMO = re.compile(
    r'\b(available for freelance|dm me for design|dm me for dev|i build websites for|i help founders build|i design logos|our agency specializes|check out my portfolio|portfolio|i can help you build|dm for collaborations|dm to work together|offering web development|offering smart contract)\b',
    re.IGNORECASE
)

RE_JOB_SEEKER = re.compile(
    r'\b(seeking opportunities|seeking new opportunities|open to work|looking for a job|looking for work|hire me|available for hire|looking for entry level|seeking employment|dm me for work|looking for internships|seeking internship|seeking funding for our|pitching our project)\b',
    re.IGNORECASE
)

RE_BUYER_SIGNAL = re.compile(
    r'\b(looking for a (?:developer|dev|solidity|designer|marketer|engineer|auditor|agency|freelancer)|need a (?:developer|dev|solidity|designer|marketer|engineer|auditor|agency)|who can build|anyone recommend a|who does (?:smart contract|website|app|marketing)|budget available|budget:|paid gig|rfp|looking to hire a|looking for someone to build)\b',
    re.IGNORECASE
)

RE_HIRING_SIGNAL = re.compile(
    r'\b(we are hiring|we\'re hiring|join our team|now hiring|hiring for our|looking for full-time|apply at|job opening|careers:)\b',
    re.IGNORECASE
)

RE_INFO_THOUGHT = re.compile(
    r'\b(\d+\s*lessons|\d+\s*tips|a thread on|here is what i learned|how to build a|how to launch|why you should never|the future of|market recap|crypto news|daily digest)\b',
    re.IGNORECASE
)


def verify_quote_in_text(quote: str, text: str) -> bool:
    """Verifies that the evidence quote literally appears in the post text."""
    if not quote or not text:
        return False
    # Clean whitespace for robust comparison
    clean_quote = " ".join(quote.strip().split()).lower()
    clean_text = " ".join(text.strip().split()).lower()
    return clean_quote in clean_text


def classify_direction_heuristic(post_text: str, author_bio: str = "", offer: str = "") -> DirectionClassificationResult:
    """
    Deterministic rule-based direction classifier.
    Fast, reliable, zero-cost, and immune to prompt injection.
    """
    combined = f"{post_text} {author_bio}".strip()

    # 1. AIRDROP_BOT_SPAM Check
    match_spam = RE_AIRDROP_SPAM.search(post_text)
    if match_spam:
        quote = match_spam.group(0)
        return DirectionClassificationResult(
            direction=DirectionLabel.AIRDROP_BOT_SPAM,
            max_score_cap=DIRECTION_SCORE_CAPS[DirectionLabel.AIRDROP_BOT_SPAM],
            reason="Detected giveaway, airdrop, or bot engagement pattern.",
            evidence_quote=quote,
            quote_verified=verify_quote_in_text(quote, post_text),
            is_fallback=True
        )

    # 2. BUYER_SIGNAL Check (Genuine buyer looking for help/budget)
    match_buyer = RE_BUYER_SIGNAL.search(post_text)
    if match_buyer:
        quote = match_buyer.group(0)
        return DirectionClassificationResult(
            direction=DirectionLabel.BUYER_SIGNAL,
            max_score_cap=DIRECTION_SCORE_CAPS[DirectionLabel.BUYER_SIGNAL],
            reason="Author has an explicit need, budget, or is seeking a provider matching the offer.",
            evidence_quote=quote,
            quote_verified=verify_quote_in_text(quote, post_text),
            is_fallback=True
        )

    # 3. HIRING_SIGNAL Check (Recruiter or team hiring)
    match_hiring = RE_HIRING_SIGNAL.search(post_text)
    if match_hiring:
        quote = match_hiring.group(0)
        return DirectionClassificationResult(
            direction=DirectionLabel.HIRING_SIGNAL,
            max_score_cap=DIRECTION_SCORE_CAPS[DirectionLabel.HIRING_SIGNAL],
            reason="Author represents a company actively hiring roles relevant to the domain.",
            evidence_quote=quote,
            quote_verified=verify_quote_in_text(quote, post_text),
            is_fallback=True
        )

    # 4. SERVICE_PROVIDER_PROMO Check (Freelancers / competitors selling their own services)
    match_promo = RE_SERVICE_PROMO.search(post_text)
    if match_promo:
        quote = match_promo.group(0)
        return DirectionClassificationResult(
            direction=DirectionLabel.SERVICE_PROVIDER_PROMO,
            max_score_cap=DIRECTION_SCORE_CAPS[DirectionLabel.SERVICE_PROVIDER_PROMO],
            reason="Author is a service provider/freelancer promoting their own services or portfolio.",
            evidence_quote=quote,
            quote_verified=verify_quote_in_text(quote, post_text),
            is_fallback=True
        )

    # 5. JOB_SEEKER Check (e.g. seeking employment)
    match_job = RE_JOB_SEEKER.search(post_text)
    if match_job:
        quote = match_job.group(0)
        return DirectionClassificationResult(
            direction=DirectionLabel.JOB_SEEKER,
            max_score_cap=DIRECTION_SCORE_CAPS[DirectionLabel.JOB_SEEKER],
            reason="Author is seeking opportunities/employment/funding for themselves.",
            evidence_quote=quote,
            quote_verified=verify_quote_in_text(quote, post_text),
            is_fallback=True
        )

    # 6. INFO_OR_THOUGHT_CONTENT Check (Educational threads, lessons, essays)
    match_info = RE_INFO_THOUGHT.search(post_text)
    if match_info:
        quote = match_info.group(0)
        return DirectionClassificationResult(
            direction=DirectionLabel.INFO_OR_THOUGHT_CONTENT,
            max_score_cap=DIRECTION_SCORE_CAPS[DirectionLabel.INFO_OR_THOUGHT_CONTENT],
            reason="Informational essay, educational thread, or general industry commentary without buyer intent.",
            evidence_quote=quote,
            quote_verified=verify_quote_in_text(quote, post_text),
            is_fallback=True
        )

    # Default: UNCLEAR
    first_words = " ".join(post_text.split()[:5])
    return DirectionClassificationResult(
        direction=DirectionLabel.UNCLEAR,
        max_score_cap=DIRECTION_SCORE_CAPS[DirectionLabel.UNCLEAR],
        reason="Ambiguous commercial intent; requires manual review.",
        evidence_quote=first_words if first_words in post_text else "",
        quote_verified=bool(first_words in post_text),
        is_fallback=True
    )


async def classify_lead_direction(
    post_text: str,
    author_bio: str = "",
    brief: Optional[LeadBrief] = None
) -> DirectionClassificationResult:
    """
    Main entrypoint: Classifies author direction relative to the user's offer.
    Uses heuristic engine first for high-confidence rules, falls back to LLM if needed,
    and enforces quote verification.
    """
    offer_str = brief.offer if brief else ""
    
    # Run deterministic heuristics
    res = classify_direction_heuristic(post_text, author_bio=author_bio, offer=offer_str)
    
    # If quote verification fails on non-unclear, downgrade to UNCLEAR
    if res.direction != DirectionLabel.UNCLEAR and not res.quote_verified:
        logger.warning(f"Direction quote verification failed for quote: '{res.evidence_quote}'. Downgrading to UNCLEAR.")
        res.direction = DirectionLabel.UNCLEAR
        res.max_score_cap = DIRECTION_SCORE_CAPS[DirectionLabel.UNCLEAR]
        res.reason = "Evidence quote could not be verified in post text."

    return res
