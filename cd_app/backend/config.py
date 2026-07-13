"""Backend settings.

All configuration is environment driven (prefix ``CD_APP_``) and can live in a
local ``.env`` file. Nothing here is an Anthropic API key: authentication is the
subscription OAuth token produced by ``claude setup-token``. Keeping this token
individual to the owner is what keeps the deployment inside Anthropic's
individual-use terms.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CD_APP_", env_file=".env", extra="ignore"
    )

    # Claude subscription auth. Optional: if empty, the Agent SDK falls back to
    # the Claude Code CLI credentials mounted at ~/.claude (the VPS is already
    # logged in). Otherwise set a `claude setup-token` OAuth token here. This is
    # NOT an ANTHROPIC_API_KEY. The two must never both be set.
    claude_code_oauth_token: str = ""

    # Google Sign-In. Accept only tokens minted for our own OAuth client(s),
    # and only for emails on the allowlist (all the owner's own accounts).
    google_client_ids: str = Field(..., description="Comma separated OAuth client IDs")
    allowed_emails: str = Field(..., description="Comma separated allowlisted emails")

    # Secondary shared secret checked before the Google identity (defence in depth).
    app_bearer_token: str = Field(..., min_length=32)

    # Doctrine engine (cd_mcp) served over streamable HTTP on the same host.
    mcp_url: str = "http://127.0.0.1:8765/mcp"
    mcp_server_name: str = "christian-doctrine"

    # Working directory for the agent. Set to the repo root so read only tools
    # can reach the data stores, and so sessions are grouped under one project.
    engine_cwd: str = "."

    # MongoDB for the conversation index + durable chat history.
    mongo_url: str = "mongodb://127.0.0.1:27017"
    mongo_db: str = "christian_doctrine"

    # Directory of generated doctrine PDFs (mounted into the container).
    archive_dir: str = "/archive"

    # Optional model override (defaults to the account's Claude Code default).
    model: str | None = None

    @property
    def google_client_id_list(self) -> tuple[str, ...]:
        return tuple(x.strip() for x in self.google_client_ids.split(",") if x.strip())

    @property
    def allowed_email_set(self) -> frozenset[str]:
        return frozenset(
            x.strip().lower() for x in self.allowed_emails.split(",") if x.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
