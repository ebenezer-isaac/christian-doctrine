"""doctrinal_verdict: a plain-language verdict plus optional full diagnostics.

The tool resolves a proposition to a stored question, then assembles three
blocks that are never fused:

  1. lexical verdict   - authoritative, read verbatim from evidence/<id>.json (Pipeline 2)
  2. cultural overlay   - diagnostic, retrieved live from the cultural store
  3. historical attestation - diagnostic, read from historical/<id>.json (Pipeline 4)

The server does no synthesis of its own: it assembles structured data and the
calling model reasons over it. Because the verdict is read straight from the
stored evidence file, it cannot drift; there is no query-time re-derivation.

Response shape is controlled by ``verbosity``:

  * ``summary`` (default) - a compact, human-readable answer: a yes/no, a plain
    explanation, the key scriptures, and short diagnostic summaries with
    pointers to the drill-down tools. Small enough to never overflow a client.
  * ``full`` - additionally embeds the complete lexical, cultural, and (slimmed)
    historical blocks for export or programmatic use.

The query-time air-gap holds: the lexical block comes only from the evidence
file, and the cultural and historical blocks ride alongside as separate blocks
with separate license stacks. A non-redistributable source in any block folds
into the envelope license audit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import Context
from pydantic import Field

from cd_mcp.question_match import classify, load_question_index
from cd_mcp.runtime import app_context
from cd_mcp.runtime import cultural_chunks as retrieve_chunks
from cd_mcp.tools._common import (
    CallerContext,
    ToolInputBase,
    error_envelope,
    success_envelope,
    validate_question_id,
)
from cd_mcp.tools.cultural_overlay import build_cultural_overlay
from pipeline4.historical_schema import HistoricalAttestation

TOOL_NAME = "doctrinal_verdict"
EVIDENCE_DIR = Path("evidence")
HISTORICAL_DIR = Path("historical")

Verbosity = Literal["summary", "full"]

# How many items the summary surfaces before deferring to a drill-down tool.
MAX_KEY_SCRIPTURES = 8
MAX_ALSO_WEIGHED = 3
MAX_TOP_WITNESSES = 2
MAX_CULTURAL_EXAMPLES = 2
# Hard cap per "also weighed" note so one verbose resolution cannot bloat the summary.
MAX_ALSO_WEIGHED_CHARS = 240


class DoctrinalVerdictInput(ToolInputBase):
    proposition: str = Field(min_length=1)
    denominations: list[str] | None = None
    depth: Literal["fast", "deep"] = "fast"
    verbosity: Verbosity = "summary"
    progressToken: str | None = None  # noqa: N815  MCP-protocol field, camelCase required


# ---------------------------------------------------------------------------
# Historical block (Pipeline 4 sidecar)
# ---------------------------------------------------------------------------


def _empty_historical_block() -> dict[str, Any]:
    return {
        "attestation_present": False,
        "witnesses": [],
        "summary": "",
        "license_audit": {
            "sources_used": [],
            "evidence_safe_to_publish": True,
            "non_redistributable_reason": None,
        },
        "flags": [],
    }


def load_historical_block(
    qid: str, historical_dir: Path | None = None
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Read and validate historical/<qid>.json. Returns (block, witness sources).

    The witness sources are mapped into the envelope ``sources_used`` shape so a
    non-redistributable witness (for example a DSS CC-BY-NC-4.0 source) folds
    into ``response_safe_to_share``. A missing sidecar yields the empty block
    (most of the 231 questions carry no attestation). The question_id is
    validated here so a directly imported call cannot traverse outside the
    historical directory.
    """
    qid = validate_question_id(qid)
    path = (historical_dir or HISTORICAL_DIR) / f"{qid}.json"
    if not path.exists():
        return _empty_historical_block(), []
    attestation = HistoricalAttestation.model_validate(json.loads(path.read_text(encoding="utf-8")))
    dumped = attestation.model_dump(mode="json", by_alias=True)
    block = {
        "attestation_present": dumped["attestation_present"],
        "witnesses": dumped["witnesses"],
        "summary": dumped["summary"],
        "license_audit": dumped["license_audit"],
        "flags": dumped["flags"],
    }
    sources = [
        {"source": src["source_slug"], "license": src["license"]}
        for src in dumped["license_audit"]["sources_used"]
    ]
    return block, sources


# ---------------------------------------------------------------------------
# Lexical block (Pipeline 2 evidence) and proposition classification
# ---------------------------------------------------------------------------


