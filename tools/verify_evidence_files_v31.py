"""Validate every evidence/*.json against the v3.1 Pydantic schema.

Run: python tools/verify_evidence_files_v31.py [--json] [--strict-empty]
                                                [--root PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Allow running this script directly (python tools/verify_evidence_files_v31.py)
# from the repo root without requiring the package to be pip-installed.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pydantic import ValidationError  # noqa: E402

from pipeline2.evidence_schema import Evidence  # noqa: E402


@dataclass(frozen=True)
class FileResult:
    path: Path
    ok: bool
    error: str | None


def _first_error_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return str(exc)
    err = errors[0]
    loc = ".".join(str(p) for p in err.get("loc", ()))
    msg = err.get("msg", "")
    typ = err.get("type", "")
    return f"{loc}: {msg} (type={typ})"


def validate_file(path: Path) -> FileResult:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return FileResult(path=path, ok=False, error=f"read failed: {exc}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return FileResult(path=path, ok=False, error=f"json decode failed: {exc}")
    try:
        Evidence.model_validate(data)
    except ValidationError as exc:
        return FileResult(path=path, ok=False, error=_first_error_message(exc))
    return FileResult(path=path, ok=True, error=None)


def iter_evidence_files(evidence_dir: Path) -> list[Path]:
    """Top-level evidence/*.json only. Skip archive*/ subdirs and non-JSON."""
    out: list[Path] = []
    if not evidence_dir.is_dir():
        return out
    for child in sorted(evidence_dir.iterdir()):
        if child.is_dir():
            continue
        if child.suffix.lower() != ".json":
            continue
        if child.name.startswith("_"):
            continue
        out.append(child)
    return out


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate every evidence/*.json against the v3.1 Pydantic schema."
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--strict-empty",
        action="store_true",
        help="Exit non-zero if evidence/ is empty.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repo root containing evidence/ (default: cwd).",
    )
    return parser.parse_args(argv)


def _print_human(results: list[FileResult], total: int, passed: int, failed: int) -> None:
    for r in results:
        if r.ok:
            continue
        print(f"FAIL {r.path}: {r.error}")
    print()
    print(f"Total: {total}  Passed: {passed}  Failed: {failed}")


def _print_json(results: list[FileResult], total: int, passed: int, failed: int) -> None:
    payload = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "results": [
            {"path": str(r.path), "ok": r.ok, "error": r.error} for r in results
        ],
    }
    print(json.dumps(payload, indent=2))


def main() -> int:
    args = _parse_args()
    root: Path = args.root.resolve()
    evidence_dir = root / "evidence"
    files = iter_evidence_files(evidence_dir)

    if not files:
        if args.strict_empty:
            if args.as_json:
                print(json.dumps({"total": 0, "passed": 0, "failed": 0, "results": []}))
            else:
                print(f"No evidence/*.json files found under {evidence_dir}")
            print("VERIFICATION FAILED: 1 issues")
            return 1
        if args.as_json:
            print(json.dumps({"total": 0, "passed": 0, "failed": 0, "results": []}))
        else:
            print(f"No evidence/*.json files found under {evidence_dir}")
            print("VERIFICATION PASSED")
        return 0

    results = [validate_file(p) for p in files]
    passed = sum(1 for r in results if r.ok)
    failed = sum(1 for r in results if not r.ok)
    total = len(results)

    if args.as_json:
        _print_json(results, total, passed, failed)
    else:
        _print_human(results, total, passed, failed)

    if failed > 0:
        if not args.as_json:
            print(f"VERIFICATION FAILED: {failed} issues")
        return 1
    if not args.as_json:
        print("VERIFICATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
