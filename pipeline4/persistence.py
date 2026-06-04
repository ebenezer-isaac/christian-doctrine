"""Pipeline 4 persistence: historical/<id>.json + non-redistributable list.

Mirrors pipeline2/persistence.py. Writes the attestation sidecar and maintains
historical/_non_redistributable.txt (question ids whose
license_audit.evidence_safe_to_publish is False).
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline4.historical_schema import HistoricalAttestation

HISTORICAL_DIR = Path("historical")
NON_REDIST_FILE = HISTORICAL_DIR / "_non_redistributable.txt"


def historical_path(question_id: str, base: Path | None = None) -> Path:
    return (base or HISTORICAL_DIR) / f"{question_id}.json"


def persist_historical(
    attestation: HistoricalAttestation,
    base: Path | None = None,
) -> Path:
    """Write attestation to disk and rewrite the non-redistributable list."""
    base = base or HISTORICAL_DIR
    base.mkdir(parents=True, exist_ok=True)
    path = historical_path(attestation.question_id, base=base)
    payload = attestation.model_dump(by_alias=True, mode="json")
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _rewrite_non_redistributable_list(base)
    return path


def load_historical(
    question_id: str, base: Path | None = None
) -> HistoricalAttestation:
    path = historical_path(question_id, base=base)
    if not path.exists():
        raise FileNotFoundError(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return HistoricalAttestation.model_validate(raw)


def list_historical_files(base: Path | None = None) -> list[str]:
    base = base or HISTORICAL_DIR
    if not base.exists():
        return []
    return [p.name for p in sorted(base.glob("*.json"))]


def historical_publish_safe_list(base: Path | None = None) -> list[str]:
    base = base or HISTORICAL_DIR
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
