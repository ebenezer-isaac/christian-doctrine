"""Live lexical-store connection helpers for the Pipeline 3 MCP tools.

The four store-backed lexical handlers (lexical_lookup, concordance_walk,
cross_ref, parallel_translation) are pure: each ``handle()`` takes an optional
``neo4j_session`` (any object exposing ``.run(cypher, **params)`` that yields
records the handler indexes by key) and never opens a connection itself. The
server opens the driver once in its lifespan (``cd_mcp/runtime.py``) and hands a
session to each handler per request. This module builds that driver and session
against the running lexical Neo4j (``bolt://localhost:7688`` by default).

Query-time air-gap: this module connects to the lexical store ONLY. It never
references the cultural or historical store URIs (``:7689`` / ``:7101``). The
cultural side is owned by ``cd_mcp/live/cultural.py``.

The handlers carry the Cypher; the real graph schema they target is documented
in ``pipeline2/context_builder.py`` and confirmed live (see the module-level
notes on each handler). This file only opens the connection and hands back a
session object whose ``.run`` returns Neo4j ``Record`` objects (which support
both ``rec["key"]`` and ``dict(rec)`` access, matching the handler contracts).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress

from neo4j import Driver, GraphDatabase, Session
from pydantic_settings import BaseSettings, SettingsConfigDict


class LexicalSettings(BaseSettings):
    """Connection settings for the lexical Neo4j store.

    Reads the same ``.env`` keys Pipeline 1/2 use (``NEO4J_LEXICAL_*``) so the
    live MCP path shares one source of truth for credentials. Never holds a
    cultural or historical URI.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    neo4j_lexical_uri: str = "bolt://localhost:7688"
    neo4j_lexical_user: str = "neo4j"
    neo4j_lexical_password: str = ""


def build_lexical_settings(settings: LexicalSettings | None = None) -> LexicalSettings:
    """Return the given settings or load them from the environment.

    Kept tiny and immutable: callers that already hold a settings object pass it
    through; everyone else gets a fresh env-driven instance.
    """
    if settings is not None:
        return settings
    return LexicalSettings()  # type: ignore[call-arg]


def lexical_driver(settings: LexicalSettings | None = None) -> Driver:
    """Open a Neo4j driver pointed at the lexical store.

    The caller owns the returned driver and must ``close()`` it. Prefer
    ``lexical_session()`` which manages both the driver and the session.
    """
    cfg = build_lexical_settings(settings)
    return GraphDatabase.driver(
        cfg.neo4j_lexical_uri,
        auth=(cfg.neo4j_lexical_user, cfg.neo4j_lexical_password),
    )


@contextmanager
def lexical_session(settings: LexicalSettings | None = None) -> Iterator[Session]:
    """Yield a live lexical Neo4j session, closing the driver on exit.

    Usage::

        with lexical_session() as session:
            env = lexical_lookup.handle(payload, neo4j_session=session)

    The yielded ``Session`` is exactly the object the handlers expect for their
    ``neo4j_session`` argument: its ``.run(cypher, **params)`` returns an
    iterable of Neo4j ``Record`` objects, each indexable by the result aliases
    the handler reads (``rec["l"]``, ``rec["ref"]``, ``rec["from_ref"]``, ...).
    """
    driver = lexical_driver(settings)
    try:
        with driver.session() as session:
            yield session
    finally:
        driver.close()


def lexical_store_reachable(settings: LexicalSettings | None = None) -> bool:
    """Best-effort liveness probe for the lexical store.

    Returns ``True`` only when a driver opens and ``verify_connectivity()``
    succeeds. Swallows every connection error and returns ``False`` so callers
    (and the live test suite) can skip cleanly when the Docker stack is down.
    This mirrors the asset-absent skip pattern used by the lexical coverage
    tests. It never raises.
    """
    driver: Driver | None = None
    try:
        driver = lexical_driver(settings)
        driver.verify_connectivity()
        return True
    except Exception:
        return False
    finally:
        if driver is not None:
            with suppress(Exception):
                driver.close()
