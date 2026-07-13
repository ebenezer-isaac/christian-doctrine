"""Adversarial hardening tests for the Pipeline 3 query surface.

Scope (intentionally disjoint from test_tools.py):
  - cd_mcp/tools/doctrinal_verdict.py  (load_historical_block + handle: the
    historical block attach, license fold, verdict read straight from the file)
  - cd_mcp/tools/historical_inspect.py (question-id traversal defense, schema
    validation surfacing)
  - pipeline4/historical_schema.py     (the validation contract these tools lean
    on: word-count bounds, anchor regex, duplicate witness ids, NFC, dashes,
    license-registry redistribute pinning)

These tests are written to BREAK code. Where a test encodes a genuine defect in
the source (not a test mistake), it is left failing-first with a clear reason. Do
NOT weaken an assertion to make it green.

Run: python -m pytest tests/cd_mcp/test_pipeline3_hardening.py -q
"""

from __future__ import annotations

import json
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from cd_mcp.tools.doctrinal_verdict import (
    DoctrinalVerdictInput,
    load_historical_block,
)
from cd_mcp.tools.doctrinal_verdict import handle as verdict_handle
from cd_mcp.tools.historical_inspect import HistoricalInspectInput
from cd_mcp.tools.historical_inspect import handle as historical_inspect_handle
from pipeline2.evidence_schema import Evidence
from pipeline2.score_calc import compute_lexical_breadth, compute_variant_stability
from pipeline4.historical_schema import HistoricalAttestation
from tests.pipeline2._fixtures import minimal_evidence_dict

_TRINITY_PROP = "There is one God in three coequal coeternal persons"


# --------------------------------------------------------------------------
# fixtures: evidence + historical sidecar builders (self-contained)
# --------------------------------------------------------------------------


def _evidence_dict() -> dict[str, Any]:
    e = Evidence.model_validate(minimal_evidence_dict())
    d = e.model_dump(by_alias=True)
    d["verdict"]["lexical_breadth"] = compute_lexical_breadth(e)
    d["verdict"]["variant_stability"] = compute_variant_stability(e)
    return d


def _materialize_trinity(tmp_path: Path) -> None:
    (tmp_path / "doc-trinity.json").write_text(json.dumps(_evidence_dict()), encoding="utf-8")


def _hist_dir(tmp_path: Path) -> Path:
    d = tmp_path / "hist"
    d.mkdir()
    return d


_VALID_SUMMARY = (
    "This is a deliberately constructed test summary that nonetheless contains enough "
    "words to satisfy the fifty word lower bound that the historical schema enforces "
    "whenever an attestation is present, so that the witnessed block validates cleanly "
    "and rides through the doctrinal verdict tool as a separate diagnostic alongside "
    "the lexical verdict without ever being fused into it or altering it in any way at "
    "all whatsoever here today."
)


def _pliny_witness() -> dict[str, Any]:
    return {
        "witness_id": "pliny.ep.10.96",
        "source_type": "roman-historian",
        "source": {
            "source_slug": "pliny",
            "work_id": "pliny.ep",
            "work_title": "Letters, Book 10",
            "author": "Pliny the Younger",
            "date_written_range": "c. 112 CE",
            "anchor_id": "pliny.ep.10.96",
            "anchor_alt_citation": None,
            "language": "en",
            "translator": "William Melmoth",
            "edition": "Wikisource",
        },
        "attestation_type": "neutral",
        "confidence": 0.6,
        "evidence_phrase": "they addressed a form of prayer to Christ, as to a divinity",
        "rationale": "A test witness used to exercise the historical block.",
        "contested_interpolation": {
            "type": "none",
            "note": None,
            "redact_for_embedding": False,
        },
        "provenance": {
            "original_language": "la",
            "witness_chain": ["latin-original"],
            "extant_witnesses": [],
            "loss_status": "complete",
        },
        "text": "they addressed a form of prayer to Christ, as to a divinity",
        "text_to_embed": "they addressed a form of prayer to Christ, as to a divinity",
        "license": "PD",
        "redistribute": True,
        "license_note": None,
    }


