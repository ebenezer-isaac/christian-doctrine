"""open-cbgm 3 John adapter coverage tests (phase C.2 verifier).

This file references tools/predicates_by_type.cypher for $pred_string,
$pred_int, $pred_bool definitions. Predicate semantics are loaded at module
level from that file and used to assert property types on captured node
payloads.

TDD red-state contract:
  The adapter at ingest/lexical/open_cbgm_3_john.py has NO function body at
  this commit. Every test that calls ingest_open_cbgm_3_john() MUST fail
  because getattr returns None and calling None raises AttributeError or
  TypeError. That failure IS the red state the Wave 2 orchestrator gate
  requires.

Entry function:
  - ingest/lexical/open_cbgm_3_john.py: docstring-only, no def at this commit
  - Expected function name: ingest_open_cbgm_3_john
  - Adapter module: ingest.lexical.open_cbgm_3_john

Random seed:
  commit_sha = '23c42ecd3fce242a35e9e09cc62a530ea345c22c'
    (git log -1 -- ingest/lexical/open_cbgm_3_john.py)
  seed = int('23c42ecd', 16) = 600059597

Fixture: tests/lexical/fixtures/open_cbgm_3_john_slice.json
  3 variant units across 3John.1.1-1.15.
  Covers lacuna sentinel readings, corrector hands, and single-reading units.

Source: tools/expected_counts.json sources."open-cbgm-3-john"
  expected_count=728, tier B, tolerance_relative=0.02, min=700, max=760,
  record_unit cbgm_node (node-only: 142 Witness + 116 VariantUnit + 470
  Reading = 728 per docs/PHASE_D_CATALOG_RECONCILIATION.md section 6;
  the prior 600/588/612 with record_unit cbgm_record was a hand-set
  estimate that never modeled the by-design lacuna back-fill).
Decisions: 6 (CBGM Witness/Variant/Reading shape), 14 (Source node + license).
"""

from __future__ import annotations

import importlib
import json
import random
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# -- predicates_by_type.cypher (tools/predicates_by_type.cypher) ------------
# Loaded at module level. Inline predicate definitions are forbidden
# by RESEED_PLAN C.5; use the canonical file only.
_PREDICATES_CYPHER_PATH = REPO / "tools" / "predicates_by_type.cypher"
_PREDICATES_RAW = _PREDICATES_CYPHER_PATH.read_text(encoding="utf-8")


