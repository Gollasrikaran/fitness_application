"""Configuration with fail-fast validation.

STRATEGY_AND_OPS §11: one canonical variable per concern, validated at boot.
Production refuses to start if anything required is missing — silent degradation
is worse than a failed deploy.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta


class ConfigError(RuntimeError):
    """Raised at boot when required configuration is absent or invalid."""


# Found live (code audit): FLASK_ENV was read with a plain default and compared
# by exact string equality with nothing validating it against this set. Unset,
# misspelled, or wrong-case ("Production", "PROD", "staging", a trailing
# space) all silently fell through to the dev branch below — hardcoded dev
# secrets, hardcoded dev JWT key, the internal devconsole blueprint mounted
# unauthenticated (see app/factory.py), debug-level logging. This one variable
# controls the entire production security posture, so an unrecognized value
# must refuse to boot, not silently degrade.
_VALID_ENVS = {"development", "test", "production"}


def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise ConfigError(
            f"{name} is required and not set. "
            "Production must not start with incomplete configuration (STRATEGY §11)."
        )
    return val


def _optional(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class Config:
    env: str
    debug: bool

    secret_key: str
    database_url: str

    # Two Redis instances, not four (STRATEGY §6). Exactly these two names are
    # read; nothing else in the codebase may invent another Redis variable.
    redis_durable_url: str
    redis_cache_url: str

    # --- Module 5: rehab & pain RAG ---------------------------------------
    # A separate Postgres (Supabase + pgvector) from database_url above, by
    # design — the vector store stays out of the primary datastore's blast
    # radius (STRATEGY §5). Not yet required in production: that's a real
    # deploy decision nobody has made, so an unset value here degrades to
    # "Module 5 answers with a config error" rather than refusing to boot.
    rag_database_url: str
    openrouter_api_key: str

    # --- RLM (Implementation_RLM_plan.md Phase 7) -------------------------
    # Independent flags so the silent backend curve (Phase 2) can ship without
    # waiting on the LLM-facing chat analysis (Phase 3/4/5), and either half
    # can be switched off on its own if something needs investigating —
    # without touching code, per the plan's own rollout guidance.
    rlm_weekly_progression_enabled: bool
    rlm_chat_analysis_enabled: bool

    # --- Module 1: tokens -------------------------------------------------
    jwt_current_kid: str
    jwt_keys: dict[str, str]  # kid -> secret. Two active keys allow rotation (1.3)
    access_token_ttl: timedelta
    refresh_token_ttl: timedelta          # sliding window (1.4)
    refresh_absolute_cap: timedelta       # 180d from original login (1.4)
    refresh_grace: timedelta              # ~30s, device-bound (1.4)

    # --- Module 1: password / lockout ------------------------------------
    password_min_length: int
    breach_check_enabled: bool
    login_lockout_threshold: int
    login_lockout_base_seconds: int

    # --- Module 2: rate limits (three independent limits, 2.3) -----------
    rl_user_per_minute: int
    rl_device_per_hour: int
    rl_ip_per_hour: int

    # --- Product constants ------------------------------------------------
    timezone: str = "Asia/Kolkata"   # single market (3.3)
    min_age: int = 18                # 18+ only (Out of Scope 17)

    # --- Devconsole (found live, code audit) -------------------------------
    # factory.py's `if not cfg.is_production` gate is necessary but not
    # sufficient: "development" and "test" are both legitimate non-prod
    # FLASK_ENV values, so a box deliberately or accidentally started with
    # either, but still network-reachable, would leave devconsole wide open
    # with no login of its own. Blank password = devconsole refuses every
    # request outright (fail closed) rather than silently allowing access —
    # see app/devconsole/routes.py's before_request hook.
    devconsole_user: str = "admin"
    devconsole_password: str = ""

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def load_config() -> Config:
    # No default (found live, code audit): a silent "development" fallback
    # meant forgetting to set FLASK_ENV anywhere — a fresh deploy, a
    # container image missing the var, a copy-pasted env file with the line
    # dropped — silently ran with dev secrets, the dev JWT key, and
    # devconsole exposed, with no signal anything was wrong. Every real
    # invocation path already sets this explicitly (run.ps1 sources
    # .env.dev, tests/conftest.py sets it directly, the scheduled-job
    # wrapper sets it directly) — requiring it turns "forgot to set this
    # somewhere new" into an immediate boot failure everywhere, not a
    # silent security downgrade on whichever context happens to be real
    # production.
    env = _require("FLASK_ENV")
    if env not in _VALID_ENVS:
        raise ConfigError(
            f"FLASK_ENV={env!r} is not a recognized environment (expected one "
            f"of {sorted(_VALID_ENVS)}). Refusing to boot with an ambiguous "
            "environment, since it silently controls the entire production "
            "security posture (secrets, JWT signing key, devconsole exposure)."
        )
    is_prod = env == "production"

    if is_prod:
        secret_key = _require("SECRET_KEY")
        if len(secret_key) < 32:
            raise ConfigError("SECRET_KEY must be at least 32 characters in production")
        database_url = _require("DATABASE_URL")
        if database_url.startswith("sqlite"):
            raise ConfigError("SQLite is not permitted in production")
        redis_durable = _require("REDIS_DURABLE_URL")
        redis_cache = _require("REDIS_CACHE_URL")
        jwt_current = _require("JWT_CURRENT_KID")
        jwt_secret = _require("JWT_KEY_CURRENT")
        # Not yet _require()'d — see the field comment above.
        rag_database_url = _optional("RAG_DATABASE_URL", "")
        openrouter_api_key = _optional("OPENROUTER_API_KEY", "")
    else:
        secret_key = _optional("SECRET_KEY", "dev-only-secret-do-not-use-in-production")
        database_url = _optional(
            "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/fitness"
        )
        redis_durable = _optional("REDIS_DURABLE_URL", "redis://localhost:6379/0")
        redis_cache = _optional("REDIS_CACHE_URL", "redis://localhost:6379/1")
        jwt_current = _optional("JWT_CURRENT_KID", "dev-1")
        jwt_secret = _optional("JWT_KEY_CURRENT", "dev-jwt-signing-key-not-for-production")
        rag_database_url = _optional("RAG_DATABASE_URL", "")
        openrouter_api_key = _optional("OPENROUTER_API_KEY", "")

    # Found live (code audit): nothing enforced this file's own architectural
    # rule (STRATEGY §6) that the durable store and the evictable cache must
    # never share an instance — a copy-paste misconfiguration pointing both
    # at the same Redis would let allkeys-lru eviction silently delete a
    # revocation-denylist entry under memory pressure, making a revoked/
    # logged-out token valid again with no code-level signal anything is wrong.
    if redis_durable == redis_cache:
        raise ConfigError(
            "REDIS_DURABLE_URL and REDIS_CACHE_URL must not be the same value. "
            "The durable store (revocation denylist, rate limits) must never "
            "share an instance with the evictable cache (STRATEGY §6)."
        )

    # Normalise the postgres:// form Supabase and Heroku still emit.
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    # rag_database_url goes through plain psycopg (app/rag/vectorstore.py), never
    # SQLAlchemy, so it needs the bare postgresql:// scheme regardless of how it's
    # written in the environment.
    rag_database_url = rag_database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    # Two active keys so a key can be retired without invalidating live sessions (1.3).
    keys = {jwt_current: jwt_secret}
    prev_kid = os.environ.get("JWT_PREVIOUS_KID", "").strip()
    prev_key = os.environ.get("JWT_KEY_PREVIOUS", "").strip()
    if prev_kid and prev_key:
        keys[prev_kid] = prev_key

    return Config(
        env=env,
        debug=not is_prod,
        secret_key=secret_key,
        database_url=database_url,
        redis_durable_url=redis_durable,
        redis_cache_url=redis_cache,
        rag_database_url=rag_database_url,
        openrouter_api_key=openrouter_api_key,
        rlm_weekly_progression_enabled=_optional(
            "RLM_WEEKLY_PROGRESSION_ENABLED", "true").lower() == "true",
        rlm_chat_analysis_enabled=_optional(
            "RLM_CHAT_ANALYSIS_ENABLED", "true").lower() == "true",
        jwt_current_kid=jwt_current,
        jwt_keys=keys,
        access_token_ttl=timedelta(minutes=_int("ACCESS_TOKEN_TTL_MINUTES", 30)),
        refresh_token_ttl=timedelta(days=_int("REFRESH_TOKEN_TTL_DAYS", 30)),
        refresh_absolute_cap=timedelta(days=_int("REFRESH_ABSOLUTE_CAP_DAYS", 180)),
        refresh_grace=timedelta(seconds=_int("REFRESH_GRACE_SECONDS", 30)),
        password_min_length=_int("PASSWORD_MIN_LENGTH", 10),
        breach_check_enabled=_optional("BREACH_CHECK_ENABLED", "true").lower() == "true",
        login_lockout_threshold=_int("LOGIN_LOCKOUT_THRESHOLD", 5),
        login_lockout_base_seconds=_int("LOGIN_LOCKOUT_BASE_SECONDS", 30),
        rl_user_per_minute=_int("RL_USER_PER_MINUTE", 120),
        rl_device_per_hour=_int("RL_DEVICE_PER_HOUR", 60),
        rl_ip_per_hour=_int("RL_IP_PER_HOUR", 200),
        devconsole_user=_optional("DEVCONSOLE_USER", "admin"),
        devconsole_password=_optional("DEVCONSOLE_PASSWORD", ""),
    )
