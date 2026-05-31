"""Mechanically check questions.json for verdict pre-loading, confessional-
vocabulary smuggling, stale schema fields, and out-of-enum metadata.

Usage:
    python -m tools.verify_questions             # run full check
    python -m tools.verify_questions --report    # write questions-hygiene-report.md (exit 0)
    python -m tools.verify_questions --quiet     # silent; exit code = flagged stem count

Default exit code = number of stem-level flags. --report always exits 0.
Schema integrity failures (stale tier, bad historical_consensus enum) raise
SystemExit(2) regardless of --report so CI catches them.

Flags surfaced (stem-level):
- VERDICT_PRELOADED: statement asserts the answer.
- CONFESSIONAL_VOCAB: statement uses Reformed-confessional shorthand.
- META_FRAMING: statement frames the question as legitimacy claim.
- NAMED_CARRIERS: statement names specific cult/heretical groups inline.

Schema checks (fail-fast):
- STALE_TIER_FIELD: any question carries a `tier` key (abolished 2026-05-10).
- BAD_HISTORICAL_CONSENSUS: value is outside the v3.1 enum.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "questions.json"


# --- Heuristic patterns ---------------------------------------------------

# Named cult/heretical-group carriers that should NOT appear in the statement
NAMED_CARRIER_PATTERNS = [
    r"\bMormon(?:ism)?\b",
    r"\bLDS\b",
    r"\bBook of Mormon\b",
    r"\bJehovah's Witness(?:es)?\b",
    r"\bWatchtower\b",
    r"\bWatch Tower\b",
    r"\bChristian Science\b",
    r"\bIglesia ni Cristo\b",
    r"\bManalo\b",
    r"\bEllen G\.? White\b",
    r"\bSeventh-day Adventist\b",
    r"\bChildren of God\b",
    r"\bMo Letters\b",
    r"\bBranham(?:ism)?\b",
    r"\bWord-Faith\b",
    r"\bWord of Faith\b",
    r"\bUnification(?: Church)?\b",
    r"\bDivine Principle\b",
    r"\bICC\b",
    r"\bInternational Churches of Christ\b",
    r"\bBritish Israelism\b",
    r"\bSerpent Seed\b",
    r"\bRoman Catholic(?:ism)?\b",
    r"\bHyper-Calvinis(?:m|t)\b",
]

# Verdict words inside the statement
VERDICT_WORDS = [
    r"\bis (?:cult-grade|heresy|heretical|heterodox|unbiblical|false gospel)\b",
    r"\bare (?:cult-grade|heresy|heretical|heterodox|unbiblical|false gospel)\b",
    r"\bis (?:rejected|denied|refuted) by Scripture\b",
    r"\bcorrupts? the gospel\b",
    r"\bis a damning error\b",
    r"\bdenial (?:of [\w\s]+ )?(?:is|=) cult-grade\b",
    r"\bcult-grade error\b",
]

# Reformed-confessional vocabulary used as if neutral
CONFESSIONAL_VOCAB = [
    r"\bsola fide\b",
    r"\bsola gratia\b",
    r"\bsolus christus\b",
    r"\bsola scriptura\b",
    r"\bsoli Deo gloria\b",
    r"\bimputed righteousness\b",
    r"\bimputation\b",
    r"\bforensic justification\b",
    r"\bforensic\b",
    r"\bperspicuity\b",
    r"\bregulative principle\b",
    r"\bcovenant of grace\b",
    r"\bcovenant of works\b",
    r"\bex opere operato\b",
    r"\bpropitiat(?:e|ing|ion)\b",
    r"\bex cathedra\b",
]

# Meta-acceptability framing
META_FRAMING = [
    r"\bis a legitimate (?:orthodox )?position\b",
    r"\bis the historic Brethren position\b",
    r"\bis the historic position of\b",
    r"\bis a defensible position\b",
    r"\bis tenable\b",
]


def _compile_all(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_RE_NAMED = _compile_all(NAMED_CARRIER_PATTERNS)
_RE_VERDICT = _compile_all(VERDICT_WORDS)
_RE_CONF = _compile_all(CONFESSIONAL_VOCAB)
_RE_META = _compile_all(META_FRAMING)


HISTORICAL_CONSENSUS_ENUM = frozenset(
    {
        "unanimous_lineages",
        "divided_lineages",
        "minority_lineages",
        "outside_majority_lineages",
        "outside_historic_christianity",
    }
)


def schema_integrity_check(questions: list[dict]) -> list[str]:
    """Return a list of fatal schema errors. Empty list means PASS."""
    errors: list[str] = []
    for q in questions:
        if "tier" in q:
            errors.append(f"{q['id']}: STALE_TIER_FIELD (tier abolished 2026-05-10)")
        hc = q.get("historical_consensus")
        if hc is not None and hc not in HISTORICAL_CONSENSUS_ENUM:
            errors.append(
                f"{q['id']}: BAD_HISTORICAL_CONSENSUS {hc!r} "
                f"(allowed: {sorted(HISTORICAL_CONSENSUS_ENUM)})"
            )
    return errors


def _hits(text: str, regexes: list[re.Pattern]) -> list[str]:
    out: list[str] = []
    for r in regexes:
        for m in r.finditer(text or ""):
            out.append(m.group(0))
    return out


# --- Main check -----------------------------------------------------------


def audit_question(q: dict) -> list[tuple[str, list[str]]]:
    """Return list of (flag_name, matched_substrings) for one question."""
    statement = q.get("statement", "") or ""
    flags: list[tuple[str, list[str]]] = []

    named = _hits(statement, _RE_NAMED)
    if named:
        flags.append(("NAMED_CARRIERS", named))

    verdicts = _hits(statement, _RE_VERDICT)
    if verdicts:
        flags.append(("VERDICT_PRELOADED", verdicts))

    confessional = _hits(statement, _RE_CONF)
    if confessional:
        flags.append(("CONFESSIONAL_VOCAB", confessional))

    meta = _hits(statement, _RE_META)
    if meta:
        flags.append(("META_FRAMING", meta))

    return flags


def audit_all() -> list[dict]:
    """Audit all questions; returns list of {id, statement, flags}."""
    raw = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    questions = raw["questions"]
    results: list[dict] = []
    for q in questions:
        flags = audit_question(q)
        if flags:
            results.append(
                {
                    "id": q["id"],
                    "category": q.get("category"),
                    "subcategory": q.get("subcategory"),
                    "statement": q.get("statement", ""),
                    "flags": flags,
                }
            )
    return results


def write_report(results: list[dict], total: int) -> None:
    out = ROOT / "questions-hygiene-report.md"
    lines = ["# questions-hygiene-report.md", ""]
    lines.append(f"Audited **{total}** questions in `questions.json`.")
    lines.append(f"**{len(results)}** flagged.")
    lines.append("")
    by_flag: dict[str, int] = {}
    for r in results:
        for fname, _ in r["flags"]:
            by_flag[fname] = by_flag.get(fname, 0) + 1
    if by_flag:
        lines.append("## Flag distribution")
        for k, v in sorted(by_flag.items(), key=lambda x: -x[1]):
            lines.append(f"- {k}: {v}")
        lines.append("")
    lines.append("## Per-question flags")
    lines.append("")
    for r in results:
        cat = f"{r['category']}"
        if r["subcategory"]:
            cat += f" › {r['subcategory']}"
        lines.append(f"### {r['id']}: {cat}")
        lines.append(f"> {r['statement']}")
        lines.append("")
        for fname, hits in r["flags"]:
            joined = ", ".join(f"`{h}`" for h in hits[:8])
            lines.append(f"- **{fname}**: {joined}")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--report", action="store_true", help="Write questions-hygiene-report.md")
    p.add_argument("--quiet", action="store_true", help="Exit code only; no per-question output")
    args = p.parse_args()

    raw = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    total = len(raw["questions"])

    schema_errors = schema_integrity_check(raw["questions"])
    if schema_errors:
        for err in schema_errors:
            print(f"[SCHEMA] {err}", file=sys.stderr)
        return 2

    results = audit_all()

    if not args.quiet:
        for r in results:
            cat = r["category"] + (f"/{r['subcategory']}" if r["subcategory"] else "")
            flag_summary = ", ".join(f for f, _ in r["flags"])
            print(f"[FLAG] {r['id']} ({cat}): {flag_summary}")

    print(f"\n{len(results)} flagged of {total} ({len(results)/total*100:.1f}%)")

    if args.report:
        write_report(results, total)
        print("wrote questions-hygiene-report.md")
        return 0

    return len(results)


if __name__ == "__main__":
    sys.exit(main())
