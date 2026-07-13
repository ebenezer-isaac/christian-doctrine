"""Tests for cd_mcp.streaming."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from cd_mcp.streaming import emit_progress


class _RecordingSession:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def send_progress_notification(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


def _server_with_session(session: _RecordingSession) -> Any:
    return SimpleNamespace(request_context=SimpleNamespace(session=session))


def test_no_progress_token_is_noop() -> None:
    session = _RecordingSession()
    server = _server_with_session(session)
    asyncio.run(emit_progress(server, None, progress=0.5))
    assert session.events == []


def test_with_token_emits_notification() -> None:
    session = _RecordingSession()
    server = _server_with_session(session)
    asyncio.run(
        emit_progress(server, "tok-123", progress=0.4, total=1.0, message="cultural-retrieval")
    )
    assert len(session.events) == 1
    e = session.events[0]
    assert e["progress_token"] == "tok-123"
    assert e["progress"] == 0.4
    assert e["message"] == "cultural-retrieval"


def test_server_without_session_is_safe() -> None:
    server = SimpleNamespace()
    asyncio.run(emit_progress(server, "tok", progress=0.1))


def test_three_stage_progress_in_order() -> None:
    session = _RecordingSession()
    server = _server_with_session(session)

    async def stages() -> None:
        await emit_progress(server, "t", 0.15, 1.0, "lexical-retrieval")
        await emit_progress(server, "t", 0.45, 1.0, "cultural-retrieval")
        await emit_progress(server, "t", 0.85, 1.0, "synthesis")

    asyncio.run(stages())
    msgs = [e["message"] for e in session.events]
    assert msgs == ["lexical-retrieval", "cultural-retrieval", "synthesis"]
    fractions = [e["progress"] for e in session.events]
    assert 0.0 <= fractions[0] <= 0.3
    assert 0.3 <= fractions[1] <= 0.6
    assert 0.6 <= fractions[2] <= 1.0
