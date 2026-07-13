"""Progress notification helper for long-running MCP tools.

Used by doctrinal_verdict to surface stage progress through progressToken.
"""

from __future__ import annotations

from typing import Any


async def emit_progress(
    server: Any,
    progress_token: str | None,
    progress: float,
    total: float = 1.0,
    message: str = "",
) -> None:
    """Send a notifications/progress event keyed by progress_token.

    No-op when progress_token is None. The server must expose either
    `request_context.session.send_progress_notification` (FastMCP) or a similar
    coroutine; we look both up and fall back to a no-op if neither exists.
    """
    if progress_token is None:
        return
    notifier = _resolve_notifier(server)
    if notifier is None:
        return
    await notifier(
        progress_token=progress_token,
        progress=progress,
        total=total,
        message=message,
    )


def _resolve_notifier(server: Any) -> Any | None:
    ctx = getattr(server, "request_context", None)
    if ctx is None:
        return None
    session = getattr(ctx, "session", None)
    if session is None:
        return None
    return getattr(session, "send_progress_notification", None)