def _build_lexical_block(evidence: dict[str, Any], qid: str) -> dict[str, Any]:
    """Assemble the full lexical-evidence block from the stored evidence file."""
    verdict = evidence.get("verdict", {})
    lexical = dict(evidence.get("lexical_evidence", {}) or {})
    lexical.update(
        {
            "rationale": verdict.get("rationale"),
            "lay_summary": evidence.get("lay_summary"),
            "pan_canonical": verdict.get("pan_canonical"),
            "variant_robust": verdict.get("variant_robust"),
            "source_evidence_files": [f"evidence/{qid}.json"],
        }
    )
    return lexical


# ---------------------------------------------------------------------------
# Plain-language summarizers (the off-the-bat experience)
# ---------------------------------------------------------------------------

# OSIS-style book codes that need a friendlier rendering. Codes not listed pass
# through unchanged (most are already readable, e.g. Deut, Isa, John, Col).
_BOOK_LABELS = {
    "1Tim": "1 Tim",
    "2Tim": "2 Tim",
    "1Cor": "1 Cor",
    "2Cor": "2 Cor",
    "1John": "1 John",
    "2John": "2 John",
    "3John": "3 John",
    "1Pet": "1 Pet",
    "2Pet": "2 Pet",
    "Jas": "James",
    "Phil": "Phil",
    "Rom": "Rom",
    "Ps": "Ps",
}


def _humanize_ref(ref: str) -> str:
    """Turn an OSIS-ish ref like ``1Tim.2.5`` into ``1 Tim 2:5``."""
    parts = (ref or "").split(".")
    if not parts or not parts[0]:
        return ref
    book = _BOOK_LABELS.get(parts[0], parts[0])
    if len(parts) >= 3:
        return f"{book} {parts[1]}:{parts[2]}"
    if len(parts) == 2:
        return f"{book} {parts[1]}"
    return book


def _key_scriptures(lexical: dict[str, Any]) -> list[str]:
    """Up to MAX_KEY_SCRIPTURES human-readable refs, order-preserving and deduped."""
    raw = lexical.get("scripture") or []
    seen: list[str] = []
    for item in raw:
        ref = item.get("ref") if isinstance(item, dict) else item
        human = _humanize_ref(str(ref))
        if human and human not in seen:
            seen.append(human)
        if len(seen) >= MAX_KEY_SCRIPTURES:
            break
    return seen


