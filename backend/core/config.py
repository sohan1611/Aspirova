from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env-based settings. Never hardcode secrets (Doc 08 §2)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "development"
    database_url: str = ""
    # Optional pool-mode override. Transaction mode is auto-detected from a
    # Supabase :6543 URL; setting this to "transaction" forces transaction
    # mode even on another port. The default "session" means "auto/session".
    db_pool_mode: str = "session"
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""
    cors_origins: str = "http://localhost:3000"
    # Public site base for links in outbound email. Must match the frontend's
    # canonical SITE_URL (app/layout.tsx) exactly - the apex redirects to www,
    # so a non-www link would cost every email click an extra hop.
    site_url: str = "https://www.aspirova.org"

    # AI providers (Doc 05, Doc handoffs/PHASE-3-HANDOFF.md Part 1).
    # Blank keys select the deterministic local stub: no network call, no
    # spend, and no hard failure. Model/runtime controls stay env-driven.
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ai_generation_model: str = "claude-haiku-4-5"
    ai_embedding_model: str = "text-embedding-3-small"
    ai_embedding_dim: int = 1536
    ai_max_output_tokens: int = 512
    ai_daily_usd_cap: float = 0.45
    ai_generation_input_usd_per_mtok: float = 1.0
    ai_generation_output_usd_per_mtok: float = 5.0
    ai_embedding_input_usd_per_mtok: float = 0.02

    # Upstash Redis REST API (rate limiting + read cache - Doc
    # handoffs/PHASE-2-HANDOFF.md sec 11). Blank = not configured yet, which
    # every caller must treat as "fail open" (sec 11.2), never as an error.
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""
    redis_timeout_seconds: float = 0.75

    # Subscription grace, limits/TTL are config, not code (sec 11.4) -
    # Sonnet may retune these, but they must stay env-driven.
    subscription_grace_days: int = 3
    rate_limit_ip_feed_search_per_minute: int = 60
    rate_limit_ip_opportunity_per_minute: int = 120
    rate_limit_user_bookmark_write_per_minute: int = 30
    rate_limit_user_dream_company_write_per_minute: int = 30
    rate_limit_user_saved_search_write_per_minute: int = 20
    rate_limit_user_copilot_per_day: int = 20
    rate_limit_ip_waitlist_per_minute: int = 5
    rate_limit_ip_report_per_minute: int = 5
    rate_limit_ip_view_per_minute: int = 60
    read_cache_ttl_seconds: int = 45
    stats_cache_ttl_seconds: int = 300
    copilot_cache_ttl_seconds: int = 3600

    # Independent nightly backup (Doc 03 sec 8/9) - S3-compatible object
    # storage, so this works unchanged against either Cloudflare R2 or
    # Backblaze B2 (the user's choice, Doc handoffs/PHASE-2-HANDOFF.md sec
    # 10); just point the endpoint at whichever one is created. Blank =
    # not configured yet.
    backup_s3_endpoint_url: str = ""
    backup_s3_access_key_id: str = ""
    backup_s3_secret_access_key: str = ""
    backup_s3_bucket: str = ""

    # Razorpay (Doc 02 sec 3.9, Doc handoffs/PHASE-2-HANDOFF.md sec 6) -
    # test-mode keys first (Doc handoffs/PHASE-2-HANDOFF.md sec 2: "never
    # auto-charge or auto-create live billing"). Blank = payments routes
    # fail closed with a clear error, never silently accept a checkout.
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    # Resend (Doc 02 sec 3.6, Doc handoffs/PHASE-2-HANDOFF.md sec 5) -
    # sending domain needs SPF/DKIM/DMARC verified in the Resend dashboard
    # first (Doc handoffs/PHASE-2-HANDOFF.md sec 10, manual prerequisite).
    # Blank = the notification worker logs + records a 'failed' row per
    # skipped send instead of silently no-oping, so gaps are visible.
    resend_api_key: str = ""
    resend_from_email: str = ""

    # Pricing-page waitlist (Doc handoffs/PHASE-2.5-HANDOFF.md sec 3.7) -
    # the honest Razorpay dummy: no checkout, just a founder notification
    # via the existing Resend seam. Blank = signups are accepted (still
    # return ok to the visitor - never surface an internal delivery gap on
    # a public marketing page) but logged instead of emailed.
    waitlist_notify_email: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
