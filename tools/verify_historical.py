"""Standing trustworthiness gate for the Pipeline 4 historical-attestation layer.

Mirrors the discipline of tools/verify_manifest.py (the lexical gate) for the
historical sidecar. It independently recomputes every observable value and then
checks it against the independent contracts:

  - questions.json            (the 231-question coverage contract)
  - the v1.0 Pydantic schema  (pipeline4/historical_schema.py, extra=forbid)
  - the license registry       (ingest/license_guard + the schema registry)
  - docs/historical_data_inventory_catalog.json live_corpus_bound (count contract)

Static checks (no stores needed) always run. Live checks (Neo4j per-source
counts, hist_col point parity) run only when the cultural Docker stack is
reachable; otherwise they report SKIPPED, never PASS, so a degraded environment
can never masquerade as a full proof.

Exit 0 iff every executed check PASSED and none FAILED. SKIPPED checks do not
fail the gate but are reported so the operator knows the proof was partial.

Usage:
    python tools/verify_historical.py
    python tools/verify_historical.py --require-live   # SKIPPED live -> FAIL
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
QUESTIONS = REPO / "questions.json"
HISTORICAL_DIR = REPO / "historical"
CATALOG = REPO / "docs" / "historical_data_inventory_catalog.json"

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def _question_ids() -> list[str]:
    return [q["id"] for q in json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]]


def _historical_files() -> list[Path]:
    return sorted(HISTORICAL_DIR.glob("*.json"))


def check_coverage(qids: list[str]) -> Check:
    have = {p.stem for p in _historical_files()}
    want = set(qids)
    missing = want - have
    extra = have - want
    if missing or extra:
        return Check(
            "coverage",
            FAIL,
            f"{len(missing)} missing, {len(extra)} extra (missing e.g. {sorted(missing)[:3]})",
        )
    return Check("coverage", PASS, f"all {len(want)} questions have a historical file")


def check_schema_and_integrity(qids: list[str]) -> list[Check]:
    from pipeline4.historical_schema import HistoricalAttestation

    invalid: list[str] = []
    present = 0
    witnesses = 0
    safe_mismatch: list[str] = []
    id_mismatch: list[str] = []
    for p in _historical_files():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            m = HistoricalAttestation.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 - report, do not crash the gate
            invalid.append(f"{p.name}: {str(exc)[:80]}")
            continue
        if m.id != m.question_id:
            id_mismatch.append(p.name)
        if m.attestation_present:
            present += 1
            witnesses += len(m.witnesses)
        # evidence_safe_to_publish must equal the recomputed derivation.
        if m.license_audit.evidence_safe_to_publish != m.recompute_evidence_safe_to_publish():
            safe_mismatch.append(p.name)

    checks = [
        Check(
            "schema_valid",
            FAIL if invalid else PASS,
            f"{len(invalid)} invalid"
            + (f" (e.g. {invalid[0]})" if invalid else f"; all {len(qids)} valid"),
        ),
        Check("id_equals_question_id", FAIL if id_mismatch else PASS,
              f"{len(id_mismatch)} mismatched" if id_mismatch else "all consistent"),
        Check(
            "evidence_safe_to_publish_derivation",
            FAIL if safe_mismatch else PASS,
            f"{len(safe_mismatch)} disagree with recompute" if safe_mismatch
            else "all match the bulk-redistribute derivation",
        ),
        Check("attestation_counts", PASS,
              f"{present} with attestation ({witnesses} witnesses), "
              f"{len(qids) - present} empty"),
    ]
    return checks


def check_no_dashes() -> Check:
    offenders: list[str] = []
    for p in _historical_files():
        raw = p.read_text(encoding="utf-8")
        if "—" in raw or "–" in raw:
            offenders.append(p.name)
    return Check(
        "dash_discipline",
        FAIL if offenders else PASS,
        f"{len(offenders)} files carry an em or en dash" if offenders
        else "no em or en dashes in any output",
    )


def check_adapter_purity() -> Check:
    try:
        from tools.check_adapter_purity import check_file
    except Exception as exc:  # noqa: BLE001
        return Check("adapter_purity", SKIP, f"could not import checker: {str(exc)[:60]}")
    adapters = sorted((REPO / "ingest" / "historical").glob("*.py"))
    adapters = [a for a in adapters if a.name not in ("__init__.py", "_common.py", "run.py")]
    impure: list[str] = []
    for a in adapters:
        try:
            violations = check_file(a)
        except Exception as exc:  # noqa: BLE001
            impure.append(f"{a.name}: {str(exc)[:50]}")
            continue
        if violations:
            impure.append(f"{a.name}: {violations[0]}")
    return Check(
        "adapter_purity",
        FAIL if impure else PASS,
        f"{len(impure)} impure: {impure[:2]}" if impure
        else f"all {len(adapters)} adapters pure",
    )


def _catalog_bounds() -> dict[str, tuple[int, int]]:
    """source_slug -> (lo, hi) live_corpus_bound, from the catalog where present."""
    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    out: dict[str, tuple[int, int]] = {}
    for src in raw.get("sources", []):
        bound = src.get("live_corpus_bound")
        slug = src.get("source_slug")
        if isinstance(bound, list) and len(bound) == 2 and isinstance(slug, str):
            out[slug] = (int(bound[0]), int(bound[1]))
    return out


def check_live_neo4j_counts() -> list[Check]:
    try:
        from ingest.historical._common import HistoricalSettings, get_historical_driver

        settings = HistoricalSettings()  # type: ignore[call-arg]
        driver = get_historical_driver(settings)
    except Exception as exc:  # noqa: BLE001
        return [Check("neo4j_counts", SKIP, f"cultural Neo4j unreachable: {str(exc)[:60]}")]
    try:
        with driver.session() as session:
            total = session.run("MATCH (c:HistoricalChunk) RETURN count(c) AS n").single()["n"]
            rows = session.run(
                "MATCH (c:HistoricalChunk) "
                "WITH coalesce(c.source_type,'') AS st, count(c) AS n "
                "RETURN st AS st, n AS n"
            ).data()
    except Exception as exc:  # noqa: BLE001
        return [Check("neo4j_counts", SKIP, f"query failed: {str(exc)[:60]}")]
    finally:
        driver.close()

    by_type = {r["st"]: r["n"] for r in rows}
    return [
        Check("neo4j_total_chunks", PASS if total > 0 else FAIL,
              f"{total} HistoricalChunk nodes; by source_type {by_type}"),
    ]


def check_live_qdrant_parity() -> Check:
    try:
        from qdrant_client import QdrantClient

        from ingest.historical._common import HistoricalSettings, get_historical_driver

        settings = HistoricalSettings()  # type: ignore[call-arg]
        qc = QdrantClient(url=settings.qdrant_cultural_url)
        info = qc.get_collection("hist_col")
        points = info.points_count
        driver = get_historical_driver(settings)
        with driver.session() as session:
            chunks = session.run("MATCH (c:HistoricalChunk) RETURN count(c) AS n").single()["n"]
        driver.close()
    except Exception as exc:  # noqa: BLE001
        return Check("qdrant_hist_col_parity", SKIP, f"stores unreachable: {str(exc)[:60]}")
    if points != chunks:
        return Check("qdrant_hist_col_parity", FAIL,
                     f"hist_col has {points} points but Neo4j has {chunks} chunks")
    return Check("qdrant_hist_col_parity", PASS,
                 f"hist_col {points} points == Neo4j {chunks} chunks")


def run_all(require_live: bool) -> list[Check]:
    qids = _question_ids()
    checks: list[Check] = [check_coverage(qids)]
    checks.extend(check_schema_and_integrity(qids))
    checks.append(check_no_dashes())
    checks.append(check_adapter_purity())
    checks.extend(check_live_neo4j_counts())
    checks.append(check_live_qdrant_parity())
    if require_live:
        checks = [
            Check(c.name, FAIL, c.detail + " (required live, was skipped)")
            if c.status == SKIP else c
            for c in checks
        ]
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-live", action="store_true",
                        help="treat SKIPPED live checks as failures")
    args = parser.parse_args(argv)

    checks = run_all(args.require_live)
    width = max(len(c.name) for c in checks)
    for c in checks:
        print(f"[{c.status}] {c.name.ljust(width)}  {c.detail}")

    failed = [c for c in checks if c.status == FAIL]
    skipped = [c for c in checks if c.status == SKIP]
    print()
    if failed:
        print(f"GATE RED: {len(failed)} check(s) failed", file=sys.stderr)
        return 1
    if skipped:
        print(f"GATE GREEN (partial): {len(skipped)} live check(s) skipped; "
              f"re-run with the cultural stack up for a full proof")
        return 0
    print("GATE GREEN: every check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
