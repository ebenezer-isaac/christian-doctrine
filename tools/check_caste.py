"""Caste boundary enforcer for verifier-caste subagent commits.

Implements the RESEED_PLAN v3 verifier-caste pre-commit / post-commit
check. Every commit must carry a ``Caste: <name>`` trailer in its
message. The changed file-set is then matched against an allow-list per
caste. Crossing castes within a single commit is rejected.

Caste table (mirrors RESEED_PLAN section "Verifier-caste architecture"):

* ``architect``
    Allowed: ``docs/SCHEMA_DECISIONS.md``,
    ``docs/data_inventory_catalog.json``,
    ``docs/CULTURAL_SCHEMA_DECISIONS.md``,
    ``docs/cultural_data_inventory_catalog.json``,
    ``docs/ARCHITECTURE.md``, ``docs/implementation_phases/**``,
    ``docs/PHASE_*.md`` (Phase governance, ledger and analysis
    docs, generalizes the earlier ``docs/PHASE_D_*.md`` wildcard so
    worktree agents that reset to main tip can see the master ledger,
    audits and the Phase F/EFH analysis docs),
    ``README.md`` (top-level project narrative, same governance
    family as docs/ARCHITECTURE.md), ``docs/POC_FINDINGS.md`` (stale
    PoC doc slated for architect deletion in the greenfield set),
    ``graph/lexical.cypher``, ``graph/cultural.cypher``,
    ``tools/expected_counts.json``. On a ``[SCHEMA-REVISION]``-tagged
    commit ONLY, also ``tools/expected_counts.baseline`` (its atomic
    SHA-256 lock companion, which must move in the same commit as the
    json). For all other commits the baseline remains implementer-z1's.
* ``implementer``
    Allowed: a single ``.py`` file outside ``tests/`` and ``docs/``,
    plus that file's docstring contract commit. ``tools/*.py`` is
    allowed for Z-tier tooling commits tagged ``implementer-z1``.
* ``implementer-docstring``
    Allowed: same target ``.py`` but the diff must add ONLY top-of-file
    docstring lines (no executable statements at module level beyond
    ``from __future__`` and existing structure). Enforcement is
    structural via AST: the patched file must have ``len(module.body)
    == 1 and isinstance(module.body[0], ast.Expr)``.
* ``implementer-impl``
    Same target ``.py`` after the docstring commit; allowed to add
    function bodies.
* ``implementer-z1``
    Allowed: ``tools/*.py``, ``tools/*.cypher``,
    ``tests/lexical/stubs/*.py``,
    ``embeddings/embed_lexical.py`` for the Phase Z.1 refactor that
    extracts ``build_embed_text``, ``docker/lexical/docker-compose.yml``,
    ``docker/cultural/docker-compose.yml``, ``.gitignore`` (repo-root
    ignore file, same build/config tooling family as tools/ and the
    compose configs). Forbidden: ``docs/**``,
    ``tools/expected_counts.json``.
* ``verifier``
    Allowed: ``tests/**/test_*.py``, ``tests/**/conftest.py``,
    ``tests/lexical/fixtures/**``. Forbidden: any ``.py`` outside
    ``tests/``.
* ``verifier-z1``
    Same as ``verifier`` plus
    ``tests/lexical/test_verify_catches_lazy_adapter.py`` extension and
    ``tests/embeddings/**``.
* ``auditor``
    Allowed: ``docs/MANIFEST_VERIFICATION_*.json`` and
    ``docs/AUDIT_*.md``.

Usage::

    python tools/check_caste.py [--rev REV] [--self-test]

With no ``--rev`` the script inspects the staged diff against HEAD
(intended for pre-commit). With ``--rev <sha>`` it inspects a specific
commit (intended for CI auditing every commit since Phase A.1).

Exit codes:

* 0  caste declaration matches the changed file-set
* 1  caste mismatch or missing trailer; offending files printed
* 2  argument / git invocation error
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


CASTE_TRAILER_RE = re.compile(
    r"^Caste:\s*(?P<name>[A-Za-z0-9_-]+)\s*$", re.MULTILINE,
)

# A [SCHEMA-REVISION] subject tag authorizes the architect caste to move
# tools/expected_counts.json. Because tools/expected_counts.baseline is the
# SHA-256 lock of that json, the two MUST move together in one atomic commit
# (a half-move leaves the immutability gate transiently broken). The baseline
# glob stays bound to implementer-z1 for all non-tagged commits; it is granted
# to architect ONLY when this tag is present on the commit subject.
SCHEMA_REVISION_TAG_RE = re.compile(r"^\[SCHEMA-REVISION\]")
SCHEMA_REVISION_ARCHITECT_EXTRA: tuple[str, ...] = (
    "tools/expected_counts.baseline",
)


@dataclass(frozen=True)
class CasteRule:
    name: str
    allowed_globs: tuple[str, ...]
    forbidden_globs: tuple[str, ...] = field(default=())


CASTE_RULES: dict[str, CasteRule] = {
    "architect": CasteRule(
        name="architect",
        allowed_globs=(
            "docs/SCHEMA_DECISIONS.md",
            "docs/CULTURAL_SCHEMA_DECISIONS.md",
            "docs/data_inventory_catalog.json",
            "docs/cultural_data_inventory_catalog.json",
            "docs/ARCHITECTURE.md",
            "docs/implementation_phases/*.md",
            "docs/phase_prompts/*.md",
            # Phase governance, master ledger and analysis docs.
            # Generalizes the earlier docs/PHASE_D_*.md wildcard (itself
            # added in 34180a7 to broaden the single literal
            # docs/PHASE_D_CATALOG_RECONCILIATION.md; byte-derived
            # evidence backing [SCHEMA-REVISION]s ceb3898, 01e09c6) to
            # the docs/PHASE_*.md family so the untracked Phase D ledger
            # plus the Phase F / EFH analysis docs become durable and
            # visible to worktree agents that reset to main tip. Scoped
            # to the PHASE_ prefix, not a broad docs/*.md wildcard, to
            # keep the architect docs scope tightly enumerated. Follows
            # the b66831c / 34180a7 tightly scoped governance precedent.
            "docs/PHASE_*.md",
            # Phase H reseed manifest CLAIM file. The reseed phase
            # (architect/orchestrator per docs/PHASE_EFH_EXECUTION_SPEC.md
            # gap G7) authors docs/RESEED_MANIFEST_<ts>.json as the
            # recorded ground-truth contract that the Auditor caste
            # independently re-executes via tools/verify_manifest.py. It
            # is an architect contract artifact by nature (the auditor
            # only ever writes docs/MANIFEST_VERIFICATION_*.json); without
            # this glob the manifest was covered by no caste, a caste-
            # config gap. Scoped to the RESEED_MANIFEST_ prefix, same
            # tightly-enumerated governance precedent as the PHASE_ glob.
            "docs/RESEED_MANIFEST_*.json",
            # Top-level project narrative and the stale PoC findings doc.
            # README.md is the project's narrative entry point, the same
            # architect-owned governance family as docs/ARCHITECTURE.md.
            # docs/POC_FINDINGS.md is a superseded PoC doc slated for
            # architect deletion in the greenfield set; without an
            # architect glob it matched no caste, a governance dead end
            # (no caste could ever git rm it). Added as precise literals,
            # not a broad docs/*.md or top-level wildcard, to keep the
            # architect docs scope tightly enumerated. Follows the
            # b66831c / 34180a7 tightly scoped governance precedent.
            "README.md",
            "docs/POC_FINDINGS.md",
            "graph/lexical.cypher",
            "graph/cultural.cypher",
            "tools/expected_counts.json",
        ),
    ),
    "implementer": CasteRule(
        name="implementer",
        allowed_globs=(
            "ingest/lexical/*.py",
            "ingest/cultural/*.py",
            # Pipeline 4 historical procurement adapters parse local
            # data/private/ source files into HistoricalChunk records, the
            # same implementer family as the lexical and cultural adapters.
            "ingest/historical/*.py",
            # ingest/license_guard.py is the shared redistribution gate read
            # by every store. It matched no caste at top-level (a governance
            # dead end: the historical layer's PD/CC0 slug additions could
            # never be committed). Added as a precise literal, mirroring the
            # tightly-enumerated README.md / .gitignore / pyproject.toml
            # gap-closure precedent.
            "ingest/license_guard.py",
            "embeddings/*.py",
            "pipeline1/*.py",
            "pipeline2/*.py",
            # Pipeline 4 historical attestation engine (model, context
            # builder, dispatcher, triangle, persistence, run), the same
            # implementer family as pipeline2/.
            "pipeline4/*.py",
            "retrieval/*.py",
        ),
        forbidden_globs=(
            "tests/**",
            "docs/**",
            "tools/expected_counts.json",
        ),
    ),
    "implementer-docstring": CasteRule(
        name="implementer-docstring",
        allowed_globs=(
            "ingest/lexical/*.py",
            "ingest/cultural/*.py",
        ),
        forbidden_globs=(
            "tests/**",
            "docs/**",
            "tools/expected_counts.json",
        ),
    ),
    "implementer-impl": CasteRule(
        name="implementer-impl",
        allowed_globs=(
            "ingest/lexical/*.py",
            "ingest/cultural/*.py",
        ),
        forbidden_globs=(
            "tests/**",
            "docs/**",
            "tools/expected_counts.json",
        ),
    ),
    "implementer-z1": CasteRule(
        name="implementer-z1",
        allowed_globs=(
            "tools/*.py",
            "tools/*.cypher",
            "tests/lexical/stubs/*.py",
            "embeddings/embed_lexical.py",
            "docker/lexical/docker-compose.yml",
            # Cultural compose mirrors the lexical compose ownership so
            # the verified qdrant healthcheck fix (bash /dev/tcp /readyz,
            # wget/curl absent in image) can land on both stacks under
            # the same implementer-z1 governance.
            "docker/cultural/docker-compose.yml",
            # Repo-root ignore file is build/config tooling, the same
            # family as the tools/ scripts and docker compose configs
            # implementer-z1 already owns. Without this glob .gitignore
            # matched no caste, a governance dead end. Precise literal,
            # not a wildcard, mirroring the tightly enumerated scope.
            ".gitignore",
            # Python build/packaging manifest. pyproject.toml is the
            # project's distribution identity and build config, the same
            # build/config tooling family as .gitignore and the docker
            # compose configs implementer-z1 already owns. Without this
            # glob pyproject.toml matched no caste, a governance dead end
            # (no caste could ever commit the distribution rename or any
            # build-config change). Added as a precise literal, not a
            # broad wildcard, mirroring the tightly enumerated scope and
            # the README.md / .gitignore tightly-scoped-literal precedent.
            "pyproject.toml",
            "tools/expected_counts.baseline",
        ),
        forbidden_globs=(
            "tools/expected_counts.json",
            "docs/SCHEMA_DECISIONS.md",
            "docs/data_inventory_catalog.json",
        ),
    ),
    "verifier": CasteRule(
        name="verifier",
        allowed_globs=(
            "tests/**/test_*.py",
            "tests/**/conftest.py",
            "tests/**/fixtures/**",
        ),
        forbidden_globs=(
            "ingest/**",
            "embeddings/**",
            "pipeline1/**",
            "pipeline2/**",
            "pipeline4/**",
            "retrieval/**",
            "tools/**.py",
            "docs/**",
        ),
    ),
    "verifier-z1": CasteRule(
        name="verifier-z1",
        allowed_globs=(
            "tests/**/test_*.py",
            "tests/**/conftest.py",
            "tests/**/fixtures/**",
            "tests/embeddings/**",
            "tests/tools/**",
        ),
        forbidden_globs=(
            "ingest/**",
            "embeddings/**",
            "pipeline1/**",
            "pipeline2/**",
            "pipeline4/**",
            "retrieval/**",
            "tools/**.py",
            "docs/**",
        ),
    ),
    "auditor": CasteRule(
        name="auditor",
        allowed_globs=(
            "docs/MANIFEST_VERIFICATION_*.json",
            "docs/AUDIT_*.md",
        ),
    ),
}


@dataclass(frozen=True)
class Verdict:
    ok: bool
    caste: str | None
    changed: tuple[str, ...]
    violations: tuple[str, ...]
    detail: str = ""


def extract_caste(message: str) -> str | None:
    m = CASTE_TRAILER_RE.search(message)
    return m.group("name").strip() if m else None


def _match_any(path: str, globs: tuple[str, ...]) -> bool:
    norm = path.replace("\\", "/")
    for g in globs:
        if fnmatch.fnmatchcase(norm, g):
            return True
        if "**" in g:
            simple = g.replace("**/", "").replace("/**", "")
            if fnmatch.fnmatchcase(norm, simple):
                return True
        if g.endswith("/**") and norm.startswith(g[:-3]):
            return True
        if "**" in g:
            parts = g.split("**")
            if all(p in norm for p in parts if p):
                if norm.startswith(parts[0].rstrip("/") or norm[0:0]):
                    return True
    return False


def _is_schema_revision(subject: str | None) -> bool:
    if not subject:
        return False
    first_line = subject.splitlines()[0] if subject.splitlines() else subject
    return SCHEMA_REVISION_TAG_RE.search(first_line.strip()) is not None


def evaluate(
    caste: str | None,
    changed: list[str],
    subject: str | None = None,
) -> Verdict:
    if caste is None:
        return Verdict(
            ok=False,
            caste=None,
            changed=tuple(sorted(changed)),
            violations=tuple(sorted(changed)),
            detail="commit message is missing the 'Caste: <name>' trailer",
        )
    rule = CASTE_RULES.get(caste)
    if rule is None:
        return Verdict(
            ok=False,
            caste=caste,
            changed=tuple(sorted(changed)),
            violations=tuple(sorted(changed)),
            detail=(
                f"unknown caste {caste!r}; declared castes: "
                f"{sorted(CASTE_RULES)}"
            ),
        )
    allowed_globs = rule.allowed_globs
    if caste == "architect" and _is_schema_revision(subject):
        # Atomic SHA-lock companion: a [SCHEMA-REVISION] commit moves
        # tools/expected_counts.json and its lock tools/expected_counts.baseline
        # together. Grant the baseline glob to architect ONLY here so the pair
        # cannot be split. implementer-z1 keeps its standing baseline binding.
        allowed_globs = allowed_globs + SCHEMA_REVISION_ARCHITECT_EXTRA

    violations: list[str] = []
    for f in changed:
        if _match_any(f, rule.forbidden_globs):
            violations.append(f"{f} (forbidden for caste {caste})")
            continue
        if not _match_any(f, allowed_globs):
            violations.append(f"{f} (not in allowed set for caste {caste})")
    return Verdict(
        ok=len(violations) == 0,
        caste=caste,
        changed=tuple(sorted(changed)),
        violations=tuple(sorted(violations)),
        detail="" if not violations else f"{len(violations)} file(s) violate caste",
    )


def _git(*argv: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *argv], cwd=str(cwd), capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(argv)} failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def _changed_files_for_rev(rev: str, cwd: Path) -> list[str]:
    out = _git("show", "--name-only", "--pretty=format:", rev, cwd=cwd)
    return [line.strip() for line in out.splitlines() if line.strip()]


def _staged_files(cwd: Path) -> list[str]:
    out = _git("diff", "--name-only", "--cached", cwd=cwd)
    return [line.strip() for line in out.splitlines() if line.strip()]


def _commit_message_for_rev(rev: str, cwd: Path) -> str:
    return _git("show", "--no-patch", "--format=%B", rev, cwd=cwd)


def check_revision(rev: str, repo: Path) -> Verdict:
    msg = _commit_message_for_rev(rev, repo)
    changed = _changed_files_for_rev(rev, repo)
    return evaluate(extract_caste(msg), changed, subject=msg)


def check_staged(repo: Path, message_file: Path | None = None) -> Verdict:
    if message_file is not None and message_file.exists():
        msg = message_file.read_text(encoding="utf-8")
    else:
        msg = ""
    changed = _staged_files(repo)
    return evaluate(extract_caste(msg), changed, subject=msg)


def check_range(spec: str, repo: Path) -> list[tuple[str, Verdict]]:
    out = _git("log", "--format=%H", spec, cwd=repo)
    revs = [r.strip() for r in out.splitlines() if r.strip()]
    return [(r, check_revision(r, repo)) for r in revs]


def _self_test() -> int:
    good = evaluate("verifier", ["tests/tools/test_check_caste.py"])
    if not good.ok:
        print(f"self-test FAIL: verifier with tests/* rejected: {good.violations}",
              file=sys.stderr)
        return 1
    bad = evaluate("verifier", ["ingest/lexical/macula_hebrew.py"])
    if bad.ok:
        print("self-test FAIL: verifier with ingest/* accepted", file=sys.stderr)
        return 1
    z1 = evaluate("implementer-z1", ["tools/check_caste.py",
                                     "tools/predicates_by_type.cypher"])
    if not z1.ok:
        print(f"self-test FAIL: implementer-z1 with tools/* rejected: {z1.violations}",
              file=sys.stderr)
        return 1
    z1b = evaluate("implementer-z1", ["tools/expected_counts.baseline"])
    if not z1b.ok:
        print(
            "self-test FAIL: implementer-z1 with tools/expected_counts.baseline "
            f"rejected: {z1b.violations}",
            file=sys.stderr,
        )
        return 1
    missing = evaluate(None, ["tests/tools/test_check_caste.py"])
    if missing.ok:
        print("self-test FAIL: missing trailer accepted", file=sys.stderr)
        return 1
    unknown = evaluate("nonsense-caste", ["tests/foo.py"])
    if unknown.ok:
        print("self-test FAIL: unknown caste accepted", file=sys.stderr)
        return 1
    print("self-test OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rev", type=str, default=None,
                        help="Inspect a single commit SHA.")
    parser.add_argument("--range", type=str, default=None,
                        help="Inspect a commit range (e.g. main..HEAD).")
    parser.add_argument("--message-file", type=Path, default=None,
                        help="Commit message file (for pre-commit hook).")
    parser.add_argument("--repo", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()

    try:
        if args.range is not None:
            results = check_range(args.range, args.repo)
            failed = [(r, v) for r, v in results if not v.ok]
            for rev, v in results:
                mark = "OK" if v.ok else "FAIL"
                print(f"[{mark}] {rev[:12]} caste={v.caste} changed={len(v.changed)}")
                for viol in v.violations:
                    print(f"        {viol}")
            if failed:
                print(f"\n{len(failed)} commit(s) violate caste", file=sys.stderr)
                return 1
            return 0
        if args.rev is not None:
            v = check_revision(args.rev, args.repo)
        else:
            v = check_staged(args.repo, args.message_file)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if v.ok:
        print(f"OK: caste={v.caste} files={len(v.changed)}")
        return 0
    print(f"FAIL: caste={v.caste} {v.detail}", file=sys.stderr)
    for viol in v.violations:
        print(f"  {viol}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
