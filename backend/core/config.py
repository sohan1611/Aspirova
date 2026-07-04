from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env-based settings. Never hardcode secrets (Doc 08 §2)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "development"
    database_url: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""
    cors_origins: str = "http://localhost:3000"

    # Upstash Redis REST API (rate limiting + read cache - Doc
    # handoffs/PHASE-2-HANDOFF.md sec 11). Blank = not configured yet, which
    # every caller must treat as "fail open" (sec 11.2), never as an error.
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""
    redis_timeout_seconds: float = 0.75

    # Limits/TTL are config, not code (sec 11.4) - Sonnet may retune these,
    # but they must stay env-driven.
    rate_limit_ip_feed_search_per_minute: int = 60
    rate_limit_ip_opportunity_per_minute: int = 120
    rate_limit_user_bookmark_write_per_minute: int = 30
    read_cache_ttl_seconds: int = 45

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