def _dss_witness() -> dict[str, Any]:
    return {
        "witness_id": "1qs.col04.line03",
        "source_type": "qumran-sectarian",
        "source": {
            "source_slug": "1qs",
            "work_id": "1qs",
            "work_title": "Community Rule",
            "author": None,
            "date_written_range": "c. 100 BCE",
            "anchor_id": "1qs.col04.line03",
            "anchor_alt_citation": None,
            "language": "he",
            "translator": None,
            "edition": "DSS scholarly edition",
        },
        "attestation_type": "parallel",
        "confidence": 0.5,
        "evidence_phrase": "a Qumran parallel used to exercise the license fold",
        "rationale": "A test DSS witness whose CC-BY-NC license must flip publish safety.",
        "contested_interpolation": {
            "type": "none",
            "note": None,
            "redact_for_embedding": False,
        },
        "provenance": {
            "original_language": "he",
            "witness_chain": ["hebrew-original"],
            "extant_witnesses": [],
            "loss_status": "fragmentary",
        },
        "text": "a Qumran parallel used to exercise the license fold",
        "text_to_embed": "a Qumran parallel used to exercise the license fold",
        "license": "CC-BY-NC-4.0",
        "redistribute": False,
        "license_note": None,
    }


def _historical_dict(
    qid: str,
    witnesses: list[dict[str, Any]],
    sources_used: list[dict[str, Any]],
    *,
    summary: str | None = None,
    evidence_safe_to_publish: bool = True,
    non_redistributable_reason: str | None = None,
) -> dict[str, Any]:
    present = bool(witnesses)
    return {
        "$schema_version": "1.0",
        "id": qid,
        "question_id": qid,
        "generated_at": "2026-06-04T00:00:00Z",
        "pipeline_version": "v1",
        "model": "claude-opus-4-8",
        "attestation_present": present,
        "witnesses": witnesses,
        "summary": (summary if summary is not None else (_VALID_SUMMARY if present else "")),
        "license_audit": {
            "sources_used": sources_used,
            "evidence_safe_to_publish": evidence_safe_to_publish,
            "non_redistributable_reason": non_redistributable_reason,
        },
        "flags": [],
    }


def _pliny_sidecar(qid: str) -> dict[str, Any]:
    return _historical_dict(
        qid,
        [_pliny_witness()],
        [{"source_slug": "pliny", "license": "PD", "redistribute": True}],
    )


def _dss_sidecar(qid: str) -> dict[str, Any]:
    return _historical_dict(
        qid,
        [_dss_witness()],
        [{"source_slug": "1qs", "license": "CC-BY-NC-4.0", "redistribute": False}],
        evidence_safe_to_publish=False,
        non_redistributable_reason="1qs cited under CC-BY-NC-4.0",
    )


# ==========================================================================
# 1. SCHEMA CONTRACT: the validation the tools delegate to
# ==========================================================================


def test_attestation_present_true_zero_witnesses_rejected() -> None:
    """attestation_present true with an empty witnesses list must be rejected (rule 3)."""
    d = _pliny_sidecar("doc-trinity")
    d["witnesses"] = []
    d["attestation_present"] = True
    with pytest.raises(ValueError, match="attestation_present is true but witnesses is empty"):
        HistoricalAttestation.model_validate(d)


def test_attestation_present_false_with_witnesses_rejected() -> None:
    d = _pliny_sidecar("doc-trinity")
    d["attestation_present"] = False
    with pytest.raises(ValueError, match="attestation_present is false but witnesses is non-empty"):
        HistoricalAttestation.model_validate(d)


def test_summary_below_50_words_rejected_when_present() -> None:
    d = _pliny_sidecar("doc-trinity")
    d["summary"] = "Too short a summary for the present-attestation lower bound."
    with pytest.raises(ValueError, match="50-300 words"):
        HistoricalAttestation.model_validate(d)


def test_summary_above_300_words_rejected_when_present() -> None:
    d = _pliny_sidecar("doc-trinity")
    d["summary"] = " ".join(["word"] * 301)
    with pytest.raises(ValueError, match="50-300 words"):
        HistoricalAttestation.model_validate(d)


def test_summary_exactly_50_and_300_words_accepted() -> None:
    """Boundary values 50 and 300 are inclusive."""
    lo = _pliny_sidecar("doc-trinity")
    lo["summary"] = " ".join(["word"] * 50)
    HistoricalAttestation.model_validate(lo)
    hi = _pliny_sidecar("doc-trinity")
    hi["summary"] = " ".join(["word"] * 300)
    HistoricalAttestation.model_validate(hi)


