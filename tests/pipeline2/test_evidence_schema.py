"""Tests for pipeline2.evidence_schema (v3.1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pipeline2.evidence_schema import Evidence
from tests.pipeline2._fixtures import deep_copy, minimal_evidence_dict


def test_minimal_validates() -> None:
    evidence = Evidence.model_validate(minimal_evidence_dict())
    assert evidence.question_id == "doc-trinity"
    assert evidence.verdict.affirms is True
    assert evidence.verdict.lexical_breadth is None
    assert evidence.verdict.lexical_directness == "direct"
    assert evidence.verdict.variant_stability is None


def test_id_must_equal_question_id() -> None:
    d = minimal_evidence_dict()
    d["id"] = "doc-other"
    with pytest.raises(ValidationError, match="does not match question_id"):
        Evidence.model_validate(d)


def test_schema_version_locked_to_31() -> None:
    d = minimal_evidence_dict()
    d["$schema_version"] = "3.0"  # v30-dead-ref-ok: tests rejection of the old version
    with pytest.raises(ValidationError):
        Evidence.model_validate(d)


def test_extra_top_level_key_rejected() -> None:
    d = minimal_evidence_dict()
    d["bogus"] = "extra"
    with pytest.raises(ValidationError, match="Extra inputs"):
        Evidence.model_validate(d)


def test_extra_key_rejected_in_verdict() -> None:
    d = minimal_evidence_dict()
    d["verdict"]["extra"] = "x"
    with pytest.raises(ValidationError, match="Extra inputs"):
        Evidence.model_validate(d)


def test_extra_key_rejected_in_lexical_evidence() -> None:
    d = minimal_evidence_dict()
    d["lexical_evidence"]["extra"] = "x"
    with pytest.raises(ValidationError, match="Extra inputs"):
        Evidence.model_validate(d)


def test_extra_key_rejected_in_variants() -> None:
    d = minimal_evidence_dict()
    d["variants"]["extra"] = "x"
    with pytest.raises(ValidationError, match="Extra inputs"):
        Evidence.model_validate(d)


def test_extra_key_rejected_in_hermeneutics() -> None:
    d = minimal_evidence_dict()
    d["hermeneutics"]["extra"] = "x"
    with pytest.raises(ValidationError, match="Extra inputs"):
        Evidence.model_validate(d)


def test_extra_key_rejected_in_stem_audit() -> None:
    d = minimal_evidence_dict()
    d["stem_audit"]["extra"] = "x"
    with pytest.raises(ValidationError, match="Extra inputs"):
        Evidence.model_validate(d)


def test_extra_key_rejected_in_citation() -> None:
    d = minimal_evidence_dict()
    d["citations"][0]["extra"] = "x"
    with pytest.raises(ValidationError, match="Extra inputs"):
        Evidence.model_validate(d)


def test_extra_key_rejected_in_license_audit() -> None:
    d = minimal_evidence_dict()
    d["license_audit"]["extra"] = "x"
    with pytest.raises(ValidationError, match="Extra inputs"):
        Evidence.model_validate(d)


@pytest.mark.parametrize("value", [True, False, None, "disputed"])
def test_affirms_accepts_four_states(value: object) -> None:
    d = minimal_evidence_dict()
    d["verdict"]["affirms"] = value
    Evidence.model_validate(d)


@pytest.mark.parametrize("value", ["true", "yes", "maybe", 1, 0])
def test_affirms_rejects_other_values(value: object) -> None:
    d = minimal_evidence_dict()
    d["verdict"]["affirms"] = value
    with pytest.raises(ValidationError):
        Evidence.model_validate(d)


def test_lexical_breadth_none_acceptable() -> None:
    d = minimal_evidence_dict()
    d["verdict"]["lexical_breadth"] = None
    Evidence.model_validate(d)


@pytest.mark.parametrize("band", ["canon_wide", "broad", "partial", "thin"])
def test_lexical_breadth_enum(band: str) -> None:
    d = minimal_evidence_dict()
    d["verdict"]["lexical_breadth"] = band
    Evidence.model_validate(d)


def test_lexical_breadth_rejects_other() -> None:
    d = minimal_evidence_dict()
    d["verdict"]["lexical_breadth"] = "wide"
    with pytest.raises(ValidationError):
        Evidence.model_validate(d)


@pytest.mark.parametrize("directness", ["direct", "inferred", "analogical", "silent"])
def test_lexical_directness_enum(directness: str) -> None:
    d = minimal_evidence_dict()
    d["verdict"]["lexical_directness"] = directness
    if directness == "silent":
        # silent requires affirms=null per validator
        d["verdict"]["affirms"] = None
    Evidence.model_validate(d)


def test_lexical_directness_rejects_other() -> None:
    d = minimal_evidence_dict()
    d["verdict"]["lexical_directness"] = "high"
    with pytest.raises(ValidationError):
        Evidence.model_validate(d)


def test_lexical_directness_required() -> None:
    d = minimal_evidence_dict()
    del d["verdict"]["lexical_directness"]
    with pytest.raises(ValidationError):
        Evidence.model_validate(d)


def test_variant_stability_none_acceptable() -> None:
    d = minimal_evidence_dict()
    d["verdict"]["variant_stability"] = None
    Evidence.model_validate(d)


@pytest.mark.parametrize("stability", ["stable", "sensitive", "not_in_scope"])
def test_variant_stability_enum(stability: str) -> None:
    d = minimal_evidence_dict()
    d["verdict"]["variant_stability"] = stability
    Evidence.model_validate(d)


def test_variant_stability_rejects_other() -> None:
    d = minimal_evidence_dict()
    d["verdict"]["variant_stability"] = "unstable"
    with pytest.raises(ValidationError):
        Evidence.model_validate(d)


def test_silent_requires_null_affirms() -> None:
    """lexical_directness='silent' must pair with affirms=null."""
    d = minimal_evidence_dict()
    d["verdict"]["lexical_directness"] = "silent"
    d["verdict"]["affirms"] = True
    with pytest.raises(ValidationError, match="silent.*requires affirms=null"):
        Evidence.model_validate(d)


def test_silent_with_null_affirms_ok() -> None:
    d = minimal_evidence_dict()
    d["verdict"]["lexical_directness"] = "silent"
    d["verdict"]["affirms"] = None
    Evidence.model_validate(d)


@pytest.mark.parametrize("affirms_other", [False, "disputed"])
def test_silent_rejects_non_null_affirms(affirms_other: object) -> None:
    d = minimal_evidence_dict()
    d["verdict"]["lexical_directness"] = "silent"
    d["verdict"]["affirms"] = affirms_other
    with pytest.raises(ValidationError, match="silent.*requires affirms=null"):
        Evidence.model_validate(d)


@pytest.mark.parametrize("strong", ["H0430", "G2316", "H1254A", "G2316G"])
def test_anchor_lemma_strong_ok(strong: str) -> None:
    d = minimal_evidence_dict()
    d["lexical_evidence"]["anchor_lemmas"][0]["strong"] = strong
    Evidence.model_validate(d)


@pytest.mark.parametrize("strong", ["0430", "H430", "gG2316", "H12345", "X0430", ""])
def test_anchor_lemma_strong_bad(strong: str) -> None:
    d = minimal_evidence_dict()
    d["lexical_evidence"]["anchor_lemmas"][0]["strong"] = strong
    with pytest.raises(ValidationError):
        Evidence.model_validate(d)


@pytest.mark.parametrize("strong", ["H0430", "G2316", "H1254A", "G2316G"])
def test_key_term_strong_ok(strong: str) -> None:
    d = minimal_evidence_dict()
    d["lexical_evidence"]["scripture"][0]["key_terms"][0]["strong"] = strong
    Evidence.model_validate(d)


@pytest.mark.parametrize("strong", ["0430", "H430", "gG2316", "H12345"])
def test_key_term_strong_bad(strong: str) -> None:
    d = minimal_evidence_dict()
    d["lexical_evidence"]["scripture"][0]["key_terms"][0]["strong"] = strong
    with pytest.raises(ValidationError):
        Evidence.model_validate(d)


@pytest.mark.parametrize(
    "figure",
    ["metaphor", "simile", "personification", "chiasm", "merism", "idiom", "hyperbole"],
)
def test_figures_accepts_each(figure: str) -> None:
    d = minimal_evidence_dict()
    d["lexical_evidence"]["scripture"][0]["figures"] = [figure]
    Evidence.model_validate(d)


def test_figures_rejects_analogy() -> None:
    d = minimal_evidence_dict()
    d["lexical_evidence"]["scripture"][0]["figures"] = ["analogy"]
    with pytest.raises(ValidationError):
        Evidence.model_validate(d)


@pytest.mark.parametrize("status", ["ecm-published", "ecm-shadow", "n/a"])
def test_ecm_status_enum(status: str) -> None:
    d = minimal_evidence_dict()
    d["variants"]["ecm_status"] = status
    Evidence.model_validate(d)


def test_ecm_status_rejects_other() -> None:
    d = minimal_evidence_dict()
    d["variants"]["ecm_status"] = "unknown"
    with pytest.raises(ValidationError):
        Evidence.model_validate(d)


@pytest.mark.parametrize(
    "method",
    [
        "grammatico-historical",
        "redemptive-historical",
        "quadriga",
        "patristic-typological",
        "accommodation",
    ],
)
def test_primary_method_enum(method: str) -> None:
    d = minimal_evidence_dict()
    d["hermeneutics"]["primary_method"] = method
    Evidence.model_validate(d)


def test_primary_method_rejects_other() -> None:
    d = minimal_evidence_dict()
    d["hermeneutics"]["primary_method"] = "allegorical-modernist"
    with pytest.raises(ValidationError):
        Evidence.model_validate(d)


@pytest.mark.parametrize(
    "flag",
    [
        "ecm-shadow",
        "concordance-thin",
        "variant-sensitive",
        "lexically-disputed",
        "cross-tradition-divergent",
        "complicating-unresolved",
    ],
)
def test_flags_accepts_standard_slugs(flag: str) -> None:
    d = minimal_evidence_dict()
    d["flags"] = [flag]
    Evidence.model_validate(d)


def test_flags_rejects_unknown() -> None:
    d = minimal_evidence_dict()
    d["flags"] = ["made-up-flag"]
    with pytest.raises(ValidationError):
        Evidence.model_validate(d)


@pytest.mark.parametrize(
    "supports",
    ["for", "complicates", "neutral"],
)
def test_scripture_supports_enum(supports: str) -> None:
    d = minimal_evidence_dict()
    d["lexical_evidence"]["scripture"][0]["supports"] = supports
    Evidence.model_validate(d)


def test_scripture_supports_rejects_other() -> None:
    d = minimal_evidence_dict()
    d["lexical_evidence"]["scripture"][0]["supports"] = "against"
    with pytest.raises(ValidationError):
        Evidence.model_validate(d)


@pytest.mark.parametrize(
    "genre", ["law", "narrative", "wisdom", "prophecy", "gospel", "epistle", "apocalyptic"]
)
def test_scripture_genre_enum(genre: str) -> None:
    d = minimal_evidence_dict()
    d["lexical_evidence"]["scripture"][0]["genre"] = genre
    Evidence.model_validate(d)


def test_scripture_genre_rejects_other() -> None:
    d = minimal_evidence_dict()
    d["lexical_evidence"]["scripture"][0]["genre"] = "torah"
    with pytest.raises(ValidationError):
        Evidence.model_validate(d)


def test_lay_summary_too_short() -> None:
    d = minimal_evidence_dict()
    d["lay_summary"] = "Too short."
    with pytest.raises(ValidationError, match="too short"):
        Evidence.model_validate(d)


def test_lay_summary_too_long() -> None:
    d = minimal_evidence_dict()
    d["lay_summary"] = " ".join(["word"] * 501)
    with pytest.raises(ValidationError, match="too long"):
        Evidence.model_validate(d)


def test_lay_summary_em_dash_rejected() -> None:
    d = minimal_evidence_dict()
    summary = d["lay_summary"]
    summary = summary.replace(",", "—", 1)
    d["lay_summary"] = summary
    with pytest.raises(ValidationError, match="em-dash or en-dash"):
        Evidence.model_validate(d)


def test_lay_summary_en_dash_rejected() -> None:
    d = minimal_evidence_dict()
    summary = d["lay_summary"]
    summary = summary.replace(",", "–", 1)
    d["lay_summary"] = summary
    with pytest.raises(ValidationError, match="em-dash or en-dash"):
        Evidence.model_validate(d)


def test_lay_summary_smart_quotes_ok() -> None:
    d = minimal_evidence_dict()
    summary = d["lay_summary"]
    summary = summary.replace("Hebrew", "“Hebrew”", 1)
    d["lay_summary"] = summary
    Evidence.model_validate(d)


@pytest.mark.parametrize(
    "phrase",
    [
        "the historic Christian position is that God is one being",
        "the Reformed teach the doctrine clearly",
        "the denominational landscape varies on this",
        "catholics teach a different view",
        "by contrast the Lutheran tradition affirms",
        "tradition holds that the trinity is foundational",
        "the Anglican church affirms the Nicene Creed",
    ],
)
def test_lay_summary_cultural_denylist(phrase: str) -> None:
    d = minimal_evidence_dict()
    summary = d["lay_summary"]
    summary = summary[:200] + " " + phrase + " " + summary[200:]
    summary = " ".join(summary.split()[:500])
    d["lay_summary"] = summary
    with pytest.raises(ValidationError, match="cultural-overlay framing"):
        Evidence.model_validate(d)


def test_citation_source_rejects_wcf() -> None:
    d = minimal_evidence_dict()
    d["citations"][0]["source"] = "WCF"
    with pytest.raises(ValidationError, match="ALLOWED_SOURCE_SLUGS"):
        Evidence.model_validate(d)


def test_citation_source_rejects_vatican() -> None:
    d = minimal_evidence_dict()
    d["citations"][0]["source"] = "Vatican.va-CCC"
    with pytest.raises(ValidationError, match="ALLOWED_SOURCE_SLUGS"):
        Evidence.model_validate(d)


def test_citation_source_rejects_carm() -> None:
    d = minimal_evidence_dict()
    d["citations"][0]["source"] = "carm.org"
    with pytest.raises(ValidationError, match="ALLOWED_SOURCE_SLUGS"):
        Evidence.model_validate(d)


def test_citation_source_macula_ok() -> None:
    d = minimal_evidence_dict()
    d["citations"][0]["source"] = "MACULA-Greek"
    Evidence.model_validate(d)


def test_license_audit_inconsistent_ccbync_redistribute_true_rejected() -> None:
    d = minimal_evidence_dict()
    d["license_audit"] = {
        "sources_used": [{"source": "ETCBC-BHSA", "license": "CC-BY-NC-4.0", "redistribute": True}],
        "evidence_safe_to_publish": True,
        "non_redistributable_reason": None,
    }
    with pytest.raises(ValidationError, match="redistribute=True"):
        Evidence.model_validate(d)


def test_license_audit_etcbc_bhsa_must_be_redistribute_false() -> None:
    d = minimal_evidence_dict()
    d["license_audit"] = {
        "sources_used": [
            {"source": "ETCBC-BHSA", "license": "CC-BY-NC-4.0", "redistribute": False}
        ],
        "evidence_safe_to_publish": False,
        "non_redistributable_reason": "Cites BHSA syntactic features under CC-BY-NC-4.0.",
    }
    Evidence.model_validate(d)


def test_license_audit_safe_to_publish_must_be_computed_not_trusted() -> None:
    d = minimal_evidence_dict()
    d["license_audit"] = {
        "sources_used": [
            {"source": "ETCBC-BHSA", "license": "CC-BY-NC-4.0", "redistribute": False}
        ],
        "evidence_safe_to_publish": True,
        "non_redistributable_reason": None,
    }
    with pytest.raises(ValidationError, match="evidence_safe_to_publish"):
        Evidence.model_validate(d)


def test_license_audit_macula_hebrew_composite_resolves_to_ccbync() -> None:
    d = minimal_evidence_dict()
    d["license_audit"] = {
        "sources_used": [
            {"source": "MACULA-Hebrew", "license": "MACULA-Hebrew", "redistribute": False}
        ],
        "evidence_safe_to_publish": False,
        "non_redistributable_reason": "MACULA-Hebrew composite includes MARBLE/SDBH CC-BY-NC-4.0.",
    }
    Evidence.model_validate(d)


def test_license_audit_missing_reason_when_unsafe_rejected() -> None:
    d = minimal_evidence_dict()
    d["license_audit"] = {
        "sources_used": [
            {"source": "ETCBC-BHSA", "license": "CC-BY-NC-4.0", "redistribute": False}
        ],
        "evidence_safe_to_publish": False,
        "non_redistributable_reason": None,
    }
    with pytest.raises(ValidationError, match="non_redistributable_reason required"):
        Evidence.model_validate(d)


def test_generated_at_must_be_iso_utc() -> None:
    d = minimal_evidence_dict()
    d["generated_at"] = "2026/05/15 12:00:00"
    with pytest.raises(ValidationError):
        Evidence.model_validate(d)


def test_generated_at_with_offset_ok() -> None:
    d = minimal_evidence_dict()
    d["generated_at"] = "2026-05-15T12:00:00+00:00"
    Evidence.model_validate(d)


def test_concordance_must_be_strongs() -> None:
    d = minimal_evidence_dict()
    d["lexical_evidence"]["concordance_traversed"] = ["bogus"]
    with pytest.raises(ValidationError):
        Evidence.model_validate(d)


def test_minimal_round_trip_via_dump() -> None:
    e = Evidence.model_validate(minimal_evidence_dict())
    dumped = e.model_dump(by_alias=True)
    e2 = Evidence.model_validate(dumped)
    assert e == e2


def test_deep_copy_independence() -> None:
    d = minimal_evidence_dict()
    d2 = deep_copy(d)
    d["verdict"]["affirms"] = False
    assert d2["verdict"]["affirms"] is True
