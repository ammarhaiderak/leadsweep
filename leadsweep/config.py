from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Origins allowed by default: the Vite dev server. Deliberately NOT a wildcard, because
# credentialed CORS with "*" is meaningless and misleading (browsers reject it anyway) and
# because an open CORS policy on a tool that drives authenticated browser sessions is a real risk.
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:5175,http://127.0.0.1:5175,http://localhost:4173,http://127.0.0.1:4173"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="LEADSWEEP_", extra="ignore", env_ignore_empty=True)

    leadsweep_env: str = "development"  # development | production
    turnstile_disabled: bool = False  # Allows explicit disable with warning
    cloudflare_turnstile_secret_key: str | None = None

    sessions_file: Path = Path("sessions.json")
    state_file: Path = Path("data/session_state.json")
    raw_dump_dir: Path = Path("data/raw")
    debug_dir: Path = Path("data/debug")
    debug_save_raw: bool = False

    headless: bool = True
    # Skip images/video/fonts while scraping X: ~60-80% less bandwidth and memory.
    # Post data arrives via GraphQL JSON, so lead quality is unaffected.
    block_media: bool = True
    browser_channel: str | None = None
    locale: str = "en-US"
    timezone_id: str = "UTC"

    min_delay: float = 0.4
    max_delay: float = 1.2
    max_scrolls: int = 12
    first_payload_timeout_s: float = 15.0
    session_cooldown_s: int = 300
    call_gap_min: float = 1.0  # Polite pause between consecutive MCP scrapes
    call_gap_max: float = 2.5

    log_level: str = "INFO"

    # ---- Follower Intelligence Safety Caps (Phase 6 / Stage 1)
    max_users_per_run: int = 300
    max_pages_per_run: int = 10
    follower_page_delay_min: float = 6.0
    follower_page_delay_max: float = 14.0
    min_hours_between_runs: float = 6.0
    per_session_daily_users: int = 1000

    # ---- NEW FEATURE (P3): pipeline / LLM / sinks
    queries_file: Path = Path("config/queries.toml")
    db_path: Path = Path("data/leadsweep.db")
    out_dir: Path = Path("data/out")
    llm_provider: str = "auto"  # auto | groq | ollama | heuristic
    llm_model: str = "qwen2.5:3b"  # Ollama model (Groq uses groq_model)
    ollama_url: str = "http://localhost:11434"
    groq_api_key: str | None = None  # UPDATED LOGIC: Accepts LEADSWEEP_GROQ_API_KEY or GROQ_API_KEY
    groq_model: str = "openai/gpt-oss-120b"  # cheap + strong; UPDATED LOGIC: Accepts LEADSWEEP_GROQ_MODEL or GROQ_MODEL
    groq_fallback_model: str | None = "openai/gpt-oss-20b"  # Accepts LEADSWEEP_GROQ_FALLBACK_MODEL or GROQ_FALLBACK_MODEL
    include_aggregators: bool = True  # NEW FEATURE: Allow job-board aggregators with verified roles
    llm_top_n: int = 150  # top candidates evaluated by LLM per job (caps Groq spend / free-tier quota)
    llm_timeout_s: int = 120
    min_score: int | None = None  # overrides config/queries.toml when set
    webhook_url: str | None = None

    # ---- API surface security (PHASE 1). No defaults with secrets in them.
    # Shared secret required in the `X-API-Key` header. When unset the API starts but every
    # non-public route is refused, so a missing deployment secret fails closed instead of open.
    api_key: str | None = None
    # Comma-separated list of browser origins allowed to call the API. No wildcard default.
    cors_origins: str = DEFAULT_CORS_ORIGINS
    # Directory of built frontend assets. When present, the API also serves the SPA.
    web_dist: Path | None = None
    # Maximum seconds an agent may wait for a human decision before auto-aborting.
    hitl_timeout_s: int = 3600
    # Login is OFF by default: LeadSweep is a single-user app you install and run locally, and
    # every dashboard request acts as one built-in owner. In that mode the server only answers
    # requests addressed to localhost (blocks DNS-rebinding from websites you visit).
    # Set true (plus LEADSWEEP_ADMIN_EMAIL / _PASSWORD) before exposing it on a network.
    require_login: bool = False
    # Extra Host names accepted while require_login is false (comma-separated), e.g. a hostname
    # you use to reach the app through an SSH tunnel. Ignored when require_login is true.
    allowed_hosts: str = ""

    # ---- Owner account & email notifications. No credentials ship with the code:
    # the owner account only exists once LEADSWEEP_ADMIN_EMAIL + LEADSWEEP_ADMIN_PASSWORD are set.
    owner_email: str = ""
    admin_email: str = ""
    admin_password: str = ""
    admin_name: str = "Owner"
    from_email: str = ""
    from_name: str = "LeadSweep"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True

    # ---- NEW FEATURE: Reddit Lead Generation (zero-credential, zero-cost first)
    # No Reddit account, OAuth client, token or cookie is ever configured here: the integration
    # is designed to work without them, or to report that access is restricted.
    reddit_enabled: bool = True
    reddit_access_mode: str = "public_unauthenticated"  # public_unauthenticated | offline_fixtures | disabled
    reddit_source_provider: str = "arctic_shift"  # arctic_shift (live public archive) | reddit_json (direct Reddit JSON)
    reddit_user_agent: str = "python:leadsweep:1.0 (self-hosted public-content-reader)"
    reddit_base_url: str = "https://www.reddit.com"
    reddit_archive_base_url: str = "https://arctic-shift.photon-reddit.com"
    reddit_max_requests_per_minute: int = 30  # conservative ceiling; documented OAuth limit is 100 QPM
    reddit_max_concurrent_requests: int = 1
    reddit_request_timeout: float = 20.0
    reddit_max_retries: int = 3
    reddit_cache_ttl_seconds: int = 900
    reddit_fixture_dir: Path = Path("data/reddit_fixtures")
    reddit_max_pages: int = 2
    reddit_page_size: int = 25
    reddit_comment_budget: int = 3
    reddit_circuit_breaker_ttl_s: float = 300.0

    # ---- NEW FEATURE: Telegram MTProto Scraper Configuration
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_session_path: Path = Path("sessions/telegram.session")
    # NEW FEATURE (N5 & A5/A6): Telegram Transport & Discovery Configuration
    telegram_transport: str = "auto"  # auto | direct | relay
    telegram_direct_timeout: float = 2.0  # Configurable direct connect timeout (default 2s)
    telegram_relay_max_requests: int = 25  # Per-job relay request budget (safe under 20 req/min limit)
    telegram_max_channels_per_job: int = 5  # Max candidate channels per job (default 5)
    telegram_max_messages_per_channel: int = 20  # Max messages scraped per channel (default 20 = 1 page)
    telegram_direct_cb_ttl_s: float = 300.0  # Circuit breaker TTL in seconds (default 5m)
    # NEW FEATURE (C4): Configurable Telegram Global Topics and Channel Registry
    telegram_global_topics: str = "web3 hiring, crypto jobs, remote developer, ai engineering"
    telegram_channel_registry: str = ""
    telegram_max_age_days: int = 30  # Freshness window in days (default 30, 0 = off)
    telegram_relevance_gate_threshold: int = 1  # C2 Relevance gate threshold (default 1 token)
    judge_max_chars: int = 1200  # C4 Judge input truncation (default 1200 chars)
    ollama_base_url: str = ""  # C5 Fallback Provider Chain (default off)
    ollama_model: str = ""  # C5 Fallback Provider Chain (default off)
    # NEW FEATURE (F1): Editable Multilingual Intent Lexicon
    telegram_intent_lexicon: str = (
        "hiring,hire,job,jobs,vacancy,vacancies,career,careers,recruit,recruiting,developer,engineer,contractor,wanted,seeking,position,"
        "вакансия,вакансии,вакансія,вакансії,робота,найм,шукаю,ищу,требуется,потрібен,розробник,разработчик,программист,програміст,инженер,інженер,"
        "招聘,直聘,招募,求职,雇佣,兼职,全职,岗位,开发,工程师,架构师,程序员,"
        "وظائف,وظيفة,نوکریاں,نوکری,مطلوب,توظيف,فرصة عمل,مطور,ڈویلپر,مبرمج,انجینئر"
    )
    # NEW FEATURE (G4): Configurable probe on 0-overlap Latin channels
    telegram_probe_zero_overlap: bool = True
    # When no post matches the query by keyword but an LLM judge is configured, pass the
    # channel's most recent posts to the judge instead of returning nothing.
    telegram_llm_passthrough: bool = True