def test_summary_over_300_words_rejected_when_absent() -> None:
    """Even an empty attestation cannot carry a runaway summary."""
    d = _historical_dict("doc-trinity", [], [])
    d["summary"] = " ".join(["word"] * 301)
    with pytest.raises(ValueError, match="0-300 words"):
        HistoricalAttestation.model_validate(d)


def test_id_must_equal_question_id() -> None:
    d = _pliny_sidecar("doc-trinity")
    d["id"] = "doc-other"
    with pytest.raises(ValueError, match="must equal question_id"):
        HistoricalAttestation.model_validate(d)


def test_duplicate_witness_id_rejected() -> None:
    d = _pliny_sidecar("doc-trinity")
    dup = deepcopy(d["witnesses"][0])
    d["witnesses"] = [d["witnesses"][0], dup]
    # both witnesses key off the same anchor; uniqueness must fail before any
    # downstream tool ever sees a degenerate witness list.
    with pytest.raises(ValueError, match="duplicate witness_id"):
        HistoricalAttestation.model_validate(d)


def test_witness_id_must_equal_anchor_id() -> None:
    d = _pliny_sidecar("doc-trinity")
    d["witnesses"][0]["witness_id"] = "pliny.ep.10.97"  # anchor stays .96
    with pytest.raises(ValueError, match="must equal source.anchor_id"):
        HistoricalAttestation.model_validate(d)


def test_dash_discipline_violation_in_summary_rejected() -> None:
    """An em-dash in BD's own free text (summary) is a hard error (rule 15)."""
    d = _pliny_sidecar("doc-trinity")
    words = _VALID_SUMMARY.split()
    words[3] = "evidence—here"  # inject an em-dash
    d["summary"] = " ".join(words)
    with pytest.raises(ValueError, match="forbidden dash"):
        HistoricalAttestation.model_validate(d)


def test_dash_discipline_violation_in_rationale_rejected() -> None:
    d = _pliny_sidecar("doc-trinity")
    d["witnesses"][0]["rationale"] = "A rationale with an en–dash inside it."
    with pytest.raises(ValueError, match="forbidden dash"):
        HistoricalAttestation.model_validate(d)


def test_dash_discipline_violation_in_non_redistributable_reason_rejected() -> None:
    d = _dss_sidecar("doc-trinity")
    d["license_audit"]["non_redistributable_reason"] = "blocked—CC-BY-NC"
    with pytest.raises(ValueError, match="forbidden dash"):
        HistoricalAttestation.model_validate(d)


def test_evidence_phrase_over_60_words_rejected() -> None:
    d = _pliny_sidecar("doc-trinity")
    d["witnesses"][0]["evidence_phrase"] = " ".join(["w"] * 61)
    with pytest.raises(ValueError, match="exceeds 60 words"):
        HistoricalAttestation.model_validate(d)


def test_text_fields_are_nfc_normalized() -> None:
    """text / text_to_embed must round-trip through NFC (rule 12)."""
    d = _pliny_sidecar("doc-trinity")
    decomposed = "café"  # 'e' + combining acute, NFD form
    assert decomposed != unicodedata.normalize("NFC", decomposed)
    d["witnesses"][0]["text"] = decomposed
    d["witnesses"][0]["text_to_embed"] = decomposed
    obj = HistoricalAttestation.model_validate(d)
    assert obj.witnesses[0].text == unicodedata.normalize("NFC", decomposed)
    assert obj.witnesses[0].text == "café"


# --- anchor-id regex: Qumran DSS vs named-source ---


def test_dss_witness_with_named_source_anchor_rejected() -> None:
    """A qumran source_type whose anchor_id is a named-source citation must fail."""
    d = _pliny_sidecar("doc-trinity")
    w = _dss_witness()
    w["source"]["anchor_id"] = "pliny.ep.10.96"
    w["witness_id"] = "pliny.ep.10.96"
    d["witnesses"] = [w]
    d["license_audit"]["sources_used"] = [
        {"source_slug": "1qs", "license": "CC-BY-NC-4.0", "redistribute": False}
    ]
    d["license_audit"]["evidence_safe_to_publish"] = False
    with pytest.raises(ValueError, match="does not match the DSS pattern"):
        HistoricalAttestation.model_validate(d)


