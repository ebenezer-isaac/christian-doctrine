"""Tests for the live lexical-store session factory (Pipeline 3, Step C).

Two layers:

  - Hermetic checks on the session-factory module (``bd_mcp/live/lexical.py``)
    that need no Docker: settings resolution, the air-gap invariant (no cultural
    or historical URI ever surfaces), and graceful fail-soft on an unreachable
    store.
  - Live tests that open the real lexical Neo4j (``NEO4J_LEXICAL_URI``, default
    ``bolt://localhost:7688``) and drive each of the wired lexical handlers,
    asserting REAL data (theos for G2316, real concordance occurrences, real
    OpenBible cross-ref votes, the original Greek/Hebrew verse text). They SKIP
    cleanly when the store is unreachable, mirroring the skip-when-asset-absent
    pattern the CBGM PoC coverage test uses.

The handlers under test stay pure: each ``handle()`` takes the live session as
``neo4j_session`` and never opens a connection itself. The lexical layer touches
the lexical store ONLY.
"""

from __future__ import annotations

import unicodedata

import pytest

from bd_mcp.live import lexical
from bd_mcp.live.lexical import (
    LexicalSettings,
    build_lexical_settings,
    lexical_session,
    lexical_store_reachable,
)
from bd_mcp.tools.concordance_walk import ConcordanceWalkInput
from bd_mcp.tools.concordance_walk import handle as concordance_handle
from bd_mcp.tools.cross_ref import CrossRefInput
from bd_mcp.tools.cross_ref import handle as cross_ref_handle
from bd_mcp.tools.lexical_lookup import LexicalLookupInput
from bd_mcp.tools.lexical_lookup import handle as lexical_lookup_handle
from bd_mcp.tools.parallel_translation import ParallelTranslationInput
from bd_mcp.tools.parallel_translation import handle as parallel_translation_handle


def _base_letters(text: str) -> str:
    """Strip combining marks (accents, cantillation, niqqud) for robust compare.

    The store stores accented Greek with the oxia codepoint and pointed Hebrew
    with cantillation, which differ from naive precomposed literals. Comparing on
    the base consonant/vowel letters keeps the assertion about the lexeme, not
    the exact diacritic encoding.
    """
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


# --------------------------------------------------------------------------
# Hermetic: settings + air-gap + fail-soft (no Docker needed)
# --------------------------------------------------------------------------


def test_build_lexical_settings_passthrough() -> None:
    s = LexicalSettings(
        neo4j_lexical_uri="bolt://x:7688",
        neo4j_lexical_user="neo4j",
        neo4j_lexical_password="pw",
    )
    assert build_lexical_settings(s) is s


def test_build_lexical_settings_loads_from_env() -> None:
    s = build_lexical_settings(None)
    assert isinstance(s, LexicalSettings)
    assert s.neo4j_lexical_uri.startswith("bolt://")


def test_settings_never_expose_cultural_or_historical_uri() -> None:
    # Air-gap at the config boundary: the lexical settings object must carry no
    # cultural / historical URI attribute. The only Neo4j URI it knows is lexical.
    s = build_lexical_settings(None)
    assert not hasattr(s, "neo4j_cultural_uri")
    assert not hasattr(s, "neo4j_historical_uri")
    assert not hasattr(s, "qdrant_cultural_url")
    assert "7689" not in s.neo4j_lexical_uri
    assert "7101" not in s.neo4j_lexical_uri


def test_lexical_uri_points_at_lexical_port() -> None:
    s = build_lexical_settings(None)
    # The lexical bolt port is 7688 in this deployment; never the cultural 7689.
    assert "7689" not in s.neo4j_lexical_uri


def test_store_reachable_false_on_bad_uri_does_not_raise() -> None:
    s = LexicalSettings(
        neo4j_lexical_uri="bolt://127.0.0.1:6553",  # nothing listens here
        neo4j_lexical_user="neo4j",
        neo4j_lexical_password="nope",
    )
    # Must return a bool and never raise, so the live tests can skip cleanly.
    assert lexical_store_reachable(s) is False


# --------------------------------------------------------------------------
# Live: hit the real lexical store, assert real data, skip when down
# --------------------------------------------------------------------------


_REACHABLE = lexical_store_reachable()
_REASON = "lexical Neo4j unreachable (bolt://localhost:7688 stack not up)"
_live = pytest.mark.skipif(not _REACHABLE, reason=_REASON)


@_live
def test_live_lexical_lookup_strong_g2316_is_theos() -> None:
    with lexical_session() as session:
        env = lexical_lookup_handle(
            LexicalLookupInput(query="G2316", lang="gk", id_type="strong"),
            neo4j_session=session,
        )
    assert env["ok"] is True
    matches = env["result"]["matches"]
    assert matches, "G2316 must resolve in the live lexical store"
    top = matches[0]
    assert top["strong"] == "G2316"
    # Compare on base letters: the store uses the oxia accent codepoint.
    assert _base_letters(top["lemma"]) == _base_letters("θεός")
    assert top["transliteration"] == "theos"
    assert top["gloss"] and "God" in top["gloss"]
    # theos occurs over a thousand times in the NT; assert a real, non-trivial count.
    assert isinstance(top["occurrences_in_canon"], int)
    assert top["occurrences_in_canon"] > 1000


