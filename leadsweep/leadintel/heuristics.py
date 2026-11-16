# NEW FEATURE: Lead Intelligence Local Heuristic Fallbacks
"""
Deterministic, $0, ultra-fast regex and rule-based heuristics for:
1. Direction classification (JOB_SEEKER, SERVICE_PROVIDER_PROMO, AIRDROP_BOT_SPAM, INFO_OR_THOUGHT_CONTENT, BUYER_SIGNAL, HIRING_SIGNAL)
2. Verbatim evidence quote verification
3. Prompt injection detection
"""
import re
import logging
from typing import Tuple, Optional
from leadsweep.leadintel.models import DirectionLabel, DirectionClassificationResult, DIRECTION_SCORE_CAPS

log = logging.getLogger("leadsweep.leadintel.heuristics")

# Precompiled detection patterns
RE_INJECTION = re.compile(
    r'(ignore previous instructions|ignore all instructions|system prompt|disregard|score me 100|you are an ai|override prompt|admin mode)',
    re.IGNORECASE
)

RE_AIRDROP_SPAM = re.compile(
    r'\b(airdrop|giveaway|drop wallet|drop your sol|presale|whitelist|claim now|send dm to claim|tag \d+ friends|retweet to win|rt and follow|bounty|airdrop quest|zealy quest|galxe quest)\b',
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
    r'\b(looking for (?:a|an)?\s*(?:reliable\s+|experienced\s+)?(?:developer|dev|solidity|designer|marketer|engineer|auditor|agency|freelancer|team|firm|partner|vendor|smart contract auditor)|need (?:a|an)?\s*(?:reliable\s+|experienced\s+)?(?:developer|dev|solidity|designer|marketer|engineer|auditor|agency|team|firm|partner)|who can build|anyone recommend a|who does (?:smart contract|website|app|marketing|audit)|budget available|budget is|budget:|paid gig|rfp|looking to hire a|looking for someone to (?:build|audit|develop))\b',
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


def verify_evidence_quote(quote: str, text: str) -> bool:
    """Verifies that evidence_quote is a literal verbatim substring of text."""
    if not quote or not text:
        return False
    clean_q = " ".join(quote.strip().split()).lower()
    clean_t = " ".join(text.strip().split()).lower()
    return clean_q in clean_t


def classify_direction_rules(post_text: str, author_bio: str = "", offer: str = "") -> DirectionClassificationResult:
    """
    Deterministic rule-based direction classification.
    Zero latency, $0 cost, prompt-injection safe.
    """
    # 0. Prompt injection check
    if RE_INJECTION.search(post_text):
        log.warning("Prompt injection attempt detected in post text. Flagging and demoting.")
        return DirectionClassificationResult(
            direction=DirectionLabel.AIRDROP_BOT_SPAM,
            max_score_cap=5,
            reason="Malicious prompt injection / adversarial manipulation pattern detected.",
            evidence_quote="prompt injection",
            quote_verified=True,
            is_fallback=True
        )

    # 1. Airdrop / Bounty / Bot Spam
    m_spam = RE_AIRDROP_SPAM.search(post_text)
    if m_spam:
        quote = m_spam.group(0)
        return DirectionClassificationResult(
            direction=DirectionLabel.AIRDROP_BOT_SPAM,
            need_strength=0.0,
            urgency=0.0,
            icp_fit=0.0,
            max_score_cap=DIRECTION_SCORE_CAPS[DirectionLabel.AIRDROP_BOT_SPAM],
            reason="Detected airdrop, giveaway, or spam pattern.",
            evidence_quote=quote,
            quote_verified=verify_evidence_quote(quote, post_text),
            is_fallback=True
        )

    # 2. Service Provider Self-Promo / Freelancers
    m_promo = RE_SERVICE_PROMO.search(post_text)
    if m_promo:
        quote = m_promo.group(0)
        return DirectionClassificationResult(
            direction=DirectionLabel.SERVICE_PROVIDER_PROMO,
            need_strength=0.1,
            urgency=0.1,
            icp_fit=0.2,
            max_score_cap=DIRECTION_SCORE_CAPS[DirectionLabel.SERVICE_PROVIDER_PROMO],
            reason="Author is a competitor or freelancer marketing their own services.",
            evidence_quote=quote,
            quote_verified=verify_evidence_quote(quote, post_text),
            is_fallback=True
        )

    # 3. Job / Funding Seeker (e.g. @Web3temple)
    m_job = RE_JOB_SEEKER.search(post_text)
    if m_job:
        quote = m_job.group(0)
        return DirectionClassificationResult(
            direction=DirectionLabel.JOB_SEEKER,
            need_strength=0.1,
            urgency=0.2,
            icp_fit=0.2,
            max_score_cap=DIRECTION_SCORE_CAPS[DirectionLabel.JOB_SEEKER],
            reason="Author is seeking a job, contract work, or funding for themselves.",
            evidence_quote=quote,
            quote_verified=verify_evidence_quote(quote, post_text),
            is_fallback=True
        )

    # 4. Buyer Signal (Target lead)
    m_buyer = RE_BUYER_SIGNAL.search(post_text)
    if m_buyer:
        quote = m_buyer.group(0)
        return DirectionClassificationResult(
            direction=DirectionLabel.BUYER_SIGNAL,
            need_strength=0.9,
            urgency=0.8,
            icp_fit=0.85,
            confidence=0.9,
            max_score_cap=DIRECTION_SCORE_CAPS[DirectionLabel.BUYER_SIGNAL],
            reason="Explicit buyer demand, RFP, or hiring phrase matching offer.",
            evidence_quote=quote,
            quote_verified=verify_evidence_quote(quote, post_text),
            is_fallback=True
        )

    # 5. Hiring Signal
    m_hiring = RE_HIRING_SIGNAL.search(post_text)
    if m_hiring:
        quote = m_hiring.group(0)
        return DirectionClassificationResult(
            direction=DirectionLabel.HIRING_SIGNAL,
            need_strength=0.85,
            urgency=0.75,
            icp_fit=0.8,
            confidence=0.85,
            max_score_cap=DIRECTION_SCORE_CAPS[DirectionLabel.HIRING_SIGNAL],
            reason="Company or founder actively hiring paid roles in domain.",
            evidence_quote=quote,
            quote_verified=verify_evidence_quote(quote, post_text),
            is_fallback=True
        )

    # 6. Informational Essay / Thought Leadership
    m_info = RE_INFO_THOUGHT.search(post_text)
    if m_info:
        quote = m_info.group(0)
        return DirectionClassificationResult(
            direction=DirectionLabel.INFO_OR_THOUGHT_CONTENT,
            need_strength=0.1,
            urgency=0.0,
            icp_fit=0.3,
            max_score_cap=DIRECTION_SCORE_CAPS[DirectionLabel.INFO_OR_THOUGHT_CONTENT],
            reason="Educational tips, thread, or commentary without purchase intent.",
            evidence_quote=quote,
            quote_verified=verify_evidence_quote(quote, post_text),
            is_fallback=True
        )

    # Default: UNCLEAR
    first_words = " ".join(post_text.split()[:4])
    return DirectionClassificationResult(
        direction=DirectionLabel.UNCLEAR,
        need_strength=0.3,
        urgency=0.2,
        icp_fit=0.3,
        max_score_cap=DIRECTION_SCORE_CAPS[DirectionLabel.UNCLEAR],
        reason="Ambiguous commercial intent; sent to review queue.",
        evidence_quote=first_words if first_words in post_text else "",
        quote_verified=bool(first_words in post_text),
        is_fallback=True
    )