def test_named_source_with_dss_anchor_rejected() -> None:
    """A pliny witness wearing a DSS columnar anchor must fail the named pattern."""
    d = _pliny_sidecar("doc-trinity")
    d["witnesses"][0]["source"]["anchor_id"] = "1qs.col04.line03"
    d["witnesses"][0]["witness_id"] = "1qs.col04.line03"
    with pytest.raises(ValueError, match="does not match the pliny pattern"):
        HistoricalAttestation.model_validate(d)


def test_dss_fragmentary_anchor_accepted() -> None:
    """The fragmentary DSS form <scroll>.f<frag>.line<NN> from the docstring validates."""
    d = _pliny_sidecar("doc-trinity")
    w = _dss_witness()
    w["source"]["source_slug"] = "4q427"
    w["source"]["work_id"] = "4q427"
    w["source"]["anchor_id"] = "4q427.f7ii.line14"
    w["witness_id"] = "4q427.f7ii.line14"
    d["witnesses"] = [w]
    d["license_audit"]["sources_used"] = [
        {"source_slug": "4q427", "license": "CC-BY-NC-4.0", "redistribute": False}
    ]
    d["license_audit"]["evidence_safe_to_publish"] = False
    obj = HistoricalAttestation.model_validate(d)
    assert obj.witnesses[0].source.anchor_id == "4q427.f7ii.line14"


# --- license-registry redistribute pinning (rule 13) ---


def test_witness_mislabeling_nc_as_redistributable_rejected() -> None:
    """A CC-BY-NC-4.0 witness flipped to redistribute=true must be rejected."""
    d = _dss_sidecar("doc-trinity")
    d["witnesses"][0]["redistribute"] = True  # the lie
    with pytest.raises(ValueError, match="disagrees with registry"):
        HistoricalAttestation.model_validate(d)


def test_witness_mislabeling_pd_as_non_redistributable_rejected() -> None:
    d = _pliny_sidecar("doc-trinity")
    d["witnesses"][0]["redistribute"] = False  # PD is registry-true
    with pytest.raises(ValueError, match="disagrees with registry"):
        HistoricalAttestation.model_validate(d)


def test_unregistered_license_rejected() -> None:
    d = _pliny_sidecar("doc-trinity")
    d["witnesses"][0]["license"] = "©Someone-Proprietary"
    with pytest.raises(ValueError, match="not a registered slug"):
        HistoricalAttestation.model_validate(d)


def test_recompute_evidence_safe_to_publish_mixed_sources() -> None:
    """A mixed PD + CC-BY-NC source set is not bulk-publishable."""
    d = _historical_dict(
        "doc-trinity",
        [_pliny_witness(), _dss_witness()],
        [
            {"source_slug": "pliny", "license": "PD", "redistribute": True},
            {"source_slug": "1qs", "license": "CC-BY-NC-4.0", "redistribute": False},
        ],
        evidence_safe_to_publish=False,
        non_redistributable_reason="1qs cited under CC-BY-NC-4.0",
    )
    obj = HistoricalAttestation.model_validate(d)
    assert obj.recompute_evidence_safe_to_publish() is False


def test_recompute_evidence_safe_to_publish_all_pd_true() -> None:
    obj = HistoricalAttestation.model_validate(_pliny_sidecar("doc-trinity"))
    assert obj.recompute_evidence_safe_to_publish() is True


# ==========================================================================
# 2. load_historical_block: edge cases + traversal exposure
# ==========================================================================


