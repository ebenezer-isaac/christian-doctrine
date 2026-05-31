"""Cross-check that all four v3.1 spec sources agree, and that the v3.0
function and type aliases are gone.

Run: python tools/verify_schema_consistency.py [--root PATH]
"""

from __future__ import annotations

import argparse
import importlib
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Allow running this script directly (python tools/verify_schema_consistency.py)
# from the repo root without requiring the package to be pip-installed.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

EXPECTED_VERSION = "3.1"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _check(name: str, fn: Callable[[], tuple[bool, str]]) -> Check:
    try:
        ok, detail = fn()
    except Exception as exc:  # noqa: BLE001
        return Check(name=name, ok=False, detail=f"exception: {exc!r}")
    return Check(name=name, ok=ok, detail=detail)


# ---------------------------------------------------------------------------
# Source 1: pipeline2/evidence_schema.py SCHEMA_VERSION
# ---------------------------------------------------------------------------


def check_schema_version_constant() -> tuple[bool, str]:
    mod = importlib.import_module("pipeline2.evidence_schema")
    value = getattr(mod, "SCHEMA_VERSION", None)
    if value != EXPECTED_VERSION:
        return False, f"SCHEMA_VERSION={value!r}, expected {EXPECTED_VERSION!r}"
    return True, f"SCHEMA_VERSION={value!r}"


# ---------------------------------------------------------------------------
# Source 2: pipeline2/evidence_schema.py Evidence.schema_version Literal
# ---------------------------------------------------------------------------


def check_evidence_schema_literal() -> tuple[bool, str]:
    mod = importlib.import_module("pipeline2.evidence_schema")
    evidence_cls = mod.Evidence
    field = evidence_cls.model_fields.get("schema_version")
    if field is None:
        return False, "Evidence.schema_version field missing"
    ann = field.annotation
    args = getattr(ann, "__args__", ())
    if not args or args[0] != EXPECTED_VERSION:
        return False, f"Evidence.schema_version Literal args={args!r}"
    return True, f"Evidence.schema_version Literal={args!r}"


# ---------------------------------------------------------------------------
# Source 3: docs/EVIDENCE_SCHEMA.md
# ---------------------------------------------------------------------------

RE_DOC_HEADING_VERSION = re.compile(r"^#\s*Evidence\s+Schema\s+v(\S+)", re.MULTILINE)
RE_DOC_SCHEMA_VERSION_JSON = re.compile(r'"\$schema_version"\s*:\s*"([0-9.]+)"')


def check_evidence_schema_md(root: Path) -> tuple[bool, str]:
    path = root / "docs" / "EVIDENCE_SCHEMA.md"
    if not path.is_file():
        return False, f"missing file: {path}"
    text = path.read_text(encoding="utf-8")

    heading = RE_DOC_HEADING_VERSION.search(text)
    if not heading:
        return False, f"no heading match in {path}"
    if heading.group(1) != EXPECTED_VERSION:
        return False, f"heading version={heading.group(1)!r}, expected {EXPECTED_VERSION!r}"

    bad_examples: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), start=1):
        m = RE_DOC_SCHEMA_VERSION_JSON.search(line)
        if not m:
            continue
        if m.group(1) != EXPECTED_VERSION:
            bad_examples.append((i, line.strip()))

    if bad_examples:
        first_line, first_snippet = bad_examples[0]
        return False, (
            f"{len(bad_examples)} JSON example(s) disagree, first at "
            f"line {first_line}: {first_snippet}"
        )
    return True, f"heading and all JSON examples agree on v{EXPECTED_VERSION}"


# ---------------------------------------------------------------------------
# Source 4: docs/phase_prompts/pipeline2_verdict.md
# ---------------------------------------------------------------------------

RE_VERDICT_YAML_SCHEMA = re.compile(r"^\s*schema_version\s*:\s*(\S+)", re.MULTILINE)


def check_verdict_prompt_md(root: Path) -> tuple[bool, str]:
    path = root / "docs" / "phase_prompts" / "pipeline2_verdict.md"
    if not path.is_file():
        return False, f"missing file: {path}"
    text = path.read_text(encoding="utf-8")

    yaml_versions = RE_VERDICT_YAML_SCHEMA.findall(text)
    json_versions = RE_DOC_SCHEMA_VERSION_JSON.findall(text)

    if not yaml_versions and not json_versions:
        return False, f"no schema_version mention in {path}"

    bad: list[str] = []
    for v in yaml_versions:
        if v.strip().strip('"') != EXPECTED_VERSION:
            bad.append(f"yaml schema_version={v!r}")
    for v in json_versions:
        if v != EXPECTED_VERSION:
            bad.append(f"json $schema_version={v!r}")

    if bad:
        return False, "; ".join(bad)
    return True, f"yaml={yaml_versions!r}, json={json_versions!r}"