@_live
def test_live_lexical_lookup_strong_hebrew_h0430_is_elohim() -> None:
    with lexical_session() as session:
        env = lexical_lookup_handle(
            LexicalLookupInput(query="H0430", lang="hb", id_type="strong"),
            neo4j_session=session,
        )
    matches = env["result"]["matches"]
    assert matches
    top = matches[0]
    assert top["strong"] == "H0430"
    assert "אלהים" in _base_letters(top["lemma"] or "")
    # Elohim is attested thousands of times in the Hebrew Bible.
    assert top["occurrences_in_canon"] > 2000


@_live
def test_live_lexical_lookup_by_lemma_resolves_strong() -> None:
    with lexical_session() as session:
        env = lexical_lookup_handle(
            LexicalLookupInput(query="θεός", lang="gk", id_type="lemma"),
            neo4j_session=session,
        )
    matches = env["result"]["matches"]
    assert matches and matches[0]["strong"] == "G2316"


@_live
def test_live_lexical_lookup_by_gloss_returns_matches() -> None:
    with lexical_session() as session:
        env = lexical_lookup_handle(
            LexicalLookupInput(query="God", lang="gk", id_type="gloss", limit=5),
            neo4j_session=session,
        )
    matches = env["result"]["matches"]
    assert matches, "a gloss search for God must return lexical entries"
    assert all(m["strong"] for m in matches)


@_live
def test_live_concordance_walk_greek_strong_real_occurrences() -> None:
    with lexical_session() as session:
        env = concordance_handle(
            ConcordanceWalkInput(strong="G2316", limit=50),
            neo4j_session=session,
        )
    occ = env["result"]["occurrences"]
    assert occ, "theos must have real occurrences"
    for o in occ:
        assert o["ref"] and "." in o["ref"]
        assert o["surface"]
        assert o["morph"].startswith("G2316")


@_live
def test_live_concordance_walk_filter_book_john() -> None:
    with lexical_session() as session:
        env = concordance_handle(
            ConcordanceWalkInput(strong="G2316", filter_book=["John"], limit=2000),
            neo4j_session=session,
        )
    occ = env["result"]["occurrences"]
    assert occ, "theos occurs in John"
    assert all(o["ref"].startswith("John.") for o in occ)


@_live
def test_live_concordance_walk_hebrew_strong() -> None:
    with lexical_session() as session:
        env = concordance_handle(
            ConcordanceWalkInput(strong="H0430", limit=20),
            neo4j_session=session,
        )
    occ = env["result"]["occurrences"]
    assert occ, "Elohim must have real OSHB occurrences"
    assert all(o["surface"] for o in occ)


@_live
def test_live_cross_ref_openbible_has_real_votes() -> None:
    with lexical_session() as session:
        env = cross_ref_handle(
            CrossRefInput(ref="John.3.16", limit=10),
            neo4j_session=session,
        )
    edges = env["result"]["edges"]
    assert edges, "John.3.16 must have cross references"
    ob = [e for e in edges if e["source"] == "openbible"]
    assert ob, "OpenBible cross refs must be present"
    # Real vote weights, not the votes=1 default the old TSK-only cypher gave.
    assert any(e["votes"] > 1 for e in ob)
    # Ordered by votes descending.
    votes = [e["votes"] for e in edges]
    assert votes == sorted(votes, reverse=True)


@_live
def test_live_cross_ref_min_votes_filter() -> None:
    with lexical_session() as session:
        env = cross_ref_handle(
            CrossRefInput(ref="John.3.16", min_votes=300, limit=50),
            neo4j_session=session,
        )
    edges = env["result"]["edges"]
    assert edges
    assert all(e["votes"] >= 300 for e in edges)


@_live
def test_live_parallel_translation_original_greek_john_1_1() -> None:
    with lexical_session() as session:
        env = parallel_translation_handle(
            ParallelTranslationInput(ref="John.1.1", translations=["ESV"], include_original=True),
            neo4j_session=session,
        )
    rows = env["result"]["rows"]
    original = [r for r in rows if r["translation"] == "original"]
    assert original, "the original Greek must be returned"
    base = _base_letters(original[0]["text"])
    assert "λογος" in base and "θε" in base
    assert original[0]["lang"] == "gk"


@_live
def test_live_parallel_translation_original_hebrew_gen_1_1() -> None:
    with lexical_session() as session:
        env = parallel_translation_handle(
            ParallelTranslationInput(ref="Gen.1.1", translations=["ESV"], include_original=True),
            neo4j_session=session,
        )
    rows = env["result"]["rows"]
    original = [r for r in rows if r["translation"] == "original"]
    assert original
    # Compare on base consonants: the verse text carries cantillation marks.
    assert "אלהים" in _base_letters(original[0]["text"])
    assert original[0]["lang"] == "hb"


@_live
def test_live_air_gap_session_targets_lexical_uri_only() -> None:
    # The session factory resolves only the lexical URI. Confirm the live driver
    # we open is bound to the lexical bolt endpoint and never the cultural one.
    s = build_lexical_settings(None)
    assert "7689" not in s.neo4j_lexical_uri
    assert lexical.lexical_store_reachable(s) is True
