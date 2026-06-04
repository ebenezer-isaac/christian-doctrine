"""Tests for the 12 MCP tool handlers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from bd_mcp.tools.concordance_walk import ConcordanceWalkInput
from bd_mcp.tools.concordance_walk import handle as concordance_handle
from bd_mcp.tools.cross_ref import CrossRefInput
from bd_mcp.tools.cross_ref import handle as cross_ref_handle
from bd_mcp.tools.cultural_overlay import CulturalOverlayInput
from bd_mcp.tools.cultural_overlay import handle as cultural_overlay_handle
from bd_mcp.tools.debate_for_verse import DebateForVerseInput
from bd_mcp.tools.debate_for_verse import handle as debate_handle
from bd_mcp.tools.doctrinal_verdict import (
    DoctrinalVerdictInput,
    load_historical_block,
    transform_synthesis_to_envelope,
)
from bd_mcp.tools.doctrinal_verdict import handle as verdict_handle
from bd_mcp.tools.evidence_inspect import EvidenceInspectInput
from bd_mcp.tools.evidence_inspect import handle as evidence_inspect_handle
from bd_mcp.tools.historical_inspect import HistoricalInspectInput
from bd_mcp.tools.historical_inspect import handle as historical_inspect_handle
from bd_mcp.tools.lexical_lookup import LexicalLookupInput
from bd_mcp.tools.lexical_lookup import handle as lexical_lookup_handle
from bd_mcp.tools.license_audit import LicenseAuditInput
from bd_mcp.tools.license_audit import handle as license_audit_handle
from bd_mcp.tools.parallel_translation import ParallelTranslationInput
from bd_mcp.tools.parallel_translation import handle as parallel_translation_handle
from bd_mcp.tools.variant_inspect import VariantInspectInput
from bd_mcp.tools.variant_inspect import handle as variant_inspect_handle
from bd_mcp.tools.versification_resolve import VersificationResolveInput
from bd_mcp.tools.versification_resolve import handle as versification_handle
from ingest.versification_mapper import VersificationMapper
from pipeline2.evidence_schema import Evidence
from pipeline2.score_calc import compute_lexical_breadth, compute_variant_stability
from tests.pipeline2._fixtures import minimal_evidence_dict

UUID_REGEX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class _SessionStub:
    def __init__(self, response: list[dict[str, Any]]) -> None:
        self._response = response

    def run(self, *_a: object, **_kw: object) -> list[dict[str, Any]]:
        return list(self._response)


def _materialize_trinity(tmp_path: Path) -> Path:
    e = Evidence.model_validate(minimal_evidence_dict())
    e_dict = e.model_dump(by_alias=True)
    e_dict["verdict"]["lexical_breadth"] = compute_lexical_breadth(e)
    e_dict["verdict"]["variant_stability"] = compute_variant_stability(e)
    p = tmp_path / "doc-trinity.json"
    p.write_text(json.dumps(e_dict, indent=2), encoding="utf-8")
    return p


# ---------- lexical_lookup ----------


def test_lexical_lookup_basic() -> None:
    session = _SessionStub(
        [
            {
                "l": {
                    "strong": "G2316",
                    "lemma": "θεός",
                    "transliteration": "theos",
                    "occurrences_in_canon": 1317,
                }
            }
        ]
    )
    env = lexical_lookup_handle(
        LexicalLookupInput(query="G2316", lang="gk", id_type="strong"), neo4j_session=session
    )
    assert env["ok"] is True
    assert env["result"]["matches"][0]["strong"] == "G2316"
    assert UUID_REGEX.match(env["trace_id"])


def test_lexical_lookup_no_session_empty() -> None:
    env = lexical_lookup_handle(LexicalLookupInput(query="G2316", lang="gk"))
    assert env["result"]["matches"] == []


def test_lexical_lookup_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        LexicalLookupInput.model_validate({"query": "x", "lang": "gk", "extra": 1})


def test_lexical_lookup_invalid_lang_rejected() -> None:
    with pytest.raises(ValidationError):
        LexicalLookupInput(query="x", lang="zz")  # type: ignore[arg-type]


def test_lexical_lookup_envelope_has_license_audit() -> None:
    session = _SessionStub(
        [
            {
                "l": {
                    "strong": "G2316",
                    "lemma": "θεός",
                    "transliteration": "theos",
                    "occurrences_in_canon": 1317,
                }
            }
        ]
    )
    env = lexical_lookup_handle(LexicalLookupInput(query="G2316", lang="gk"), neo4j_session=session)
    assert "license_audit" in env
    assert env["license_audit"]["sources_used"][0]["source"] == "STEPBible-TBESG"


def test_lexical_lookup_truncated_flag_set_on_limit() -> None:
    session = _SessionStub(
        [
            {
                "l": {
                    "strong": f"G{i:04d}",
                    "lemma": f"l{i}",
                    "transliteration": f"t{i}",
                    "occurrences_in_canon": 1,
                }
            }
            for i in range(20)
        ]
    )
    env = lexical_lookup_handle(
        LexicalLookupInput(query="G2316", lang="gk", limit=20), neo4j_session=session
    )
    assert env["result"]["truncated"] is True


# ---------- concordance_walk ----------


def test_concordance_walk_strong_returns_occurrences() -> None:
    session = _SessionStub(
        [
            {"ref": "John.1.1", "surface": "θεός", "morph": "N-NSM"},
            {"ref": "John.1.18", "surface": "θεὸν", "morph": "N-ASM"},
        ]
    )
    env = concordance_handle(ConcordanceWalkInput(strong="G2316", window=3), neo4j_session=session)
    assert env["ok"] is True
    assert len(env["result"]["occurrences"]) == 2
    assert env["result"]["occurrences"][0]["ref"] == "John.1.1"


def test_concordance_walk_requires_anchor() -> None:
    with pytest.raises(ValidationError):
        ConcordanceWalkInput()


def test_concordance_walk_filter_book() -> None:
    session = _SessionStub(
        [
            {"ref": "John.1.1", "surface": "x", "morph": ""},
            {"ref": "Matt.5.1", "surface": "y", "morph": ""},
        ]
    )
    env = concordance_handle(
        ConcordanceWalkInput(strong="G2316", filter_book=["John"]),
        neo4j_session=session,
    )
    refs = {o["ref"] for o in env["result"]["occurrences"]}
    assert "John.1.1" in refs
    assert "Matt.5.1" not in refs


def test_concordance_walk_no_session() -> None:
    env = concordance_handle(ConcordanceWalkInput(strong="G2316"))
    assert env["result"]["occurrences"] == []


def test_concordance_walk_window_validation() -> None:
    with pytest.raises(ValidationError):
        ConcordanceWalkInput(strong="G2316", window=-1)


def test_concordance_walk_lemma_anchor() -> None:
    session = _SessionStub([{"ref": "John.1.1", "surface": "logos", "morph": "N"}])
    env = concordance_handle(ConcordanceWalkInput(lemma="logos"), neo4j_session=session)
    assert env["result"]["anchor"] == "logos"


# ---------- cross_ref ----------


def test_cross_ref_returns_edges() -> None:
    session = _SessionStub(
        [
            {"from_ref": "John.3.16", "to_ref": "Rom.5.8", "source": "openbible", "votes": 100},
            {"from_ref": "John.3.16", "to_ref": "1John.4.9", "source": "tsk", "votes": 80},
        ]
    )
    env = cross_ref_handle(CrossRefInput(ref="John.3.16"), neo4j_session=session)
    assert env["result"]["count"] == 2
    sources = {s["source"] for s in env["license_audit"]["sources_used"]}
    assert "OpenBible-cross-refs" in sources
    assert "TSK" in sources


def test_cross_ref_empty_input_safe() -> None:
    env = cross_ref_handle(CrossRefInput(ref="Unknown.99.99"))
    assert env["result"]["edges"] == []


def test_cross_ref_each_edge_has_required_keys() -> None:
    session = _SessionStub(
        [{"from_ref": "J.1.1", "to_ref": "J.1.2", "source": "openbible", "votes": 5}]
    )
    env = cross_ref_handle(CrossRefInput(ref="J.1.1"), neo4j_session=session)
    edge = env["result"]["edges"][0]
    for key in ("from", "to", "source", "votes"):
        assert key in edge


def test_cross_ref_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        CrossRefInput.model_validate({"ref": "x", "bogus": 1})


def test_cross_ref_min_votes_validation() -> None:
    with pytest.raises(ValidationError):
        CrossRefInput(ref="x", min_votes=-1)


def test_cross_ref_limit_bounded() -> None:
    with pytest.raises(ValidationError):
        CrossRefInput(ref="x", limit=10000)


# ---------- variant_inspect ----------


def test_variant_inspect_returns_ecm_published_false() -> None:
    env = variant_inspect_handle(VariantInspectInput(ref="John.1.1"))
    assert env["result"]["ecm_published"] is False


def test_variant_inspect_envelope_safe_with_intf() -> None:
    env = variant_inspect_handle(VariantInspectInput(ref="John.1.1"))
    sources = env["license_audit"]["sources_used"]
    assert any(s["source"] == "INTF-NTVMR" for s in sources)


def test_variant_inspect_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        VariantInspectInput.model_validate({"ref": "x", "bogus": 1})


# ---------- parallel_translation ----------


def test_parallel_translation_basic() -> None:
    session = _SessionStub([{"surface": "Ἐν"}, {"surface": "ἀρχῇ"}])
    env = parallel_translation_handle(
        ParallelTranslationInput(ref="John.1.1", translations=["ESV"], include_original=True),
        neo4j_session=session,
    )
    rows = env["result"]["rows"]
    assert any(r["translation"] == "original" for r in rows)
    assert any(r["translation"] == "ESV" for r in rows)


def test_parallel_translation_ttesv_unsafe_in_public_share() -> None:
    env = parallel_translation_handle(
        ParallelTranslationInput(
            ref="John.1.1",
            translations=["ESV"],
            include_original=False,
            caller_context="public-share",
        )
    )
    assert env["license_audit"]["response_safe_to_share"] is False


def test_parallel_translation_no_translations_rejected() -> None:
    with pytest.raises(ValidationError):
        ParallelTranslationInput(ref="x", translations=[])


def test_parallel_translation_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        ParallelTranslationInput.model_validate({"ref": "x", "translations": ["ESV"], "bogus": 1})


def test_parallel_translation_caller_context_default() -> None:
    p = ParallelTranslationInput(ref="x", translations=["ESV"])
    assert p.caller_context == "personal"


def test_parallel_translation_export_unsafe() -> None:
    env = parallel_translation_handle(
        ParallelTranslationInput(
            ref="x", translations=["ESV"], include_original=False, caller_context="export"
        )
    )
    assert env["license_audit"]["response_safe_to_share"] is False


# ---------- versification_resolve ----------


def test_versification_identity_when_schemes_equal() -> None:
    env = versification_handle(
        VersificationResolveInput(ref="Psa.51.1", from_scheme="english", to_scheme="english"),
        mapper=VersificationMapper(),
    )
    assert env["result"]["rule_type"] == "identity"
    assert env["result"]["to_ref"] == "Psa.51.1"


def test_versification_all_mappings_at_least_2() -> None:
    env = versification_handle(
        VersificationResolveInput(ref="Psa.51.1", from_scheme="english", to_scheme="hebrew"),
        mapper=VersificationMapper(),
    )
    assert len(env["result"]["all_mappings"]) >= 2


def test_versification_envelope_carries_tvtms() -> None:
    env = versification_handle(
        VersificationResolveInput(ref="Psa.51.1", from_scheme="english", to_scheme="hebrew"),
        mapper=VersificationMapper(),
    )
    sources = {s["source"] for s in env["license_audit"]["sources_used"]}
    assert "STEPBible-TVTMS" in sources


def test_versification_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        VersificationResolveInput.model_validate(
            {"ref": "x", "from_scheme": "a", "to_scheme": "b", "bogus": 1}
        )


def test_versification_validates_ref_format() -> None:
    with pytest.raises(ValueError, match="malformed"):
        versification_handle(
            VersificationResolveInput(ref="bad", from_scheme="english", to_scheme="hebrew"),
            mapper=VersificationMapper(),
        )


# ---------- cultural_overlay ----------


def test_cultural_overlay_redistributable_full_text() -> None:
    chunks = [
        {
            "tradition": "reformed",
            "source": "opc.org-WCF",
            "stance": "affirms",
            "text": "Some confession text. " * 20,
            "license": "public_domain",
            "redistribute": True,
            "source_work_word_count": 100000,
        }
    ]
    env = cultural_overlay_handle(
        CulturalOverlayInput(doctrine="sacraments"), cultural_chunks=chunks
    )
    p = env["result"]["passages"][0]
    assert p["snippet"] is not None
    assert p["tradition_paraphrase_if_not_redistributable"] is None


def test_cultural_overlay_nc_chunk_snippet_capped_at_100_words() -> None:
    long_text = " ".join(["word"] * 500)
    chunks = [
        {
            "tradition": "catholic-magisterial",
            "source": "Vatican.va-CCC",
            "stance": "affirms",
            "text": long_text,
            "license": "©Libreria-Editrice-Vaticana",
            "redistribute": False,
            "source_work_word_count": 200000,
        }
    ]
    env = cultural_overlay_handle(
        CulturalOverlayInput(doctrine="sacraments"), cultural_chunks=chunks
    )
    p = env["result"]["passages"][0]
    assert p["snippet"] is not None
    assert len(p["snippet"].split()) <= 100
    assert p["tradition_paraphrase_if_not_redistributable"] is not None


def test_cultural_overlay_1pct_cap_for_small_source() -> None:
    long_text = " ".join(["word"] * 500)
    chunks = [
        {
            "tradition": "catholic-magisterial",
            "source": "Vatican.va-CCC",
            "stance": "affirms",
            "text": long_text,
            "license": "©Libreria-Editrice-Vaticana",
            "redistribute": False,
            "source_work_word_count": 200,
        }
    ]
    env = cultural_overlay_handle(
        CulturalOverlayInput(doctrine="sacraments"), cultural_chunks=chunks
    )
    p = env["result"]["passages"][0]
    assert p["snippet"] is not None
    assert len(p["snippet"].split()) <= 2


def test_cultural_overlay_by_tradition_grouping() -> None:
    chunks = [
        {
            "tradition": "reformed",
            "source": "WCF",
            "stance": "affirms",
            "text": "x",
            "license": "public_domain",
            "redistribute": True,
        },
        {
            "tradition": "catholic-magisterial",
            "source": "CCC",
            "stance": "complicates",
            "text": "y",
            "license": "public_domain",
            "redistribute": True,
        },
    ]
    env = cultural_overlay_handle(CulturalOverlayInput(doctrine="trinity"), cultural_chunks=chunks)
    assert "reformed" in env["result"]["by_tradition"]
    assert "catholic-magisterial" in env["result"]["by_tradition"]


def test_cultural_overlay_k_caps_results() -> None:
    chunks = [
        {
            "tradition": "r",
            "source": "s",
            "stance": "x",
            "text": "t",
            "license": "public_domain",
            "redistribute": True,
        }
    ] * 20
    env = cultural_overlay_handle(CulturalOverlayInput(doctrine="d", k=5), cultural_chunks=chunks)
    assert len(env["result"]["passages"]) == 5


def test_cultural_overlay_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        CulturalOverlayInput.model_validate({"k": 4, "bogus": 1})


# ---------- debate_for_verse ----------


def test_debate_for_verse_groups_by_tradition() -> None:
    chunks = [
        {
            "tradition": "reformed",
            "source": "WCF",
            "stance": "affirms",
            "text": "x",
            "license": "public_domain",
            "redistribute": True,
        },
        {
            "tradition": "lutheran",
            "source": "BoC",
            "stance": "qualifies",
            "text": "y",
            "license": "public_domain",
            "redistribute": True,
        },
        {
            "tradition": "catholic-magisterial",
            "source": "CCC",
            "stance": "denies",
            "text": "z",
            "license": "©x",
            "redistribute": False,
            "source_work_word_count": 200000,
        },
    ]
    env = debate_handle(DebateForVerseInput(ref="John.6.53"), cultural_chunks=chunks)
    assert len(env["result"]["by_tradition"]) >= 3


def test_debate_for_verse_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        DebateForVerseInput.model_validate({"ref": "x", "bogus": 1})


def test_debate_for_verse_envelope_carries_license_audit() -> None:
    env = debate_handle(DebateForVerseInput(ref="J.1.1"))
    assert "license_audit" in env


def test_debate_for_verse_redacts_nc_snippet() -> None:
    long_text = " ".join(["w"] * 200)
    chunks = [
        {
            "tradition": "catholic-magisterial",
            "source": "Vatican.va-CCC",
            "stance": "affirms",
            "text": long_text,
            "license": "©Libreria-Editrice-Vaticana",
            "redistribute": False,
            "source_work_word_count": 200000,
        }
    ]
    env = debate_handle(DebateForVerseInput(ref="x"), cultural_chunks=chunks)
    snippet = env["result"]["by_tradition"]["catholic-magisterial"][0]["snippet"]
    assert snippet is None or len(snippet.split()) <= 100


# ---------- doctrinal_verdict ----------


def test_doctrinal_verdict_transform_purity() -> None:
    payload = {
        "lexical_verdict": {
            "affirms": True,
            "lexical_breadth": "canon_wide",
            "lexical_directness": "direct",
            "variant_stability": "not_in_scope",
            "source_evidence_files": ["evidence/doc-trinity.json"],
            "rationale": "r",
        },
        "cultural_overlay": {"by_tradition": {}},
        "variant_sensitivity": {},
        "license_audit": {"sources_used": []},
    }
    import hashlib

    digests = set()
    for _ in range(10):
        out = transform_synthesis_to_envelope(payload)
        digests.add(
            hashlib.sha256(json.dumps(out, sort_keys=True, default=str).encode()).hexdigest()
        )
    assert len(digests) == 1


def test_doctrinal_verdict_transform_extracts_evidence_file_id() -> None:
    payload = {
        "lexical_verdict": {
            "affirms": True,
            "lexical_breadth": "canon_wide",
            "lexical_directness": "direct",
            "variant_stability": "not_in_scope",
            "source_evidence_files": ["evidence/doc-trinity.json"],
        },
        "cultural_overlay": None,
        "variant_sensitivity": None,
        "license_audit": {"sources_used": []},
    }
    out = transform_synthesis_to_envelope(payload)
    assert out["result"]["evidence_file_id"] == "doc-trinity"


def test_doctrinal_verdict_transform_surfaces_v31_axes() -> None:
    """The three v3.1 axes ride out of the transform into result."""
    payload = {
        "lexical_verdict": {
            "affirms": True,
            "lexical_breadth": "broad",
            "lexical_directness": "inferred",
            "variant_stability": "stable",
            "source_evidence_files": ["evidence/doc-trinity.json"],
        },
        "cultural_overlay": None,
        "variant_sensitivity": None,
        "license_audit": {"sources_used": []},
    }
    out = transform_synthesis_to_envelope(payload)
    assert out["result"]["verdict"] is True
    assert out["result"]["lexical_breadth"] == "broad"
    assert out["result"]["lexical_directness"] == "inferred"
    assert out["result"]["variant_stability"] == "stable"


def test_doctrinal_verdict_fidelity_success(tmp_path: Path) -> None:
    _materialize_trinity(tmp_path)
    env = verdict_handle(
        DoctrinalVerdictInput(proposition="There is one God in three coequal coeternal persons"),
        evidence_dir=tmp_path,
    )
    assert env["ok"] is True


def test_doctrinal_verdict_fidelity_violation(tmp_path: Path) -> None:
    _materialize_trinity(tmp_path)

    def bad_synth(_inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "lexical_verdict": {
                "affirms": False,
                "lexical_breadth": "thin",
                "lexical_directness": "inferred",
                "variant_stability": "not_in_scope",
                "source_evidence_files": ["evidence/doc-trinity.json"],
            },
            "cultural_overlay": None,
            "variant_sensitivity": None,
            "license_audit": {"sources_used": []},
        }

    env = verdict_handle(
        DoctrinalVerdictInput(proposition="There is one God in three coequal coeternal persons"),
        synthesis_fn=bad_synth,
        evidence_dir=tmp_path,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "verdict_fidelity_violation"


def test_doctrinal_verdict_no_match(tmp_path: Path) -> None:
    questions_path = Path("questions.json")
    if not questions_path.exists():
        pytest.skip("questions.json missing")
    env = verdict_handle(
        DoctrinalVerdictInput(proposition="qzqzqzqzqz nonsensical phrase"),
        evidence_dir=tmp_path,
    )
    assert env["ok"] is False


def test_doctrinal_verdict_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        DoctrinalVerdictInput.model_validate({"proposition": "x", "bogus": 1})


# ---------- evidence_inspect ----------


def test_evidence_inspect_reads_existing_file(tmp_path: Path) -> None:
    _materialize_trinity(tmp_path)
    env = evidence_inspect_handle(
        EvidenceInspectInput(question_id="doc-trinity"), evidence_dir=tmp_path
    )
    assert env["ok"] is True
    assert env["result"]["question_id"] == "doc-trinity"


def test_evidence_inspect_missing_returns_error(tmp_path: Path) -> None:
    env = evidence_inspect_handle(
        EvidenceInspectInput(question_id="doc-missing"), evidence_dir=tmp_path
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "evidence_missing"


@pytest.mark.parametrize(
    "malicious",
    [
        "../../../etc/passwd",
        "doc-trinity/../secrets",
        "/etc/passwd",
        "..",
        "doc-trinity/..",
    ],
)
def test_evidence_inspect_rejects_path_traversal(tmp_path: Path, malicious: str) -> None:
    env = evidence_inspect_handle(
        EvidenceInspectInput(question_id=malicious), evidence_dir=tmp_path
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "invalid_question_id"


def test_evidence_inspect_truncated_schema(tmp_path: Path) -> None:
    _materialize_trinity(tmp_path)
    env = evidence_inspect_handle(
        EvidenceInspectInput(question_id="doc-trinity", include_full_schema=False),
        evidence_dir=tmp_path,
    )
    assert env["ok"] is True
    assert "lexical_evidence" not in env["result"]
    assert env["result"]["verdict"] is not None


# ---------- license_audit ----------


def test_license_audit_evidence_file_safe(tmp_path: Path) -> None:
    _materialize_trinity(tmp_path)
    env = license_audit_handle(
        LicenseAuditInput(subject_type="evidence_file", subject_id="doc-trinity"),
        evidence_dir=tmp_path,
    )
    assert env["ok"] is True
    assert env["result"]["bulk_redistributable"] is True


def test_license_audit_evidence_file_unsafe(tmp_path: Path) -> None:
    d = minimal_evidence_dict()
    d["license_audit"] = {
        "sources_used": [
            {"source": "ETCBC-BHSA", "license": "CC-BY-NC-4.0", "redistribute": False}
        ],
        "evidence_safe_to_publish": False,
        "non_redistributable_reason": "BHSA CC-BY-NC-4.0",
    }
    d["citations"] = [
        {
            "type": "syntax",
            "source": "ETCBC-BHSA",
            "license": "CC-BY-NC-4.0",
            "redistribute": False,
            "ref": "Gen.1.1",
        }
    ]
    e = Evidence.model_validate(d)
    e_dict = e.model_dump(by_alias=True)
    e_dict["verdict"]["lexical_breadth"] = compute_lexical_breadth(e)
    e_dict["verdict"]["variant_stability"] = compute_variant_stability(e)
    (tmp_path / "doc-x.json").write_text(json.dumps(e_dict), encoding="utf-8")
    env = license_audit_handle(
        LicenseAuditInput(subject_type="evidence_file", subject_id="doc-x"),
        evidence_dir=tmp_path,
    )
    assert env["ok"] is True
    assert env["result"]["bulk_redistributable"] is False


@pytest.mark.parametrize(
    "malicious",
    [
        "../../../etc/passwd",
        "doc-trinity/../secrets",
        "/etc/passwd",
        "..",
    ],
)
def test_license_audit_rejects_evidence_file_traversal(tmp_path: Path, malicious: str) -> None:
    env = license_audit_handle(
        LicenseAuditInput(subject_type="evidence_file", subject_id=malicious),
        evidence_dir=tmp_path,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "invalid_subject_id"


@pytest.mark.parametrize(
    "bad_uuid",
    [
        "not-a-uuid",
        "../../../etc/passwd",
        "12345",
        "abc",
    ],
)
def test_license_audit_rejects_bad_trace_uuid(tmp_path: Path, bad_uuid: str) -> None:
    env = license_audit_handle(
        LicenseAuditInput(subject_type="response_trace", subject_id=bad_uuid),
        trace_dir=tmp_path,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "invalid_subject_id"


def test_license_audit_accepts_valid_uuid(tmp_path: Path) -> None:
    uid = "12345678-1234-1234-1234-123456789abc"
    (tmp_path / f"{uid}.json").write_text(
        json.dumps({"license_audit": {"sources_used": []}}), encoding="utf-8"
    )
    env = license_audit_handle(
        LicenseAuditInput(subject_type="response_trace", subject_id=uid),
        trace_dir=tmp_path,
    )
    assert env["ok"] is True


def test_license_audit_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        LicenseAuditInput.model_validate(
            {"subject_type": "evidence_file", "subject_id": "x", "bogus": 1}
        )


# ---------- historical attestation block (Pipeline 4 -> Pipeline 3) ----------

REPO_HISTORICAL_DIR = Path("historical")
_RESURRECTION_QID = "doc-bodily-resurrection-of-christ"


def _witnessed_historical_dict(qid: str, *, source_slug: str = "pliny") -> dict[str, Any]:
    """A minimal but schema-valid HistoricalAttestation with one PD witness."""
    return {
        "$schema_version": "1.0",
        "id": qid,
        "question_id": qid,
        "generated_at": "2026-06-04T00:00:00Z",
        "pipeline_version": "v1",
        "model": "claude-opus-4-8",
        "attestation_present": True,
        "witnesses": [
            {
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
        ],
        "summary": (
            "This is a deliberately short test summary that nonetheless contains enough words to "
            "satisfy the fifty word lower bound that the historical schema enforces whenever an "
            "attestation is present, so that the witnessed block validates cleanly and rides "
            "through the doctrinal verdict tool as a separate diagnostic alongside the lexical "
            "verdict without ever being fused into it or changing it in any way at all here."
        ),
        "license_audit": {
            "sources_used": [{"source_slug": source_slug, "license": "PD", "redistribute": True}],
            "evidence_safe_to_publish": True,
            "non_redistributable_reason": None,
        },
        "flags": [],
    }


def _dss_witnessed_historical_dict(qid: str) -> dict[str, Any]:
    """A schema-valid attestation citing a DSS CC-BY-NC-4.0 (non-redistributable) witness."""
    base = _witnessed_historical_dict(qid)
    base["witnesses"] = [
        {
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
    ]
    base["license_audit"]["sources_used"] = [
        {"source_slug": "1qs", "license": "CC-BY-NC-4.0", "redistribute": False}
    ]
    return base


# load_historical_block


def test_load_historical_block_real_resurrection_file() -> None:
    if not (REPO_HISTORICAL_DIR / f"{_RESURRECTION_QID}.json").exists():
        pytest.skip("resurrection historical sidecar absent")
    block, sources = load_historical_block(_RESURRECTION_QID, REPO_HISTORICAL_DIR)
    assert block["attestation_present"] is True
    assert len(block["witnesses"]) == 5
    assert block["summary"]
    slugs = {s["source"] for s in sources}
    assert {"josephus", "tacitus", "pliny", "1enoch"} <= slugs


def test_load_historical_block_missing_returns_empty(tmp_path: Path) -> None:
    block, sources = load_historical_block("doc-trinity", tmp_path)
    assert block["attestation_present"] is False
    assert block["witnesses"] == []
    assert sources == []


def test_load_historical_block_witnessed(tmp_path: Path) -> None:
    (tmp_path / "doc-trinity.json").write_text(
        json.dumps(_witnessed_historical_dict("doc-trinity")), encoding="utf-8"
    )
    block, sources = load_historical_block("doc-trinity", tmp_path)
    assert block["attestation_present"] is True
    assert len(block["witnesses"]) == 1
    assert sources == [{"source": "pliny", "license": "PD"}]


# doctrinal_verdict: the block rides through and folds into the license audit


def _hist_dir(tmp_path: Path) -> Path:
    """A historical/ dir separate from the evidence dir (both key files on <qid>.json)."""
    d = tmp_path / "hist"
    d.mkdir()
    return d


def test_doctrinal_verdict_attaches_empty_historical_block(tmp_path: Path) -> None:
    _materialize_trinity(tmp_path)
    env = verdict_handle(
        DoctrinalVerdictInput(proposition="There is one God in three coequal coeternal persons"),
        evidence_dir=tmp_path,
        historical_dir=_hist_dir(tmp_path),
    )
    assert env["ok"] is True
    block = env["result"]["historical_attestation"]
    assert block["attestation_present"] is False
    assert block["witnesses"] == []


def test_doctrinal_verdict_attaches_witnessed_historical_block(tmp_path: Path) -> None:
    _materialize_trinity(tmp_path)
    hist = _hist_dir(tmp_path)
    (hist / "doc-trinity.json").write_text(
        json.dumps(_witnessed_historical_dict("doc-trinity")), encoding="utf-8"
    )
    env = verdict_handle(
        DoctrinalVerdictInput(proposition="There is one God in three coequal coeternal persons"),
        evidence_dir=tmp_path,
        historical_dir=hist,
    )
    assert env["ok"] is True
    block = env["result"]["historical_attestation"]
    assert block["attestation_present"] is True
    assert len(block["witnesses"]) == 1
    folded = {s["source"] for s in env["license_audit"]["sources_used"]}
    assert "pliny" in folded


def test_doctrinal_verdict_dss_witness_flips_share_safety_on_export(tmp_path: Path) -> None:
    _materialize_trinity(tmp_path)
    hist = _hist_dir(tmp_path)
    (hist / "doc-trinity.json").write_text(
        json.dumps(_dss_witnessed_historical_dict("doc-trinity")), encoding="utf-8"
    )
    env = verdict_handle(
        DoctrinalVerdictInput(
            proposition="There is one God in three coequal coeternal persons",
            caller_context="export",
        ),
        evidence_dir=tmp_path,
        historical_dir=hist,
    )
    assert env["ok"] is True
    assert env["license_audit"]["response_safe_to_share"] is False


def test_doctrinal_verdict_corrupt_historical_errors(tmp_path: Path) -> None:
    _materialize_trinity(tmp_path)
    hist = _hist_dir(tmp_path)
    bad = _witnessed_historical_dict("doc-trinity")
    bad["id"] = "doc-mismatch"  # id must equal question_id (schema rule 1)
    (hist / "doc-trinity.json").write_text(json.dumps(bad), encoding="utf-8")
    env = verdict_handle(
        DoctrinalVerdictInput(proposition="There is one God in three coequal coeternal persons"),
        evidence_dir=tmp_path,
        historical_dir=hist,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "historical_corrupt"


# ---------- historical_inspect ----------


def test_historical_inspect_reads_real_file() -> None:
    if not (REPO_HISTORICAL_DIR / f"{_RESURRECTION_QID}.json").exists():
        pytest.skip("resurrection historical sidecar absent")
    env = historical_inspect_handle(
        HistoricalInspectInput(question_id=_RESURRECTION_QID),
        historical_dir=REPO_HISTORICAL_DIR,
    )
    assert env["ok"] is True
    assert env["result"]["question_id"] == _RESURRECTION_QID
    assert len(env["result"]["witnesses"]) == 5


def test_historical_inspect_truncated_schema(tmp_path: Path) -> None:
    (tmp_path / "doc-trinity.json").write_text(
        json.dumps(_witnessed_historical_dict("doc-trinity")), encoding="utf-8"
    )
    env = historical_inspect_handle(
        HistoricalInspectInput(question_id="doc-trinity", include_full_schema=False),
        historical_dir=tmp_path,
    )
    assert env["ok"] is True
    assert "witnesses" not in env["result"]
    assert env["result"]["attestation_present"] is True
    assert env["result"]["summary"]


def test_historical_inspect_missing_returns_error(tmp_path: Path) -> None:
    env = historical_inspect_handle(
        HistoricalInspectInput(question_id="doc-missing"), historical_dir=tmp_path
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "historical_missing"


def test_historical_inspect_corrupt_returns_error(tmp_path: Path) -> None:
    bad = _witnessed_historical_dict("doc-trinity")
    bad["id"] = "doc-mismatch"
    (tmp_path / "doc-trinity.json").write_text(json.dumps(bad), encoding="utf-8")
    env = historical_inspect_handle(
        HistoricalInspectInput(question_id="doc-trinity"), historical_dir=tmp_path
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "historical_corrupt"


@pytest.mark.parametrize(
    "malicious",
    [
        "../../../etc/passwd",
        "doc-trinity/../secrets",
        "/etc/passwd",
        "..",
        "doc-trinity/..",
    ],
)
def test_historical_inspect_rejects_path_traversal(tmp_path: Path, malicious: str) -> None:
    env = historical_inspect_handle(
        HistoricalInspectInput(question_id=malicious), historical_dir=tmp_path
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "invalid_question_id"