def get_settings() -> Settings:
    import os
    s = Settings()
    if os.getenv("LEADSWEEP_ENV"):
        s.leadsweep_env = os.getenv("LEADSWEEP_ENV", "development").strip().lower()
    elif os.getenv("ENV"):
        s.leadsweep_env = os.getenv("ENV", "development").strip().lower()
    if os.getenv("LEADSWEEP_ADMIN_EMAIL"):
        s.admin_email = os.getenv("LEADSWEEP_ADMIN_EMAIL", "").strip()
    elif os.getenv("ADMIN_EMAIL"):
        s.admin_email = os.getenv("ADMIN_EMAIL", "").strip()
    elif os.getenv("LEADSWEEP_OWNER_EMAIL"):
        s.admin_email = os.getenv("LEADSWEEP_OWNER_EMAIL", "").strip()
    if os.getenv("LEADSWEEP_ADMIN_PASSWORD"):
        s.admin_password = os.getenv("LEADSWEEP_ADMIN_PASSWORD", "").strip()
    elif os.getenv("ADMIN_PASSWORD"):
        s.admin_password = os.getenv("ADMIN_PASSWORD", "").strip()
    if os.getenv("LEADSWEEP_ADMIN_NAME"):
        s.admin_name = os.getenv("LEADSWEEP_ADMIN_NAME", "").strip()
    elif os.getenv("ADMIN_NAME"):
        s.admin_name = os.getenv("ADMIN_NAME", "").strip()
    if os.getenv("LEADSWEEP_TURNSTILE_DISABLED") is not None:
        s.turnstile_disabled = os.getenv("LEADSWEEP_TURNSTILE_DISABLED", "").strip().lower() in ("1", "true", "yes")
    if os.getenv("CLOUDFLARE_TURNSTILE_SECRET_KEY"):
        s.cloudflare_turnstile_secret_key = os.getenv("CLOUDFLARE_TURNSTILE_SECRET_KEY")
    # UPDATED LOGIC: Fallback to non-prefixed GROQ_API_KEY / GROQ_MODEL if not set via LEADSWEEP_
    if not s.groq_api_key:
        s.groq_api_key = os.getenv("GROQ_API_KEY")
    if os.getenv("GROQ_MODEL"):
        s.groq_model = os.getenv("GROQ_MODEL")
    if os.getenv("LEADSWEEP_GROQ_FALLBACK_MODEL"):
        s.groq_fallback_model = os.getenv("LEADSWEEP_GROQ_FALLBACK_MODEL")
    elif os.getenv("GROQ_FALLBACK_MODEL"):
        s.groq_fallback_model = os.getenv("GROQ_FALLBACK_MODEL")
    if os.getenv("LEADSWEEP_OLLAMA_BASE_URL"):
        s.ollama_base_url = os.getenv("LEADSWEEP_OLLAMA_BASE_URL")
    if os.getenv("LEADSWEEP_OLLAMA_MODEL"):
        s.ollama_model = os.getenv("LEADSWEEP_OLLAMA_MODEL")
    if os.getenv("LEADSWEEP_JUDGE_MAX_CHARS"):
        try:
            s.judge_max_chars = int(os.getenv("LEADSWEEP_JUDGE_MAX_CHARS"))
        except ValueError:
            pass
    if os.getenv("LEADSWEEP_TELEGRAM_RELEVANCE_THRESHOLD"):
        try:
            s.telegram_relevance_gate_threshold = int(os.getenv("LEADSWEEP_TELEGRAM_RELEVANCE_THRESHOLD"))
        except ValueError:
            pass
    if os.getenv("LEADSWEEP_TELEGRAM_MAX_AGE_DAYS") is not None:
        try:
            s.telegram_max_age_days = int(os.getenv("LEADSWEEP_TELEGRAM_MAX_AGE_DAYS"))
        except ValueError:
            pass
    if os.getenv("LEADSWEEP_TELEGRAM_INTENT_LEXICON"):
        s.telegram_intent_lexicon = os.getenv("LEADSWEEP_TELEGRAM_INTENT_LEXICON")
    elif os.getenv("TELEGRAM_INTENT_LEXICON"):
        s.telegram_intent_lexicon = os.getenv("TELEGRAM_INTENT_LEXICON")
    # NEW FEATURE: Reddit settings accept both LEADSWEEP_REDDIT_* and bare REDDIT_* names
    if os.getenv("REDDIT_ENABLED") is not None:
        s.reddit_enabled = os.getenv("REDDIT_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")
    if os.getenv("REDDIT_ACCESS_MODE"):
        s.reddit_access_mode = os.getenv("REDDIT_ACCESS_MODE", "").strip().lower()
    if os.getenv("REDDIT_SOURCE_PROVIDER"):
        s.reddit_source_provider = os.getenv("REDDIT_SOURCE_PROVIDER", "").strip().lower()
    elif os.getenv("LEADSWEEP_REDDIT_SOURCE_PROVIDER"):
        s.reddit_source_provider = os.getenv("LEADSWEEP_REDDIT_SOURCE_PROVIDER", "").strip().lower()
    if os.getenv("REDDIT_ARCHIVE_BASE_URL"):
        s.reddit_archive_base_url = os.getenv("REDDIT_ARCHIVE_BASE_URL", "").strip()
    elif os.getenv("LEADSWEEP_REDDIT_ARCHIVE_BASE_URL"):
        s.reddit_archive_base_url = os.getenv("LEADSWEEP_REDDIT_ARCHIVE_BASE_URL", "").strip()
    if os.getenv("REDDIT_USER_AGENT"):
        s.reddit_user_agent = os.getenv("REDDIT_USER_AGENT", "").strip()
    if os.getenv("REDDIT_MAX_REQUESTS_PER_MINUTE"):
        try:
            s.reddit_max_requests_per_minute = int(os.getenv("REDDIT_MAX_REQUESTS_PER_MINUTE", "0"))
        except ValueError:
            pass
    if os.getenv("REDDIT_MAX_CONCURRENT_REQUESTS"):
        try:
            s.reddit_max_concurrent_requests = int(os.getenv("REDDIT_MAX_CONCURRENT_REQUESTS", "0"))
        except ValueError:
            pass
    if os.getenv("REDDIT_REQUEST_TIMEOUT"):
        try:
            s.reddit_request_timeout = float(os.getenv("REDDIT_REQUEST_TIMEOUT", "0"))
        except ValueError:
            pass
    if os.getenv("REDDIT_MAX_RETRIES"):
        try:
            s.reddit_max_retries = int(os.getenv("REDDIT_MAX_RETRIES", "0"))
        except ValueError:
            pass
    if os.getenv("REDDIT_CACHE_TTL_SECONDS"):
        try:
            s.reddit_cache_ttl_seconds = int(os.getenv("REDDIT_CACHE_TTL_SECONDS", "0"))
        except ValueError:
            pass
    if os.getenv("REDDIT_FIXTURE_DIR"):
        s.reddit_fixture_dir = Path(os.getenv("REDDIT_FIXTURE_DIR", "data/reddit_fixtures"))
    if os.getenv("TELEGRAM_PROBE_ZERO_OVERLAP") is not None:
        s.telegram_probe_zero_overlap = os.getenv("TELEGRAM_PROBE_ZERO_OVERLAP", "").lower() in ("1", "true", "yes")
    elif os.getenv("LEADSWEEP_TELEGRAM_PROBE_ZERO_OVERLAP") is not None:
        s.telegram_probe_zero_overlap = os.getenv("LEADSWEEP_TELEGRAM_PROBE_ZERO_OVERLAP", "").lower() in ("1", "true", "yes")
    return s


def parse_cors_origins(raw: str) -> list[str]:
    """Split the LEADSWEEP_CORS_ORIGINS value into a clean origin list.

    Empty entries are dropped and an empty result yields an empty list, which makes
    CORSMiddleware deny every cross-origin request instead of allowing any.
    """
    return [o.strip() for o in raw.split(",") if o.strip()]