def _first_sentence(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    head = text.split(". ", 1)[0].strip()
    return head if head.endswith(".") else head + "."


def _plain_answer(verdict: bool | None) -> str:
    if verdict is True:
        return "Yes"
    if verdict is False:
        return "No"
    return "Uncertain"


def _headline(verdict: bool | None, proposition: str) -> str:
    answer = _plain_answer(verdict)
    if verdict is True:
        return f'{answer}. The biblical-language evidence supports this: "{proposition}"'
    if verdict is False:
        return f'{answer}. The biblical-language evidence does not support this: "{proposition}"'
    return f'{answer}. The evidence is not decisive on: "{proposition}"'


_BREADTH_PLAIN = {
    "canon_wide": "the supporting texts span the whole Bible",
    "broad": "the supporting texts are spread across many books",
    "partial": "the support comes from a limited set of passages",
    "thin": "the support rests on very few passages",
}
_DIRECTNESS_PLAIN = {
    "direct": "and the texts state it directly",
    "inferred": "and it follows by inference from the texts",
    "analogical": "and it rests on analogy from the texts",
    "silent": "and the texts do not address it head-on",
}


def _plain_confidence(breadth: str | None, directness: str | None) -> str:
    b = _BREADTH_PLAIN.get(breadth or "", "the breadth of support is unclassified")
    d = _DIRECTNESS_PLAIN.get(directness or "", "")
    return f"{b}{(' ' + d) if d else ''}.".capitalize()


def _also_weighed(lexical: dict[str, Any]) -> list[str]:
    """Short notes on texts that look like counter-evidence but were addressed."""
    out: list[str] = []
    for ct in lexical.get("complicating_texts") or []:
        if not isinstance(ct, dict):
            continue
        ref = _humanize_ref(str(ct.get("ref", "")))
        note = _first_sentence(str(ct.get("resolution", "")))
        if len(note) > MAX_ALSO_WEIGHED_CHARS:
            note = note[: MAX_ALSO_WEIGHED_CHARS - 1].rstrip() + "…"
        if ref and note:
            out.append(f"{ref}: {note}")
        if len(out) >= MAX_ALSO_WEIGHED:
            break
    return out


def _summarize_cultural(cultural_block: dict[str, Any]) -> dict[str, Any]:
    """Stance counts plus a couple of paraphrased examples; no raw snippets."""
    passages = cultural_block.get("passages") or []
    stances: dict[str, int] = {}
    examples: list[dict[str, Any]] = []
    for p in passages:
        stance = p.get("stance") or "unstated"
        stances[stance] = stances.get(stance, 0) + 1
        if len(examples) < MAX_CULTURAL_EXAMPLES:
            examples.append(
                {
                    "tradition": p.get("tradition"),
                    "source": p.get("source"),
                    "stance": stance,
                    "paraphrase": p.get("tradition_paraphrase_if_not_redistributable")
                    or p.get("snippet"),
                }
            )
    return {
        "note": "Diagnostic only. The cultural overlay never changes the verdict.",
        "traditions_by_stance": stances,
        "examples": examples,
        "full_detail": "Call the cultural_overlay tool for all passages.",
    }


def _summarize_historical(historical_block: dict[str, Any], qid: str) -> dict[str, Any]:
    witnesses = historical_block.get("witnesses") or []
    ranked = sorted(witnesses, key=lambda w: w.get("confidence", 0), reverse=True)
    top = []
    for w in ranked[:MAX_TOP_WITNESSES]:
        src = w.get("source", {}) if isinstance(w.get("source"), dict) else {}
        top.append(
            {
                "witness_id": w.get("witness_id"),
                "author": src.get("author"),
                "work": src.get("work_title"),
                "date": src.get("date_written_range"),
                "confidence": w.get("confidence"),
                "attestation_type": w.get("attestation_type"),
            }
        )
    return {
        "note": "Diagnostic only. Historical attestation never changes the verdict.",
        "attestation_present": historical_block.get("attestation_present", False),
        "witness_count": len(witnesses),
        "summary": historical_block.get("summary", ""),
        "top_witnesses": top,
        "full_detail": f"Call historical_inspect with question_id='{qid}' for all witnesses.",
    }


def _slim_witness(w: dict[str, Any]) -> dict[str, Any]:
    """Drop internal embedding/provenance bloat; keep what a reader needs."""
    contested = w.get("contested_interpolation") or {}
    return {
        "witness_id": w.get("witness_id"),
        "source_type": w.get("source_type"),
        "source": w.get("source"),
        "attestation_type": w.get("attestation_type"),
        "confidence": w.get("confidence"),
        "evidence_phrase": w.get("evidence_phrase"),
        "rationale": w.get("rationale"),
        "contested_interpolation_type": contested.get("type")
        if isinstance(contested, dict)
        else None,
    }


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def handle(
    payload: DoctrinalVerdictInput,
    *,
    evidence_dir: Path | None = None,
    historical_dir: Path | None = None,
    cultural_chunks: list[dict[str, Any]] | None = None,
    classification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the verdict for the proposition.

    By default (``verbosity='summary'``) the result is a compact, plain-language
    answer with pointers to the drill-down tools. ``verbosity='full'`` adds the
    complete lexical, cultural, and slimmed historical blocks. ``classification``
    is the proposition-to-question match (computed by the server with the live
    voyage client); when absent it is computed here with the offline keyword
    fallback. ``cultural_chunks`` is supplied by the server from a live cultural
    retrieval; when absent the cultural overlay is empty. Both diagnostic blocks
    are optional and never change the lexical verdict.
    """
    match = classification if classification is not None else classify(payload.proposition)
    qid = match.get("matched_qid") or ""
    if not qid:
        return error_envelope(
            TOOL_NAME,
            "no_matching_question",
            f"could not match '{payload.proposition}' to a known question",
            payload.caller_context,
        )
    try:
        qid = validate_question_id(qid)
    except ValueError as exc:
        return error_envelope(TOOL_NAME, "invalid_question_id", str(exc), payload.caller_context)

    evidence_path = (evidence_dir or EVIDENCE_DIR) / f"{qid}.json"
    if not evidence_path.exists():
        return error_envelope(
            TOOL_NAME, "evidence_missing", f"no evidence for {qid}", payload.caller_context
        )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    try:
        historical_block, historical_sources = load_historical_block(qid, historical_dir)
    except (json.JSONDecodeError, ValueError) as exc:
        return error_envelope(
            TOOL_NAME,
            "historical_corrupt",
            f"historical sidecar for {qid}: {exc}",
            payload.caller_context,
        )

    cultural_block, cultural_sources = build_cultural_overlay(cultural_chunks)

    verdict = evidence.get("verdict", {})
    affirms = verdict.get("affirms")
    breadth = verdict.get("lexical_breadth")
    directness = verdict.get("lexical_directness")
    lexical_full = _build_lexical_block(evidence, qid)

    # The compact answer block leads every response, summary or full.
    result: dict[str, Any] = {
        "verdict": affirms,
        "answer": _plain_answer(affirms),
        "headline": _headline(affirms, payload.proposition),
        "explanation": evidence.get("lay_summary") or "",
        "key_scriptures": _key_scriptures(lexical_full),
        "confidence_plain": _plain_confidence(breadth, directness),
        "also_weighed": _also_weighed(lexical_full),
        "lexical_breadth": breadth,
        "lexical_directness": directness,
        "variant_stability": verdict.get("variant_stability"),
        "diagnostics": {
            "cultural": _summarize_cultural(cultural_block),
            "historical": _summarize_historical(historical_block, qid),
        },
        "evidence_file_id": qid,
        "matched_question": {
            "question_id": qid,
            "statement": match.get("matched_statement", ""),
            "match_method": match.get("method", "keyword"),
            "match_confidence": match.get("confidence", "high"),
        },
        "drill_down": {
            "full_lexical_evidence": {"tool": "evidence_inspect", "question_id": qid},
            "full_historical": {"tool": "historical_inspect", "question_id": qid},
            "full_cultural": {"tool": "cultural_overlay", "doctrine": payload.proposition},
            "hint": "Re-run doctrinal_verdict with verbosity='full' to embed every block inline.",
        },
    }

    # When the match is not a clear winner, surface the other candidates so the
    # reader can confirm or pick, rather than trusting a silent guess.
    if match.get("confidence") in {"ambiguous", "low"}:
        alternatives = [
            {"question_id": c.get("question_id"), "statement": c.get("statement")}
            for c in match.get("candidates", [])
            if c.get("question_id") != qid
        ][:4]
        if alternatives:
            result = {
                **result,
                "did_you_mean": {
                    "note": "This proposition was close to other questions. "
                    "If the answer below looks off, re-ask naming one of these.",
                    "alternatives": alternatives,
                },
            }

    if payload.verbosity == "full":
        full_historical = {**historical_block}
        full_historical["witnesses"] = [
            _slim_witness(w) for w in (historical_block.get("witnesses") or [])
        ]
        result["lexical_evidence"] = lexical_full
        result["cultural_overlay"] = cultural_block
        result["variant_sensitivity"] = evidence.get("variants", {})
        result["historical_attestation"] = full_historical

    sources = [
        {"source": s.get("source", "?"), "license": s.get("license", "?")}
        for s in evidence.get("license_audit", {}).get("sources_used", [])
    ]
    sources.extend(cultural_sources)
    sources.extend(historical_sources)

    env = success_envelope(
        tool=TOOL_NAME,
        result=result,
        sources_used=sources,
        caller_context=payload.caller_context,
    )
    # Surface the share decision in plain terms next to the answer.
    safe = bool(env.get("license_audit", {}).get("response_safe_to_share", False))
    sharing = {
        "safe_to_share_publicly": safe,
        "reason": None
        if safe
        else "Cites copyrighted source text (e.g. lexicons or confessions); keep for personal study.",
    }
    return {**env, "result": {**env["result"], "sharing": sharing}}


def register(server: Any) -> None:
    @server.tool(
        name=TOOL_NAME,
        description=(
            "Answer a doctrinal question from Scripture. Returns a plain-language "
            "yes/no with explanation, key verses, and diagnostics. Use verbosity='full' "
            "for the complete evidence blocks."
        ),
    )
    def _tool(
        ctx: Context,
        proposition: str,
        denominations: list[str] | None = None,
        depth: Literal["fast", "deep"] = "fast",
        verbosity: Verbosity = "summary",
        progressToken: str | None = None,  # noqa: N803
        caller_context: CallerContext = "personal",
    ) -> dict[str, Any]:
        payload = DoctrinalVerdictInput(
            proposition=proposition,
            denominations=denominations,
            depth=depth,
            verbosity=verbosity,
            progressToken=progressToken,
            caller_context=caller_context,
        )
        match = classify(
            proposition,
            voyage_client=app_context(ctx).voyage,
            index=load_question_index(),
        )
        qid = match.get("matched_qid") or None
        # The cultural overlay is a diagnostic that never changes the verdict.
        # Skip its live retrieval (a voyage embedding + a Qdrant search) on the
        # default summary path, and fetch it only when full detail or specific
        # denominations are asked for. This removes the biggest per-query cost.
        chunks: list[dict[str, Any]] = []
        if verbosity == "full" or denominations:
            chunks = retrieve_chunks(
                ctx, question_id=qid, doctrine=proposition, traditions=denominations, k=8
            )
        return handle(payload, cultural_chunks=chunks, classification=match)