# ---------------------------------------------------------------------------
# Function / type alias presence and absence
# ---------------------------------------------------------------------------


def check_score_calc_has_new_funcs() -> tuple[bool, str]:
    mod = importlib.import_module("pipeline2.score_calc")
    missing = [
        name
        for name in ("compute_lexical_breadth", "compute_variant_stability")
        if not hasattr(mod, name)
    ]
    if missing:
        return False, f"missing from pipeline2.score_calc: {missing!r}"
    return True, "compute_lexical_breadth and compute_variant_stability importable"


def check_score_calc_no_compute_lexical_score() -> tuple[bool, str]:
    mod = importlib.import_module("pipeline2.score_calc")
    if hasattr(mod, "compute_lexical_score"):
        return False, "compute_lexical_score is still importable from pipeline2.score_calc"
    return True, "compute_lexical_score is gone from pipeline2.score_calc"


def check_evidence_schema_new_aliases() -> tuple[bool, str]:
    mod = importlib.import_module("pipeline2.evidence_schema")
    missing = [
        name
        for name in ("LexicalBreadth", "LexicalDirectness", "VariantStability")
        if not hasattr(mod, name)
    ]
    if missing:
        return False, f"missing from pipeline2.evidence_schema: {missing!r}"
    return True, "LexicalBreadth, LexicalDirectness, VariantStability importable"


def check_evidence_schema_no_confidence_alias() -> tuple[bool, str]:
    mod = importlib.import_module("pipeline2.evidence_schema")
    if hasattr(mod, "Confidence"):
        return False, "Confidence type alias is still exported from pipeline2.evidence_schema"
    return True, "Confidence type alias is gone from pipeline2.evidence_schema"


def check_evidence_model_fields_present() -> tuple[bool, str]:
    mod = importlib.import_module("pipeline2.evidence_schema")
    verdict_cls = mod.Verdict
    fields = verdict_cls.model_fields
    expected = ("lexical_breadth", "lexical_directness", "variant_stability")
    missing = [name for name in expected if name not in fields]
    if missing:
        return False, f"Verdict missing fields: {missing!r}"
    return True, f"Verdict has all v3.1 fields: {expected!r}"


def check_evidence_model_fields_absent() -> tuple[bool, str]:
    mod = importlib.import_module("pipeline2.evidence_schema")
    verdict_cls = mod.Verdict
    fields = verdict_cls.model_fields
    leftover = [name for name in ("lexical_score", "confidence") if name in fields]
    if leftover:
        return False, f"Verdict still has dead v3.0 fields: {leftover!r}"
    return True, "Verdict has no dead v3.0 fields"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Cross-check that v3.1 SCHEMA_VERSION, Evidence Literal, EVIDENCE_SCHEMA.md, "
            "and pipeline2_verdict.md all agree, and that the v3.0 names are gone."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repo root (default: cwd).",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args()
    root: Path = args.root.resolve()

    checks: list[Check] = [
        _check("SCHEMA_VERSION constant", check_schema_version_constant),
        _check("Evidence.schema_version Literal", check_evidence_schema_literal),
        _check("docs/EVIDENCE_SCHEMA.md", lambda: check_evidence_schema_md(root)),
        _check(
            "docs/phase_prompts/pipeline2_verdict.md",
            lambda: check_verdict_prompt_md(root),
        ),
        _check("score_calc new funcs present", check_score_calc_has_new_funcs),
        _check(
            "score_calc compute_lexical_score gone",
            check_score_calc_no_compute_lexical_score,
        ),
        _check(
            "evidence_schema new type aliases present",
            check_evidence_schema_new_aliases,
        ),
        _check(
            "evidence_schema Confidence alias gone",
            check_evidence_schema_no_confidence_alias,
        ),
        _check("Verdict has v3.1 fields", check_evidence_model_fields_present),
        _check("Verdict has no v3.0 fields", check_evidence_model_fields_absent),
    ]

    failed = 0
    for c in checks:
        status = "PASS" if c.ok else "FAIL"
        print(f"{status} {c.name}: {c.detail}")
        if not c.ok:
            failed += 1

    print()
    if failed > 0:
        print(f"VERIFICATION FAILED: {failed} issues")
        return 1
    print("VERIFICATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
