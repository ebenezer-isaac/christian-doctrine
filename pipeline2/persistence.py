"""Pipeline 2 persistence: evidence/<id>.json + Verdict node + non-redistributable list."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from neo4j import Driver

from pipeline2.evidence_schema import Evidence

EVIDENCE_DIR = Path("evidence")
NON_REDIST_FILE = EVIDENCE_DIR / "_non_redistributable.txt"


def evidence_path(question_id: str, base: Path | None = None) -> Path:
    return (base or EVIDENCE_DIR) / f"{question_id}.json"


def persist_evidence(
    evidence: Evidence,
    lexical_driver: Driver | None = None,
    base: Path | None = None,
) -> Path:
    """Write evidence to disk, update the non-redistributable list, optionally ingest."""
    base = base or EVIDENCE_DIR
    base.mkdir(parents=True, exist_ok=True)
    path = evidence_path(evidence.question_id, base=base)
    payload = evidence.model_dump(by_alias=True, mode="json")
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _rewrite_non_redistributable_list(base)
    if lexical_driver is not None:
        _upsert_verdict_node(evidence, lexical_driver)
    return path


def load_evidence(question_id: str, base: Path | None = None) -> Evidence:
    path = evidence_path(question_id, base=base)
    if not path.exists():
        raise FileNotFoundError(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Evidence.model_validate(raw)


def list_evidence_files(base: Path | None = None) -> list[str]:
    base = base or EVIDENCE_DIR
    if not base.exists():
        return []
    out: list[str] = []
    for p in sorted(base.glob("*.json")):
        out.append(p.name)
    return out


def evidence_publish_safe_list(base: Path | None = None) -> list[str]:
    base = base or EVIDENCE_DIR
    if not base.exists():
        return []
    safe: list[str] = []
    for p in sorted(base.glob("*.json")):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        audit = raw.get("license_audit", {})
        if audit.get("evidence_safe_to_publish") is True:
            qid = raw.get("question_id")
            if isinstance(qid, str):
                safe.append(qid)
    return safe


def _rewrite_non_redistributable_list(base: Path) -> None:
    unsafe: set[str] = set()
    for p in sorted(base.glob("*.json")):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        audit = raw.get("license_audit", {})
        if audit.get("evidence_safe_to_publish") is False:
            qid = raw.get("question_id")
            if isinstance(qid, str):
                unsafe.add(qid)
    target = base / "_non_redistributable.txt"
    if not unsafe:
        if target.exists():
            target.unlink()
        return
    body = "\n".join(sorted(unsafe)) + "\n"
    target.write_text(body, encoding="utf-8")


def _upsert_verdict_node(evidence: Evidence, driver: Driver) -> None:
    cypher = """
    MERGE (v:Verdict {question_id: $qid})
    SET v.affirms = $affirms,
        v.lexical_breadth = $lexical_breadth,
        v.lexical_directness = $lexical_directness,
        v.variant_stability = $variant_stability,
        v.generated_at = $generated_at,
        v.pipeline_version = $pipeline_version,
        v.evidence_safe_to_publish = $safe
    """
    affirms = evidence.verdict.affirms
    if affirms is True:
        affirms_str = "true"
    elif affirms is False:
        affirms_str = "false"
    elif affirms is None:
        affirms_str = "null"
    else:
        affirms_str = affirms
    params: dict[str, Any] = {
        "qid": evidence.question_id,
        "affirms": affirms_str,
        "lexical_breadth": evidence.verdict.lexical_breadth,
        "lexical_directness": evidence.verdict.lexical_directness,
        "variant_stability": evidence.verdict.variant_stability,
        "generated_at": evidence.generated_at,
        "pipeline_version": evidence.pipeline_version,
        "safe": evidence.license_audit.evidence_safe_to_publish,
    }
    with driver.session() as session:
        session.run(cypher, **params).consume()