def test_load_historical_block_empty_file_raises_json_error(tmp_path: Path) -> None:
    """A truncated / empty sidecar file is corrupt, not silently treated as empty."""
    (tmp_path / "doc-trinity.json").write_text("", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_historical_block("doc-trinity", tmp_path)


def test_load_historical_block_corrupt_json_raises(tmp_path: Path) -> None:
    (tmp_path / "doc-trinity.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_historical_block("doc-trinity", tmp_path)


def test_load_historical_block_schema_violation_raises_value_error(tmp_path: Path) -> None:
    bad = _pliny_sidecar("doc-trinity")
    bad["id"] = "doc-mismatch"
    (tmp_path / "doc-trinity.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError):
        load_historical_block("doc-trinity", tmp_path)


def test_load_historical_block_folds_dss_source_license(tmp_path: Path) -> None:
    (tmp_path / "doc-trinity.json").write_text(
        json.dumps(_dss_sidecar("doc-trinity")), encoding="utf-8"
    )
    block, sources = load_historical_block("doc-trinity", tmp_path)
    assert block["attestation_present"] is True
    assert sources == [{"source": "1qs", "license": "CC-BY-NC-4.0"}]


@pytest.mark.parametrize(
    "malicious",
    ["../doc-trinity", "doc-trinity/../doc-trinity", "..", "/etc/passwd"],
)
def test_load_historical_block_rejects_traversal_qid(tmp_path: Path, malicious: str) -> None:
    # load_historical_block validates the question_id at its own boundary, so a
    # traversal slug is rejected before any path is built. A well-formed sidecar
    # sits one directory up; a '..' slug must NOT reach it.
    parent = tmp_path / "outer"
    inner = parent / "inner"
    inner.mkdir(parents=True)
    (parent / "doc-trinity.json").write_text(
        json.dumps(_pliny_sidecar("doc-trinity")), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_historical_block(malicious, inner)


# ==========================================================================
# 3. doctrinal_verdict.handle: license fold, share-safety boundary, fidelity
# ==========================================================================


def test_dss_witness_flips_share_safety_under_personal(tmp_path: Path) -> None:
    """A CC-BY-NC-4.0 historical witness is unsafe to share even under personal.

    The doctrinal_verdict envelope passes snippet_word_count=0, so the snippet
    check denies CC-BY-NC-4.0 (positive word count required). Share-safety must
    therefore be False in EVERY caller_context, not only export. This pins the
    exact guard-mode boundary.
    """
    _materialize_trinity(tmp_path)
    hist = _hist_dir(tmp_path)
    (hist / "doc-trinity.json").write_text(
        json.dumps(_dss_sidecar("doc-trinity")), encoding="utf-8"
    )
    env = verdict_handle(
        DoctrinalVerdictInput(proposition=_TRINITY_PROP, caller_context="personal"),
        evidence_dir=tmp_path,
        historical_dir=hist,
    )
    assert env["ok"] is True
    assert env["license_audit"]["response_safe_to_share"] is False
    assert env["license_audit"]["non_redistributable_reason"]


@pytest.mark.parametrize("ctx", ["personal", "public-share", "export"])
def test_dss_witness_unsafe_across_all_contexts(tmp_path: Path, ctx: str) -> None:
    _materialize_trinity(tmp_path)
    hist = _hist_dir(tmp_path)
    (hist / "doc-trinity.json").write_text(
        json.dumps(_dss_sidecar("doc-trinity")), encoding="utf-8"
    )
    env = verdict_handle(
        DoctrinalVerdictInput(proposition=_TRINITY_PROP, caller_context=ctx),  # type: ignore[arg-type]
        evidence_dir=tmp_path,
        historical_dir=hist,
    )
    assert env["license_audit"]["response_safe_to_share"] is False


def test_pliny_pd_witness_safe_to_share(tmp_path: Path) -> None:
    """A PD-only witness keeps the response shareable; this guards against a
    false-positive where any historical witness would wrongly trip the guard."""
    _materialize_trinity(tmp_path)
    hist = _hist_dir(tmp_path)
    (hist / "doc-trinity.json").write_text(
        json.dumps(_pliny_sidecar("doc-trinity")), encoding="utf-8"
    )
    env = verdict_handle(
        DoctrinalVerdictInput(proposition=_TRINITY_PROP, caller_context="export"),
        evidence_dir=tmp_path,
        historical_dir=hist,
    )
    assert env["ok"] is True
    assert env["license_audit"]["response_safe_to_share"] is True


def test_historical_block_and_verdict_come_only_from_files(tmp_path: Path) -> None:
    """The verdict is read verbatim from the evidence file and the historical
    block from the sidecar. There is no synthesis seam to smuggle either through,
    so a caller cannot alter them: the result mirrors the files exactly."""
    _materialize_trinity(tmp_path)
    evidence = _evidence_dict()
    hist = _hist_dir(tmp_path)
    (hist / "doc-trinity.json").write_text(
        json.dumps(_pliny_sidecar("doc-trinity")), encoding="utf-8"
    )
    env = verdict_handle(
        DoctrinalVerdictInput(proposition=_TRINITY_PROP, verbosity="full"),
        evidence_dir=tmp_path,
        historical_dir=hist,
    )
    assert env["ok"] is True
    assert env["result"]["verdict"] == evidence["verdict"]["affirms"]
    block = env["result"]["historical_attestation"]
    assert block["attestation_present"] is True
    assert block["witnesses"][0]["witness_id"] == "pliny.ep.10.96"


def test_corrupt_sidecar_blocks_verdict_emission(tmp_path: Path) -> None:
    """A schema-invalid sidecar must fail the whole verdict, never silently drop
    to an empty historical block (fail-closed on corruption)."""
    _materialize_trinity(tmp_path)
    hist = _hist_dir(tmp_path)
    bad = _pliny_sidecar("doc-trinity")
    bad["witnesses"][0]["redistribute"] = True
    bad["witnesses"][0]["license"] = "CC-BY-NC-4.0"  # registry says redistribute must be False
    (hist / "doc-trinity.json").write_text(json.dumps(bad), encoding="utf-8")
    env = verdict_handle(
        DoctrinalVerdictInput(proposition=_TRINITY_PROP),
        evidence_dir=tmp_path,
        historical_dir=hist,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "historical_corrupt"


def test_empty_sidecar_file_in_handle_is_caught(tmp_path: Path) -> None:
    """An empty (0-byte) sidecar raises JSONDecodeError inside load_historical_block;
    handle catches it and returns historical_corrupt rather than crashing."""
    _materialize_trinity(tmp_path)
    hist = _hist_dir(tmp_path)
    (hist / "doc-trinity.json").write_text("", encoding="utf-8")
    env = verdict_handle(
        DoctrinalVerdictInput(proposition=_TRINITY_PROP),
        evidence_dir=tmp_path,
        historical_dir=hist,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "historical_corrupt"


# ==========================================================================
# 4. historical_inspect: traversal + corruption surfacing
# ==========================================================================


@pytest.mark.parametrize(
    "malicious",
    [
        "doc-trinity%2f..%2fsecrets",  # url-encoded slash
        "doc-trinity\x00.json",  # null byte
        "DOC-TRINITY",  # uppercase (regex requires lowercase lead)
        "ab",  # below 3-char minimum (regex requires >= 3)
        "doc trinity",  # whitespace
        "..\\..\\windows",  # windows-style traversal
        "doc-trinity.json",  # trailing extension is not a bare slug
    ],
)
def test_historical_inspect_rejects_extended_traversal(tmp_path: Path, malicious: str) -> None:
    env = historical_inspect_handle(
        HistoricalInspectInput(question_id=malicious), historical_dir=tmp_path
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "invalid_question_id"


def test_historical_inspect_empty_file_is_corrupt_not_crash(tmp_path: Path) -> None:
    (tmp_path / "doc-trinity.json").write_text("", encoding="utf-8")
    env = historical_inspect_handle(
        HistoricalInspectInput(question_id="doc-trinity"), historical_dir=tmp_path
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "historical_corrupt"


def test_historical_inspect_schema_violation_surfaces_as_corrupt(tmp_path: Path) -> None:
    bad = _dss_sidecar("doc-trinity")
    bad["witnesses"][0]["redistribute"] = True  # registry violation
    (tmp_path / "doc-trinity.json").write_text(json.dumps(bad), encoding="utf-8")
    env = historical_inspect_handle(
        HistoricalInspectInput(question_id="doc-trinity"), historical_dir=tmp_path
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "historical_corrupt"


def test_historical_inspect_dss_sidecar_unsafe_to_share(tmp_path: Path) -> None:
    """historical_inspect on a DSS sidecar must report the CC-BY-NC source and
    flag the response not safe to share under export."""
    (tmp_path / "doc-trinity.json").write_text(
        json.dumps(_dss_sidecar("doc-trinity")), encoding="utf-8"
    )
    env = historical_inspect_handle(
        HistoricalInspectInput(question_id="doc-trinity", caller_context="export"),
        historical_dir=tmp_path,
    )
    assert env["ok"] is True
    assert env["license_audit"]["response_safe_to_share"] is False
    sources = {s["source"] for s in env["license_audit"]["sources_used"]}
    assert "1qs" in sources
