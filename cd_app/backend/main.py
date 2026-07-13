"""FastAPI app: private companion to the doctrine engine.

Every conversation is owned by the Google-authenticated user who created it.
List, history, rename and delete all authorize against MongoDB ownership, so a
user only ever sees their own sessions (no IDOR). New conversation is the
"clear": a fresh SDK session with no prior context. Chat history is durable in
MongoDB; the SDK's on disk transcript (on a volume) is kept for resume context.

Endpoints (all require the bearer + an allowlisted Google identity):
  POST   /conversations                start a new conversation, stream first turn
  POST   /conversations/{id}/messages  continue an owned conversation, stream the turn
  GET    /conversations                list the caller's conversations
  GET    /conversations/{id}/messages  full transcript of an owned conversation
  PATCH  /conversations/{id}?title=    rename an owned conversation
  DELETE /conversations/{id}           archive (hide) an owned conversation
  GET    /healthz                      liveness (no auth)
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .agent import stream_turn
from .archive import Archive
from .auth import current_user
from .config import get_settings
from .store import ConversationStore

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("cd_app")

_store: ConversationStore | None = None
_archive: Archive | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_store() -> ConversationStore:
    assert _store is not None, "store not initialized"
    return _store


def get_archive() -> Archive:
    assert _archive is not None, "archive not initialized"
    return _archive


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _store, _archive
    # Guard the individual-use subscription path: an API key in the environment
    # would silently override the OAuth token and change billing.
    if os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is set; unset it so the subscription OAuth token is used."
        )
    settings = get_settings()  # fail fast on missing config
    _store = ConversationStore(settings.mongo_url, settings.mongo_db)
    await _store.ping()
    await _store.ensure_indexes()
    _archive = Archive(settings.archive_dir)
    log.info("cd_app backend ready")
    yield
    _store.close()


app = FastAPI(title="Christian Doctrine", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    body = b""
    try:
        body = await request.body()
    except Exception:
        pass
    log.warning("422 on %s %s: %s | body=%s", request.method, request.url.path,
                exc.errors(), body[:400])
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        content={"detail": exc.errors()})


class NewConversation(BaseModel):
    prompt: str = Field(min_length=1, max_length=32000)
    title: str | None = Field(default=None, max_length=80)


class Message(BaseModel):
    prompt: str = Field(min_length=1, max_length=32000)


async def _require_owner(session_id: str, user: str) -> None:
    owner = await get_store().owner_of(session_id)
    # 404 (not 403) so a caller cannot probe which session ids exist.
    if owner is None or owner != user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")


def _stream(prompt: str, *, user: str, resume: str | None, title: str | None) -> StreamingResponse:
    settings = get_settings()
    return StreamingResponse(
        stream_turn(
            settings,
            prompt,
            owner=user,
            store=get_store(),
            now=_now(),
            resume=resume,
            title=title,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/conversations")
async def new_conversation(
    body: NewConversation, user: str = Depends(current_user)
) -> StreamingResponse:
    return _stream(body.prompt, user=user, resume=None, title=body.title)


@app.post("/conversations/{session_id}/messages")
async def send_message(
    session_id: str, body: Message, user: str = Depends(current_user)
) -> StreamingResponse:
    await _require_owner(session_id, user)
    return _stream(body.prompt, user=user, resume=session_id, title=None)


@app.get("/conversations")
async def get_conversations(user: str = Depends(current_user)) -> dict[str, object]:
    return {"conversations": await get_store().list_for(user)}


@app.get("/conversations/{session_id}/messages")
async def get_history(session_id: str, user: str = Depends(current_user)) -> dict[str, object]:
    await _require_owner(session_id, user)
    return {"messages": await get_store().get_messages(session_id)}


@app.patch("/conversations/{session_id}")
async def rename(
    session_id: str, title: str, user: str = Depends(current_user)
) -> dict[str, str]:
    await _require_owner(session_id, user)
    if not title.strip() or len(title) > 200:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid title")
    await get_store().set_title(session_id, title)
    return {"status": "ok"}


@app.delete("/conversations/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(session_id: str, user: str = Depends(current_user)) -> None:
    await _require_owner(session_id, user)
    await get_store().archive(session_id)


# --- Doctrine PDF archive (gated) ---------------------------------------------
@app.get("/archive")
async def archive_list(_user: str = Depends(current_user)) -> dict[str, object]:
    return {"documents": get_archive().list()}


@app.get("/archive/{doc_id}")
async def archive_get(doc_id: str, _user: str = Depends(current_user)) -> FileResponse:
    path = get_archive().path_for(doc_id)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return FileResponse(path, media_type="application/pdf", filename=f"{doc_id}.pdf")
