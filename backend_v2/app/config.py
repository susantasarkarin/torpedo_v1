"""
Centrally-declared configuration — the single place database/org topology is decided.

Closes D-16 (one env var silently relocating ~40 v1 collections between databases,
because `db_pools.py` and half a dozen modules each had their own default) and D-21
(runtime-selected databases: an import-time connection probe choosing between two
databases, a FastAPI dependency accidentally exposing `db_name` as a caller-supplied
query parameter, phantom databases created by passing a collection name where a
database name was expected).

The rule this module exists to enforce: there is exactly one `MONGO_DB_NAME`, read once,
here. No other module in this codebase may read `os.environ` for a database name, accept
one as a function parameter with a default, or construct one at runtime. If a future
module needs a different *collection*, it takes the shared `Settings` and picks a
collection name — never a different database.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_uri: str
    mongo_db_name: str

    # Default org for the current single-tenant deployment. Every canonical document
    # still carries `org_id` (schema_catalogue.md §0) even though there is only one
    # today — retrofitting tenancy later is what v1 never did and paid for (D-19/D-22).
    default_org_id: str = "torpedo"

    environment: str = "development"

    # HMAC secret for verifying inbound survey-provider outcome callbacks
    # (app.panel.callback_security — the D-08 fix). No default: an unset secret must
    # fail closed (SignatureConfigError), never silently skip verification (D-23's
    # failure mode) — see that module's docstring.
    survey_callback_signing_secret: str | None = None

    # HMAC secret for the Phase 14 scheduler tick endpoint (app.scheduler.routers)
    # — a systemd timer calls it, not a logged-in user, so it's authenticated the
    # same way the survey callback above is: fails closed (SignatureConfigError)
    # on an unset secret, never a silent skip.
    scheduler_signing_secret: str | None = None

    # Phase 14 continued — the AI Gateway activation safety gate. Defaults to
    # True: a newly-activated inference backend (a real GPU/model, not the
    # test double every unit test still uses) must be watched making
    # decisions against real business events before it's trusted to actually
    # send an email, allocate a real panelist, pause/close a survey, or
    # record a payment match. Every AiProposal is still created and recorded
    # in shadow mode — decision-making itself never changes — only the
    # governed-service execution each of those five decision points would
    # otherwise trigger is suppressed. Flip to False only after the shadow-mode
    # validation phase (docs/AI_NATIVE_COMPLETION_CHECKLIST.md) is complete.
    ai_shadow_mode: bool = True

    # Real SMTP transport for app.outreach.smtp_provider.SmtpSendProvider
    # (Slice 21) — one globally configured relay, not yet a per-Mailbox
    # credential store (Mailbox.credentials_id is accepted by the SendProvider
    # Protocol but not yet resolved against anything real). An unset host/
    # username/password means SmtpSendProvider fails loud on every send
    # attempt (SendProviderUnavailable), never a silent stub success.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None


@lru_cache
def get_settings() -> Settings:
    """
    Cached — Settings is read from the environment exactly once per process, not
    re-read per request. A `.env` change requires a restart, deliberately: a live
    topology change should never be silent (that silence is exactly what D-16 was).
    """
    return Settings()
