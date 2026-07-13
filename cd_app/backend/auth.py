"""Two layer request auth.

1. A shared bearer token (constant time compared) gates every request. It keeps
   anonymous internet traffic off the endpoint before any Google work happens.
2. A Google ID token identifies the user. It must be minted for one of our own
   OAuth client IDs and resolve to an allowlisted email. Only the owner's own
   accounts are allowlisted, so the deployment stays single user.

The verified email is returned and threaded through handlers as the caller.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from .config import Settings, get_settings

_GOOGLE_REQUEST = google_requests.Request()


def _check_bearer(authorization: str | None, settings: Settings) -> None:
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    presented = authorization[len(prefix) :]
    # Compare as bytes: a non-ASCII header would make str compare_digest raise
    # TypeError (a 500, and a timing/behavior oracle) instead of a clean 401.
    if not secrets.compare_digest(presented.encode(), settings.app_bearer_token.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bearer token")


def _verify_google(id_token_value: str | None, settings: Settings) -> str:
    if not id_token_value:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing Google ID token")
    try:
        claims = google_id_token.verify_oauth2_token(
            id_token_value, _GOOGLE_REQUEST
        )
    except ValueError:
        # Covers bad signature, expiry, malformed token.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Google ID token") from None

    if claims.get("aud") not in settings.google_client_id_list:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Untrusted client")
    if claims.get("email_verified") is not True:  # require a real boolean true
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Email not verified")
    email = str(claims.get("email", "")).lower()
    if email not in settings.allowed_email_set:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account not allowlisted")
    return email


async def current_user(
    authorization: str | None = Header(default=None),
    x_google_id_token: str | None = Header(default=None),
) -> str:
    """FastAPI dependency. Returns the verified, allowlisted email or raises."""
    settings = get_settings()
    _check_bearer(authorization, settings)
    return _verify_google(x_google_id_token, settings)