def _load_predicates(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("$pred_") and ":=" in line:
            lhs, rhs = line.split(":=", 1)
            name = lhs.strip().split("$pred_")[1].split("(")[0]
            result[name] = rhs.strip()
    return result


PREDICATES = _load_predicates(_PREDICATES_RAW)

# -- adapter constants -------------------------------------------------------
ADAPTER_MODULE = "ingest.lexical.open_cbgm_3_john"
ENTRY_FUNCTION = "ingest_open_cbgm_3_john"

REQUIRED_LABELS = frozenset({"Witness", "VariantUnit", "Reading", "Source"})
REQUIRED_EDGES = frozenset({"READS_AT", "ATTESTED_BY", "CORRECTOR_OF"})

EXPECTED_COUNT = 728  # Tier B, record_unit cbgm_node (node-only), per expected_counts.json
EXPECTED_MIN = 700
EXPECTED_MAX = 760

# Seed from open_cbgm_3_john.py docstring commit SHA
DOCSTRING_COMMIT_SHA = "23c42ecd3fce242a35e9e09cc62a530ea345c22c"
SEED_INT = int(DOCSTRING_COMMIT_SHA[:8], 16)  # = 600059597


# -- FakeDriver that records every node/edge the adapter emits ---------------

class FakeDriver:
    """Minimal Neo4j driver stand-in.

    Captures every MERGE payload so tests can assert on emitted labels,
    edge types, and node property formats without touching a live graph.

    When the adapter body is absent (Wave 2 red state) the driver is never
    reached because calling ingest_open_cbgm_3_john() raises AttributeError
    or TypeError first.
    """

    def __init__(self) -> None:
        self._nodes: list[dict[str, Any]] = []
        self._edges: list[dict[str, Any]] = []
        self.settings = _FakeSettings()

    def session(self, *_: Any, **__: Any) -> "_FakeSession":
        return _FakeSession(self)

    def close(self) -> None:
        pass

    def captured_labels(self) -> set[str]:
        return {n["label"] for n in self._nodes}

    def captured_node_ids(self, label: str) -> list[str]:
        return [n["id"] for n in self._nodes if n["label"] == label and "id" in n]

    def captured_node_slugs(self, label: str) -> list[str]:
        return [n["slug"] for n in self._nodes if n["label"] == label and "slug" in n]

    def captured_edge_types(self) -> set[str]:
        return {e["rel_type"] for e in self._edges}

    def node_count(self, label: str) -> int:
        return sum(1 for n in self._nodes if n["label"] == label)

    def edge_count(self, rel_type: str) -> int:
        return sum(1 for e in self._edges if e["rel_type"] == rel_type)

    def nodes_for_label(self, label: str) -> list[dict[str, Any]]:
        return [n for n in self._nodes if n["label"] == label]

    def edges_for_type(self, rel_type: str) -> list[dict[str, Any]]:
        return [e for e in self._edges if e["rel_type"] == rel_type]


class _FakeSettings:
    """Minimal settings stub. Real Settings requires env vars."""

    neo4j_lexical_uri: str = "bolt://localhost:7687"
    neo4j_lexical_user: str = "neo4j"
    neo4j_lexical_password: str = "test"
    qdrant_lexical_url: str = "http://localhost:6333"
    voyage_api_key: str = ""


class _FakeSession:
    def __init__(self, driver: FakeDriver) -> None:
        self._driver = driver

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def run(self, cypher: str, **kwargs: Any) -> Any:
        _parse_cypher_into_driver(cypher, kwargs, self._driver)
        return _FakeResult()

    def close(self) -> None:
        pass


class _FakeResult:
    def single(self) -> dict[str, int]:
        return {"upserted": 1, "edges": 1}

    def consume(self) -> None:
        pass


def _parse_cypher_into_driver(
    cypher: str, params: dict[str, Any], driver: FakeDriver
) -> None:
    """Best-effort parse of MERGE Cypher statements into FakeDriver records.

    The adapter is expected to issue MERGE statements for Witness, VariantUnit,
    Reading, and Source nodes, and READS_AT, ATTESTED_BY, CORRECTOR_OF edges.
    This parser records what it sees; a docstring-only adapter produces no
    calls at all.
    """
    # Node MERGE patterns
    for label in ("Witness", "VariantUnit", "Reading", "Source"):
        # Phase D label-add reconciliation: only a node-MERGE statement
        # ("MERGE (n:") may contribute node records. Post-Phase-D edge-MERGE
        # Cypher carries endpoint labels in its MATCH clause; without this
        # guard its edge-batch rows (from_id/to_id, no node identity) would
        # be recorded as phantom nodes. Real node MERGEs always contain
        # "MERGE (n:" so genuine node capture is byte-identical; the edge
        # loop is untouched.
        if "MERGE (n:" not in cypher:
            continue
        if (
            f":`{label}`" in cypher
            or f"(n:{label}" in cypher
            or f":{label} " in cypher
            or f":{label})" in cypher
            or f":{label}{{" in cypher
        ):
            rows_param = params.get("rows") or params.get("records") or []
            if isinstance(rows_param, list):
                for row in rows_param:
                    node: dict[str, Any] = {"label": label}
                    node.update(row if isinstance(row, dict) else {})
                    driver._nodes.append(node)
            else:
                driver._nodes.append({"label": label})

    # Edge MERGE patterns
    for rel_type in ("READS_AT", "ATTESTED_BY", "CORRECTOR_OF"):
        if (
            f"`{rel_type}`" in cypher
            or f":{rel_type}]" in cypher
            or f":{rel_type}" in cypher
        ):
            rows_param = params.get("rows") or params.get("records") or [{}]
            count = len(rows_param) if isinstance(rows_param, list) else 1
            for row in (rows_param if isinstance(rows_param, list) else [{}]):
                edge_rec: dict[str, Any] = {"rel_type": rel_type}
                if isinstance(row, dict):
                    edge_rec.update(row)
                driver._edges.append(edge_rec)


# -- fixtures ----------------------------------------------------------------

@pytest.fixture()
def fake_driver() -> FakeDriver:
    return FakeDriver()


@pytest.fixture()
def fixture_slice() -> dict[str, Any]:
    p = REPO / "tests" / "lexical" / "fixtures" / "open_cbgm_3_john_slice.json"
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def source_root() -> Path:
    """Return the CBGM asset directory root (tmp/poc/cbgm).

    Skip the dependent tests when the local PoC asset is absent. The open-cbgm
    collation XML is a gitignored procurement artifact (tmp/ is not tracked), so
    a checkout without it cannot re-run the ingest parse. This mirrors how the
    store-gated tests skip when a Docker stack is down: the live lexical store
    and the standing trust gate (tools/verify_manifest.py) remain the
    authoritative proof of the ingested CBGM data.
    """
    root = REPO / "tmp" / "poc" / "cbgm"
    if not (root / "3_john_collation.xml").exists():
        pytest.skip("CBGM PoC asset tmp/poc/cbgm/3_john_collation.xml not present")
    return root


# ---------------------------------------------------------------------------
# GROUP 1: entry-function tests (WILL FAIL at Wave 2 - red state)
# ---------------------------------------------------------------------------

def test_adapter_entry_function_raises_without_body() -> None:
    """The adapter module must NOT expose a callable named ingest_open_cbgm_3_john yet.

    FAILS at Wave 2: the adapter has no function body. getattr returns None.
    Calling None raises AttributeError. That IS the expected red state.

    The test is structured so that it FAILS when the function is absent
    (red state) and PASSES only after the impl caste adds the body.
    This satisfies the TDD gate requirement of at least 3 FAILED tests.
    """
    mod = importlib.import_module(ADAPTER_MODULE)
    fn = getattr(mod, ENTRY_FUNCTION, None)
    assert callable(fn), (
        f"{ADAPTER_MODULE}.{ENTRY_FUNCTION} must be a callable, "
        f"but got {type(fn)!r}. "
        "This failure is the expected red state at Wave 2 (docstring-only adapter)."
    )


def test_adapter_returns_dict(fake_driver: FakeDriver, source_root: Path) -> None:
    """ingest_open_cbgm_3_john must return a dict mapping label to count.

    FAILS at Wave 2 with AttributeError or TypeError because the adapter
    has no function body.
    """
    mod = importlib.import_module(ADAPTER_MODULE)
    fn = getattr(mod, ENTRY_FUNCTION)
    result = fn(source_root, fake_driver.settings)
    assert isinstance(result, dict), (
        f"ingest_open_cbgm_3_john must return dict; got {type(result)!r}"
    )
    assert "Witness" in result or "VariantUnit" in result or "Reading" in result, (
        "return dict must contain at least one of: Witness, VariantUnit, Reading"
    )


def test_adapter_emits_required_labels(
    fake_driver: FakeDriver, source_root: Path
) -> None:
    """Running the adapter must merge nodes for every required label.

    FAILS at Wave 2 with AttributeError or TypeError.
    Labels required: Witness, VariantUnit, Reading, Source (Decision 6 + 14).
    """
    mod = importlib.import_module(ADAPTER_MODULE)
    fn = getattr(mod, ENTRY_FUNCTION)
    fn(source_root, fake_driver.settings)
    emitted = fake_driver.captured_labels()
    missing = REQUIRED_LABELS - emitted
    assert not missing, (
        f"adapter did not emit required node labels: {sorted(missing)}. "
        f"Labels seen: {sorted(emitted)}"
    )


def test_adapter_emits_required_edges(
    fake_driver: FakeDriver, source_root: Path
) -> None:
    """Running the adapter must merge every required edge type.

    FAILS at Wave 2 with AttributeError or TypeError.
    Edges required: READS_AT, ATTESTED_BY, CORRECTOR_OF (Decision 6).
    """
    mod = importlib.import_module(ADAPTER_MODULE)
    fn = getattr(mod, ENTRY_FUNCTION)
    fn(source_root, fake_driver.settings)
    emitted = fake_driver.captured_edge_types()
    missing = REQUIRED_EDGES - emitted
    assert not missing, (
        f"adapter did not emit required edge types: {sorted(missing)}. "
        f"Edge types seen: {sorted(emitted)}"
    )


def test_witness_siglum_is_nonempty_string(
    fake_driver: FakeDriver, source_root: Path
) -> None:
    """Every Witness node must have a non-empty siglum string.

    FAILS at Wave 2 with AttributeError or TypeError.

    Predicate: $pred_string from tools/predicates_by_type.cypher.
    Decision 6: siglum is the primary UNIQUE key for Witness nodes.
    """
    mod = importlib.import_module(ADAPTER_MODULE)
    fn = getattr(mod, ENTRY_FUNCTION)
    fn(source_root, fake_driver.settings)
    witnesses = fake_driver.nodes_for_label("Witness")
    assert witnesses, "adapter must emit at least one Witness node"
    bad = [
        w for w in witnesses
        if not isinstance(w.get("siglum"), str) or not w.get("siglum", "").strip()
    ]
    assert not bad, (
        f"Witness nodes with empty or missing siglum: {bad[:3]}. "
        "$pred_string(siglum) must be satisfied."
    )


def test_witness_date_century_is_int(
    fake_driver: FakeDriver, source_root: Path
) -> None:
    """Every Witness node with a date_century must have an integer value.

    FAILS at Wave 2 with AttributeError or TypeError.

    Predicate: $pred_int(date_century) from tools/predicates_by_type.cypher.
    Decision 6: date_century is the manuscript dating in calendar centuries.
    """
    mod = importlib.import_module(ADAPTER_MODULE)
    fn = getattr(mod, ENTRY_FUNCTION)
    fn(source_root, fake_driver.settings)
    witnesses = fake_driver.nodes_for_label("Witness")
    assert witnesses, "adapter must emit at least one Witness node"
    bad = [
        w for w in witnesses
        if "date_century" in w and not isinstance(w["date_century"], int)
    ]
    assert not bad, (
        f"Witness nodes with non-integer date_century: {bad[:3]}. "
        "$pred_int(date_century) requires int type."
    )


def test_witness_language_is_nonempty_string(
    fake_driver: FakeDriver, source_root: Path
) -> None:
    """Every Witness node must have a non-empty language string.

    FAILS at Wave 2 with AttributeError or TypeError.

    Predicate: $pred_string(language) from tools/predicates_by_type.cypher.
    Decision 6: language is normalised to lowercase before persistence.
    """
    mod = importlib.import_module(ADAPTER_MODULE)
    fn = getattr(mod, ENTRY_FUNCTION)
    fn(source_root, fake_driver.settings)
    witnesses = fake_driver.nodes_for_label("Witness")
    assert witnesses, "adapter must emit at least one Witness node"
    bad = [
        w for w in witnesses
        if "language" in w and (
            not isinstance(w["language"], str) or not w["language"].strip()
        )
    ]
    assert not bad, (
        f"Witness nodes with empty or non-string language: {bad[:3]}. "
        "$pred_string(language) must be satisfied."
    )


def test_witness_language_is_lowercase(
    fake_driver: FakeDriver, source_root: Path
) -> None:
    """Witness language must be normalised to lowercase.

    FAILS at Wave 2 with AttributeError or TypeError.

    Decision 6 section 3: 'The string is normalised to lowercase before
    persistence so case-sensitive joins do not split equivalent values.'
    """
    mod = importlib.import_module(ADAPTER_MODULE)
    fn = getattr(mod, ENTRY_FUNCTION)
    fn(source_root, fake_driver.settings)
    witnesses = fake_driver.nodes_for_label("Witness")
    assert witnesses, "adapter must emit at least one Witness node"
    bad = [
        w for w in witnesses
        if isinstance(w.get("language"), str)
        and w["language"] != w["language"].lower()
    ]
    assert not bad, (
        f"Witness language not normalised to lowercase: {bad[:3]}. "
        "Decision 6 requires lowercase normalisation."
    )


def test_variant_unit_book_is_3john(
    fake_driver: FakeDriver, source_root: Path
) -> None:
    """Every VariantUnit node must have book='3John'.

    FAILS at Wave 2 with AttributeError or TypeError.

    Decision 6: book is fixed at the literal string '3John' for every node.
    Any other value is a quarantine event.
    """
    mod = importlib.import_module(ADAPTER_MODULE)
    fn = getattr(mod, ENTRY_FUNCTION)
    fn(source_root, fake_driver.settings)
    units = fake_driver.nodes_for_label("VariantUnit")
    assert units, "adapter must emit at least one VariantUnit node"
    bad = [u for u in units if u.get("book") != "3John"]
    assert not bad, (
        f"VariantUnit nodes with book != '3John': {bad[:3]}. "
        "Decision 6: book is fixed at '3John' for this adapter's scope."
    )


def test_variant_unit_chapter_is_1(
    fake_driver: FakeDriver, source_root: Path
) -> None:
    """Every VariantUnit node must have chapter=1 (integer).

    FAILS at Wave 2 with AttributeError or TypeError.

    Decision 6: chapter is fixed at 1. 3 John has a single chapter.
    """
    mod = importlib.import_module(ADAPTER_MODULE)
    fn = getattr(mod, ENTRY_FUNCTION)
    fn(source_root, fake_driver.settings)
    units = fake_driver.nodes_for_label("VariantUnit")
    assert units, "adapter must emit at least one VariantUnit node"
    bad = [u for u in units if u.get("chapter") != 1]
    assert not bad, (
        f"VariantUnit nodes with chapter != 1: {bad[:3]}. "
        "Decision 6: chapter is fixed at integer 1 for 3 John."
    )


def test_variant_unit_verse_in_range(
    fake_driver: FakeDriver, source_root: Path
) -> None:
    """Every VariantUnit node must have verse in [1, 15] (integer).

    FAILS at Wave 2 with AttributeError or TypeError.

    Decision 6: verse restricted to 1 through 15. Out-of-range rows are
    quarantined, not persisted.
    """
    mod = importlib.import_module(ADAPTER_MODULE)
    fn = getattr(mod, ENTRY_FUNCTION)
    fn(source_root, fake_driver.settings)
    units = fake_driver.nodes_for_label("VariantUnit")
    assert units, "adapter must emit at least one VariantUnit node"
    bad = [
        u for u in units
        if not isinstance(u.get("verse"), int)
        or not (1 <= u["verse"] <= 15)
    ]
    assert not bad, (
        f"VariantUnit nodes with verse outside [1,15]: {bad[:3]}. "
        "Decision 6: verse is restricted to the closed range 1-15."
    )


def test_reading_is_lacuna_is_bool_not_skipped(
    fake_driver: FakeDriver, source_root: Path
) -> None:
    """Reading.is_lacuna must be a bool and lacuna sentinels must not be skipped.

    FAILS at Wave 2 with AttributeError or TypeError.

    Decision 6 edge case A: adapter MUST emit sentinel Reading{is_lacuna:true}
    rather than skipping the edge. The $pred_bool predicate treats both true
    and false as populated; the value is never null.
    """
    mod = importlib.import_module(ADAPTER_MODULE)
    fn = getattr(mod, ENTRY_FUNCTION)
    fn(source_root, fake_driver.settings)
    readings = fake_driver.nodes_for_label("Reading")
    assert readings, "adapter must emit at least one Reading node"
    bad_type = [
        r for r in readings
        if "is_lacuna" in r and not isinstance(r["is_lacuna"], bool)
    ]
    assert not bad_type, (
        f"Reading nodes with non-bool is_lacuna: {bad_type[:3]}. "
        "$pred_bool(is_lacuna) requires bool type."
    )
    lacunas = [r for r in readings if r.get("is_lacuna") is True]
    assert lacunas, (
        "Adapter emitted no lacuna sentinel readings (is_lacuna=True). "
        "Decision 6 edge case A: lacuna readings MUST NOT be skipped."
    )


def test_reading_id_is_nonempty_string(
    fake_driver: FakeDriver, source_root: Path
) -> None:
    """Every Reading node must have a non-empty reading_id string.

    FAILS at Wave 2 with AttributeError or TypeError.

    Decision 6: reading_id is the open-cbgm collation reading identifier,
    persisted verbatim. The reading_id UNIQUE constraint enforces one
    Reading per identifier.
    """
    mod = importlib.import_module(ADAPTER_MODULE)
    fn = getattr(mod, ENTRY_FUNCTION)
    fn(source_root, fake_driver.settings)
    readings = fake_driver.nodes_for_label("Reading")
    assert readings, "adapter must emit at least one Reading node"
    bad = [
        r for r in readings
        if not isinstance(r.get("reading_id"), str)
        or not r.get("reading_id", "").strip()
    ]
    assert not bad, (
        f"Reading nodes with empty or missing reading_id: {bad[:3]}. "
        "$pred_string(reading_id) must be satisfied."
    )


def test_corrector_hands_are_distinct_witness_nodes(
    fake_driver: FakeDriver, source_root: Path
) -> None:
    """Corrector hands with '*' or 'C' suffix must be distinct Witness nodes.

    FAILS at Wave 2 with AttributeError or TypeError.

    Decision 6 edge case C: adapter MUST emit each hand as a distinct Witness
    node linked by CORRECTOR_OF. Merging hands into a single Witness is
    forbidden.
    """
    mod = importlib.import_module(ADAPTER_MODULE)
    fn = getattr(mod, ENTRY_FUNCTION)
    fn(source_root, fake_driver.settings)
    witnesses = fake_driver.nodes_for_label("Witness")
    siglums = [w.get("siglum", "") for w in witnesses]
    corrector_hands = [s for s in siglums if s.endswith("*") or s.endswith("C")]
    assert corrector_hands, (
        "Adapter emitted no corrector-hand Witness nodes (siglum ending '*' or 'C'). "
        "Decision 6 edge case C: corrector hands must be distinct Witness nodes."
    )
    corrector_edges = fake_driver.edges_for_type("CORRECTOR_OF")
    assert corrector_edges, (
        "Adapter emitted no CORRECTOR_OF edges. "
        "Decision 6 edge case C: each corrector hand must link to its base hand."
    )


def test_reads_at_edges_carry_variant_unit_id(
    fake_driver: FakeDriver, source_root: Path
) -> None:
    """READS_AT edges must carry variant_unit_id as a property.

    FAILS at Wave 2 with AttributeError or TypeError.

    Decision 6: 'The edge is qualified by a variant_unit_id property carrying
    the variant unit at which the witness reads the given Reading.' Qualifying
    the edge is required so witness-coverage queries can pre-filter by variant
    unit without walking through Reading.
    """
    mod = importlib.import_module(ADAPTER_MODULE)
    fn = getattr(mod, ENTRY_FUNCTION)
    fn(source_root, fake_driver.settings)
    reads_at = fake_driver.edges_for_type("READS_AT")
    assert reads_at, "adapter must emit at least one READS_AT edge"
    bad = [e for e in reads_at if not e.get("variant_unit_id")]
    assert not bad, (
        f"READS_AT edges missing variant_unit_id property: {bad[:3]}. "
        "Decision 6: every READS_AT edge must carry variant_unit_id."
    )


def test_source_node_slug_open_cbgm(
    fake_driver: FakeDriver, source_root: Path
) -> None:
    """The Source node must be MERGEd with slug='open-cbgm-3-john'.

    FAILS at Wave 2 with AttributeError or TypeError.

    Decision 14: Source uniqueness constraint on source_slug. The adapter
    registers exactly one Source node with slug='open-cbgm-3-john',
    license='MIT', redistribute=true.
    """
    mod = importlib.import_module(ADAPTER_MODULE)
    fn = getattr(mod, ENTRY_FUNCTION)
    fn(source_root, fake_driver.settings)
    slugs = fake_driver.captured_node_slugs("Source")
    sources = fake_driver.nodes_for_label("Source")
    slug_values = [
        s.get("slug") or s.get("source_slug") or s.get("id")
        for s in sources
    ]
    found = "open-cbgm-3-john" in slugs or "open-cbgm-3-john" in slug_values
    assert found, (
        f"Source node with slug='open-cbgm-3-john' not found. "
        f"Got slugs: {slugs}, source values: {slug_values}. "
        "Decision 14 requires Source MERGE before any edge is emitted."
    )


# ---------------------------------------------------------------------------
# GROUP 2: static validation tests (do NOT call adapter, pass at Wave 2)
# ---------------------------------------------------------------------------

def test_predicates_file_has_required_predicates() -> None:
    """tools/predicates_by_type.cypher must define string, int, bool predicates.

    This test does NOT call the adapter. It validates the predicate source
    file is present and parseable per RESEED_PLAN C.5.
    The file path tools/predicates_by_type.cypher is the canonical source.
    """
    assert "string" in PREDICATES, "predicates_by_type.cypher missing $pred_string"
    assert "int" in PREDICATES, "predicates_by_type.cypher missing $pred_int"
    assert "bool" in PREDICATES, "predicates_by_type.cypher missing $pred_bool"
    assert "IS NOT NULL" in PREDICATES["string"], (
        "$pred_string must contain IS NOT NULL check"
    )


def test_expected_count_from_expected_counts_json() -> None:
    """The open-cbgm-3-john entry in expected_counts.json must match spec.

    This test does NOT call the adapter. It validates constants used by
    the coverage tests are correct per the source file.

    Spec: expected_count=728, tier=B, tolerance_relative=0.02,
    min=700, max=760, record_unit=cbgm_node.
    """
    ec_path = REPO / "tools" / "expected_counts.json"
    with open(ec_path, encoding="utf-8") as fh:
        ec = json.load(fh)
    entry = ec["sources"]["open-cbgm-3-john"]
    assert entry["expected_count"] == EXPECTED_COUNT, (
        f"expected_counts.json open-cbgm-3-john count {entry['expected_count']} "
        f"!= {EXPECTED_COUNT}"
    )
    assert entry["tier"] == "B", "open-cbgm-3-john must be Tier B"
    assert entry["min"] == EXPECTED_MIN, (
        f"min {entry['min']} != {EXPECTED_MIN}"
    )
    assert entry["max"] == EXPECTED_MAX, (
        f"max {entry['max']} != {EXPECTED_MAX}"
    )


def test_fixture_seed_derivation(fixture_slice: dict[str, Any]) -> None:
    """The fixture length must be reproducible from the stored seed.

    Seed = int(commit_sha[:8], 16) = int('23c42ecd', 16) = 600059597.
    This test does NOT call the adapter.
    """
    rng = random.Random(SEED_INT)
    length = rng.randint(1024, 16384)
    assert length == fixture_slice["length"], (
        f"Fixture length {fixture_slice['length']} != seeded length {length}. "
        f"Seed: {SEED_INT} from commit {DOCSTRING_COMMIT_SHA[:8]}"
    )


def test_fixture_variant_units_in_scope(fixture_slice: dict[str, Any]) -> None:
    """Fixture variant units must all be within 3John chapter 1 verses 1-15.

    This test does NOT call the adapter. It validates the fixture itself.
    """
    for unit in fixture_slice["variant_units"]:
        assert unit["book"] == "3John", (
            f"Fixture variant unit has wrong book: {unit['book']}"
        )
        assert unit["chapter"] == 1, (
            f"Fixture variant unit has wrong chapter: {unit['chapter']}"
        )
        assert 1 <= unit["verse"] <= 15, (
            f"Fixture variant unit verse {unit['verse']} outside [1,15]"
        )


def test_fixture_lacuna_sentinels_present(fixture_slice: dict[str, Any]) -> None:
    """Fixture must contain at least one lacuna reading (is_lacuna=true).

    This test does NOT call the adapter. It validates the fixture covers
    Decision 6 edge case A (lacuna sentinels must not be skipped).
    """
    lacunas = [
        r
        for unit in fixture_slice["variant_units"]
        for r in unit["readings"]
        if r.get("is_lacuna") is True
    ]
    assert lacunas, (
        "Fixture has no lacuna readings. Fixture must include is_lacuna=true "
        "readings to exercise Decision 6 edge case A."
    )


def test_fixture_corrector_hands_present(fixture_slice: dict[str, Any]) -> None:
    """Fixture must contain corrector hand definitions.

    This test does NOT call the adapter. It validates the fixture covers
    Decision 6 edge case C (corrector hands as distinct Witness nodes).
    """
    correctors = [
        c
        for unit in fixture_slice["variant_units"]
        for c in unit.get("correctors", [])
    ]
    assert correctors, (
        "Fixture has no corrector definitions. Fixture must include corrector "
        "hands to exercise Decision 6 edge case C."
    )


def test_fixture_witnesses_have_required_fields(fixture_slice: dict[str, Any]) -> None:
    """Fixture witness records must carry siglum, date_century, language, ga_number.

    This test does NOT call the adapter. It validates the fixture schema
    matches the Decision 6 Witness property table.
    """
    for witness in fixture_slice["all_witnesses"]:
        assert "siglum" in witness, f"Witness missing siglum: {witness}"
        assert "date_century" in witness, f"Witness missing date_century: {witness}"
        assert "language" in witness, f"Witness missing language: {witness}"
        assert "ga_number" in witness, f"Witness missing ga_number key: {witness}"
        assert isinstance(witness["siglum"], str) and witness["siglum"].strip(), (
            f"Witness siglum not a non-empty string: {witness}"
        )
        assert isinstance(witness["date_century"], int), (
            f"Witness date_century not int: {witness}"
        )
        assert witness["language"] == witness["language"].lower(), (
            f"Witness language not lowercase: {witness}"
        )


def test_fixture_length_in_valid_range(fixture_slice: dict[str, Any]) -> None:
    """Fixture length must be in range [1024, 16384] per the seeded RNG spec.

    This test does NOT call the adapter.
    """
    length = fixture_slice["length"]
    assert 1024 <= length <= 16384, (
        f"Fixture length {length} outside [1024, 16384]"
    )


# ---------------------------------------------------------------------------
# GROUP 3: stub-rejection sweep (parametrized over 13 stubs)
# ---------------------------------------------------------------------------

STUB_MODULES = [
    "tests.lexical.stubs.broken_adapter",
    "tests.lexical.stubs.empty_required",
    "tests.lexical.stubs.identical_lemma",
    "tests.lexical.stubs.zero_records",
    "tests.lexical.stubs.hardcoded_fixture",
    "tests.lexical.stubs.minimal_edges",
    "tests.lexical.stubs.nan_inf_numeric",
    "tests.lexical.stubs.duplicate_records",
    "tests.lexical.stubs.swapped_property_names",
    "tests.lexical.stubs.mutated_strings",
    "tests.lexical.stubs.silent_exception_swallow",
    "tests.lexical.stubs.reversed_edge_direction",
    "tests.lexical.stubs.hash_ordered",
]


@pytest.mark.parametrize("stub_module_name", STUB_MODULES)
def test_verifier_rejects_attack_stub(
    stub_module_name: str,
    fake_driver: FakeDriver,
    source_root: Path,
) -> None:
    """The coverage-test scaffold must detect defects in each attack-vector stub.

    Pattern:
      1. Import the stub.
      2. Try to find an ingest entry point named ingest_open_cbgm_3_john or ingest.
      3. If no entry point, skip (stub may only expose emit_records/emit_edges).
      4. If entry point exists, call it. If it raises, the stub is rejected.
      5. If it runs silently, check labels, edge types, and property correctness.
         At least one check must fail. If none fail, the test fails with
         'verifier failed to detect defect'.
    """
    stub_mod = importlib.import_module(stub_module_name)

    fn = (
        getattr(stub_mod, ENTRY_FUNCTION, None)
        or getattr(stub_mod, "ingest", None)
    )
    if fn is None or not callable(fn):
        pytest.skip(
            f"{stub_module_name} has no callable ingest entry point "
            f"(attributes: {[x for x in dir(stub_mod) if not x.startswith('_')]})"
        )

    raised = False
    try:
        fn(source_root, fake_driver.settings)
    except Exception:
        raised = True

    if raised:
        return

    emitted_labels = fake_driver.captured_labels()
    emitted_edges = fake_driver.captured_edge_types()
    witnesses = fake_driver.nodes_for_label("Witness")
    units = fake_driver.nodes_for_label("VariantUnit")
    readings = fake_driver.nodes_for_label("Reading")

    label_ok = REQUIRED_LABELS.issubset(emitted_labels)
    edge_ok = REQUIRED_EDGES.issubset(emitted_edges)
    book_ok = all(u.get("book") == "3John" for u in units) if units else False
    chapter_ok = all(u.get("chapter") == 1 for u in units) if units else False
    verse_ok = all(
        isinstance(u.get("verse"), int) and 1 <= u["verse"] <= 15
        for u in units
    ) if units else False
    siglum_ok = all(
        isinstance(w.get("siglum"), str) and w.get("siglum", "").strip()
        for w in witnesses
    ) if witnesses else False
    lacuna_ok = any(r.get("is_lacuna") is True for r in readings) if readings else False

    rejected = (
        not label_ok
        or not edge_ok
        or not book_ok
        or not chapter_ok
        or not verse_ok
        or not siglum_ok
        or not lacuna_ok
    )
    assert rejected, (
        f"verifier failed to detect defect in {stub_module_name}. "
        f"Labels: {sorted(emitted_labels)}, "
        f"Edges: {sorted(emitted_edges)}, "
        f"Sample witnesses: {witnesses[:2]}, "
        f"Sample units: {units[:2]}, "
        f"Lacuna present: {lacuna_ok}"
    )
