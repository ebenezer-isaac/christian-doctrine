"""Scan the repo for v3.0 dead refs left over after the v3.1 migration.

Run: python tools/verify_no_v30_dead_refs.py [--strict] [--root PATH]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

CAT_LEXICAL_SCORE = "lexical_score"
CAT_COMPUTE_LEXICAL_SCORE = "compute_lexical_score"
CAT_VERDICT_CONFIDENCE = "verdict_confidence"
CAT_CONFIDENCE_IMPORT = "Confidence_import"
CAT_SCHEMA_VERSION_30 = "schema_version_3.0"
CAT_SCHEMA_LITERAL_30 = "schema_literal_3.0"
CAT_EVIDENCE_FILE_30 = "evidence_file_3.0"

CATEGORIES: tuple[str, ...] = (
    CAT_LEXICAL_SCORE,
    CAT_COMPUTE_LEXICAL_SCORE,
    CAT_VERDICT_CONFIDENCE,
    CAT_CONFIDENCE_IMPORT,
    CAT_SCHEMA_VERSION_30,
    CAT_SCHEMA_LITERAL_30,
    CAT_EVIDENCE_FILE_30,
)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

RE_LEXICAL_SCORE = re.compile(r"\blexical_score\b")
RE_COMPUTE_LEXICAL_SCORE = re.compile(r"\bcompute_lexical_score\b")
# Match only the v3.0 verdict confidence enum, never other confidence fields:
# - JSON form: "confidence": "high" | "medium" | "low"
# - Python attribute form on a verdict-adjacent identifier
RE_CONFIDENCE_JSON_KEY = re.compile(r"\"confidence\"\s*:\s*\"(high|medium|low)\"")
RE_CONFIDENCE_ATTR = re.compile(r"\b(verdict|evidence\.verdict|result|raw)\.confidence\b")
RE_VERDICT_CTX_TOKENS = re.compile(
    r"(\"verdict\"|evidence\.verdict|verdict\.confidence|\"lexical_verdict\")"
)
RE_CONFIDENCE_IMPORT = re.compile(
    r"from\s+pipeline2\.evidence_schema\s+import\s+([^\n]*\bConfidence\b[^\n]*)"
)
RE_SCHEMA_VERSION_KEY = re.compile(r"(\$?schema_version|SCHEMA_VERSION)")
RE_STRING_30 = re.compile(r"\"3\.0\"|'3\.0'")
RE_SCHEMA_LITERAL_30 = re.compile(r"\"\$schema_version\"\s*:\s*\"3\.0\"")

# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------

ALLOWLIST_PATH_PARTS: tuple[str, ...] = (
    ".git",
    ".venv",
    ".ruff_cache",
    "embeddings",
    "docker",
    "converted",
    "parsed",
    "__pycache__",
    "node_modules",
    "tmp",
)
ALLOWLIST_PATH_PREFIXES: tuple[str, ...] = (
    "archive",
    "backups",
    ".tmp-",
)

ALLOWLIST_FILES: frozenset[str] = frozenset(
    {
        "tools/verify_no_v30_dead_refs.py",
        "tools/verify_evidence_files_v31.py",
        "tools/verify_schema_consistency.py",
    }
)

# Heading anchors / line-substrings in docs that mark allowed migration history.
ALLOWLIST_DOC_LINE_MARKERS: tuple[str, ...] = (
    "Migration history",
    "v3.0 (superseded)",
    "v3.0 -> v3.1",
    "v3.0 to v3.1",
    "v2.0 -> v3.0",
    "v2.0 to v3.0",
)

# Inline pragma. Any line containing this marker is excluded from all checks.
# Use only when a literal v3.0 reference is the actual subject under test
# (e.g. a rejection test that needs the old version string).
INLINE_PRAGMA = "v30-dead-ref-ok"

# Text file extensions we will scan. Binary / opaque formats skipped.
TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".md",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".cfg",
        ".ini",
        ".txt",
        ".cypher",
        ".sh",
        ".ps1",
        ".sql",
    }
)


@dataclass(frozen=True)
class Finding:
    path: Path
    line_no: int
    category: str
    snippet: str


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def _rel_parts(path: Path, root: Path) -> tuple[str, ...]:
    try:
        return path.relative_to(root).parts
    except ValueError:
        return path.parts


def _rel_posix(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def is_path_excluded(path: Path, root: Path) -> bool:
    parts = _rel_parts(path, root)
    for part in parts:
        if part in ALLOWLIST_PATH_PARTS:
            return True
        for prefix in ALLOWLIST_PATH_PREFIXES:
            if part.startswith(prefix):
                return True
    return False


def is_evidence_file(path: Path, root: Path) -> bool:
    parts = _rel_parts(path, root)
    if not parts:
        return False
    if parts[0] != "evidence":
        return False
    # Only top-level evidence/*.json; archive subdirs filtered above already.
    return len(parts) == 2 and parts[1].endswith(".json")


def is_file_allowlisted(path: Path, root: Path) -> bool:
    return _rel_posix(path, root) in ALLOWLIST_FILES


def is_doc_migration_line(line: str) -> bool:
    for marker in ALLOWLIST_DOC_LINE_MARKERS:
        if marker in line:
            return True
    stripped = line.lstrip()
    return stripped.startswith("#") and any(
        word in line for word in ("historical", "archived", "migration")
    )


# ---------------------------------------------------------------------------
# Per-line classification
# ---------------------------------------------------------------------------


def classify_line(
    line: str,
    prev_lines: list[str],
    next_lines: list[str],
) -> list[str]:
    """Return list of category hits for this line."""
    if INLINE_PRAGMA in line:
        return []
    hits: list[str] = []
    context_window = "\n".join([*prev_lines, line, *next_lines])

    if RE_COMPUTE_LEXICAL_SCORE.search(line):
        hits.append(CAT_COMPUTE_LEXICAL_SCORE)
    elif RE_LEXICAL_SCORE.search(line):
        hits.append(CAT_LEXICAL_SCORE)

    # Verdict-context confidence: only structural occurrences, never English prose.
    if RE_CONFIDENCE_JSON_KEY.search(line) or RE_CONFIDENCE_ATTR.search(line):
        hits.append(CAT_VERDICT_CONFIDENCE)

    if RE_CONFIDENCE_IMPORT.search(line):
        hits.append(CAT_CONFIDENCE_IMPORT)

    if RE_SCHEMA_LITERAL_30.search(line):
        hits.append(CAT_SCHEMA_LITERAL_30)
    elif RE_STRING_30.search(line) and RE_SCHEMA_VERSION_KEY.search(context_window):
        hits.append(CAT_SCHEMA_VERSION_30)

    return hits


def scan_file(path: Path) -> list[Finding]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    lines = text.splitlines()
    out: list[Finding] = []
    for i, line in enumerate(lines):
        prev_lines = lines[max(0, i - 2) : i]
        next_lines = lines[i + 1 : i + 3]
        cats = classify_line(line, prev_lines, next_lines)
        if not cats:
            continue
        if is_doc_migration_line(line):
            continue
        for cat in cats:
            out.append(
                Finding(
                    path=path,
                    line_no=i + 1,
                    category=cat,
                    snippet=line.strip()[:200],
                )
            )
    return out


# ---------------------------------------------------------------------------
# Walk
# ---------------------------------------------------------------------------


def iter_text_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if is_path_excluded(path, root):
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        yield path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan the repo for v3.0 dead refs after the v3.1 migration."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Also fail on evidence/*.json files that are still v3.0. "
            "Off by default so the script can run before migration."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repo root to scan (default: cwd).",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args()
    root: Path = args.root.resolve()

    all_findings: list[Finding] = []
    evidence_findings: list[Finding] = []
    files_scanned = 0

    for path in iter_text_files(root):
        files_scanned += 1
        file_findings = scan_file(path)
        if not file_findings:
            continue
        if is_evidence_file(path, root):
            evidence_findings.extend(file_findings)
            continue
        if is_file_allowlisted(path, root):
            continue
        all_findings.extend(file_findings)

    # Report disallowed findings.
    for f in all_findings:
        rel = _rel_posix(f.path, root)
        print(f"{rel}:{f.line_no}: {f.category} {f.snippet}")

    # Per-category summary.
    by_cat: dict[str, int] = {c: 0 for c in CATEGORIES}
    for f in all_findings:
        by_cat[f.category] = by_cat.get(f.category, 0) + 1
    by_cat[CAT_EVIDENCE_FILE_30] = len({f.path for f in evidence_findings})

    print()
    print(f"Files scanned: {files_scanned}")
    print(f"Disallowed findings: {len(all_findings)}")
    print(f"Evidence v3.0 files (counted separately): {by_cat[CAT_EVIDENCE_FILE_30]}")
    print("Findings by category:")
    for cat in CATEGORIES:
        print(f"  {cat}: {by_cat.get(cat, 0)}")

    failed = len(all_findings) > 0
    if args.strict and by_cat[CAT_EVIDENCE_FILE_30] > 0:
        failed = True
        print()
        print("--strict: evidence/*.json v3.0 files counted as failure.")

    if failed:
        total_bad = len(all_findings) + (
            by_cat[CAT_EVIDENCE_FILE_30] if args.strict else 0
        )
        print(f"VERIFICATION FAILED: {total_bad} issues")
        return 1
    print("VERIFICATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
