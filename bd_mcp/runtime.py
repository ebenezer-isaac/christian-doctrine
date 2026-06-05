"""Server runtime: the FastMCP lifespan and the Context accessors tools use.

Store connections are opened once when the server starts and closed when it
stops (the FastMCP lifespan pattern), then reached by each tool through the
injected Context. Tools never construct connections themselves and the server
needs no external wiring to be fully functional: ``python -m bd_mcp.server``
serves all tools live.

The query-time air-gap is structural here: the lexical driver reaches only the
lexical store, and the cultural clients reach only the cultural store. Every
store is optional and fail-soft: if one is unreachable at startup its handle is
None and the tools that use it degrade to an empty result.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from bd_mcp.live.cultural import build_cultural_clients, retrieve_cultural_chunks
from bd_mcp.live.lexical import lexical_driver
from ingest.versification_mapper import VersificationMapper


@dataclass(frozen=True)
class AppContext:
    """Live resources shared across requests, held for the server's lifetime."""

    lexical_driver: Any | None
    cult_qdrant: Any | None
    voyage: Any | None
    mapper: VersificationMapper


@asynccontextmanager
async def lifespan(_server: Any) -> AsyncIterator[AppContext]:
    """Open the live store connections on startup, close them on shutdown."""
    driver: Any | None = None
    with contextlib.suppress(Exception):
        driver = lexical_driver()
    cult_qdrant, voyage = build_cultural_clients()
    try:
        yield AppContext(
            lexical_driver=driver,
            cult_qdrant=cult_qdrant,
            voyage=voyage,
            mapper=VersificationMapper(),
        )
    finally:
        if driver is not None:
            with contextlib.suppress(Exception):
                driver.close()
        if cult_qdrant is not None:
            with contextlib.suppress(Exception):
                cult_qdrant.close()


def app_context(ctx: Any) -> AppContext:
    """The AppContext for the current request."""
    return ctx.request_context.lifespan_context


@contextlib.contextmanager
def lexical_session(ctx: Any) -> Iterator[Any | None]:
    """Yield a lexical Neo4j session, or None when the lexical store is absent."""
    app = app_context(ctx)
    if app.lexical_driver is None:
        yield None
        return
    session = app.lexical_driver.session()
    try:
        yield session
    finally:
        with contextlib.suppress(Exception):
            session.close()


def cultural_chunks(ctx: Any, **kwargs: Any) -> list[dict[str, Any]]:
    """Retrieve cultural chunks using the lifespan-held cultural clients.

    Diagnostic and fail-soft: any retrieval failure yields an empty list.
    """
    app = app_context(ctx)
    try:
        return retrieve_cultural_chunks(
            qdrant_client=app.cult_qdrant, voyage_client=app.voyage, **kwargs
        )
    except Exception:  # noqa: BLE001  cultural overlay is diagnostic, degrade to empty
        return []
