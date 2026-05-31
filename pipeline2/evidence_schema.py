"""Pydantic v2 model for Pipeline 2 evidence v3.1.

Schema spec: docs/EVIDENCE_SCHEMA.md. Every level forbids extras. License audit
is validated against ingest/license_guard so caller-supplied redistribute flags
cannot disagree with the registry.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ingest.license_guard import check_redistribute, resolve_composite_license

SCHEMA_VERSION = "3.1"

STRONG_REGEX = re.compile(r"^[HG]\d{4}[A-Z]?$")
ISO_UTC_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
DASH_REGEX = re.compile(r"[–—]")

CULTURAL_DENYLIST = re.compile(
    r"(historic\s+christian\s+position"
    r"|reformed\s+teach"
    r"|catholics?\s+teach"
    r"|lutherans?\s+teach"
    r"|denominational\s+landscape"
    r"|tradition\s+holds"
    r"|the\s+(catholic|reformed|lutheran|orthodox|anglican|methodist|anabaptist|pentecostal)"
    r"\s+church\s+(teaches|holds|affirms|denies)"
    r"|by\s+contrast\s+the\s+\w+\s+tradition)",
    re.IGNORECASE,
)

ALLOWED_SOURCE_SLUGS: frozenset[str] = frozenset(
    {
        "MACULA-Greek",
        "MACULA-Hebrew",
        "MACULA-Hebrew-marble-sdbh",
        "MACULA-Greek-louw-nida",
        "STEPBible-TAHOT",
        "STEPBible-TAGNT",
        "STEPBible-TVTMS",
        "STEPBible-TBESH",
        "STEPBible-TBESG",
        "STEPBible-TFLSJ",
        "OSHB-morphology",
        "MorphGNT-morphology",
        "SBLGNT-text",
        "Nestle1904-text",
        "ETCBC-BHSA",
        "ETCBC-Peshitta",
        "ETCBC-syrnt",
        "ETCBC-DSS",
        "OpenBible-cross-refs",
        "TSK",
        "Theographic-Bible-Metadata",
        "INTF-NTVMR",
        "open-cbgm-3-john-sample",
        "BibleHub-interlinear",
    }
)

STANDARD_FLAGS: frozenset[str] = frozenset(
    {
        "ecm-shadow",
        "concordance-thin",
        "variant-sensitive",
        "lexically-disputed",
        "cross-tradition-divergent",
        "complicating-unresolved",
    }
)

AffirmsValue = Literal[True, False, None, "disputed"]
LexicalBreadth = Literal["canon_wide", "broad", "partial", "thin"]
LexicalDirectness = Literal["direct", "inferred", "analogical", "silent"]
VariantStability = Literal["stable", "sensitive", "not_in_scope"]
Supports = Literal["for", "complicates", "neutral"]
Genre = Literal["law", "narrative", "wisdom", "prophecy", "gospel", "epistle", "apocalyptic"]
Figure = Literal[
    "metaphor",
    "simile",
    "personification",
    "chiasm",
    "merism",
    "idiom",
    "hyperbole",
]
EcmStatus = Literal["ecm-published", "ecm-shadow", "n/a"]
PrimaryMethod = Literal[
    "grammatico-historical",
    "redemptive-historical",
    "quadriga",
    "patristic-typological",
    "accommodation",
]
CitationType = Literal["morphology", "syntax", "cross_ref", "variant", "interlinear", "lexicon"]
VerdictImpact = Literal["none", "minor", "material"]
Flag = Literal[
    "ecm-shadow",
    "concordance-thin",
    "variant-sensitive",
    "lexically-disputed",
    "cross-tradition-divergent",
    "complicating-unresolved",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class AnchorLemma(_Strict):
    strong: str
    lemma: str = Field(min_length=1)
    transliteration: str = Field(min_length=1)
    occurrences_in_canon: int = Field(ge=0)
    in_anchors: bool

    @field_validator("strong")
    @classmethod
    def strong_regex(cls, v: str) -> str:
        if not STRONG_REGEX.match(v):
            raise ValueError(f"strong code {v!r} does not match ^[HG]\\d{{4}}[A-Z]?$")
        return v


class KeyTerm(_Strict):
    strong: str
    lemma: str = Field(min_length=1)

    @field_validator("strong")
    @classmethod
    def strong_regex(cls, v: str) -> str:
        if not STRONG_REGEX.match(v):
            raise ValueError(f"strong code {v!r} does not match ^[HG]\\d{{4}}[A-Z]?$")
        return v


class ScriptureRef(_Strict):
    ref: str = Field(min_length=1)
    key_terms: list[KeyTerm] = Field(min_length=1)
    reasoning: str = Field(min_length=1)
    supports: Supports
    genre: Genre
    figures: list[Figure] = Field(default_factory=list)
    macula_anchor: str | None = None


class CrossRefInvoked(_Strict):
    from_ref: str = Field(min_length=1, alias="from")
    to: str = Field(min_length=1)
    source: Literal["openbible", "tsk"]
    votes: int = Field(ge=0)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ComplicatingText(_Strict):
    ref: str = Field(min_length=1)
    addressed: bool
    resolution: str = Field(min_length=1)


class LexicalEvidence(_Strict):
    anchor_lemmas: list[AnchorLemma] = Field(default_factory=list)
    concordance_traversed: list[str] = Field(default_factory=list)
    scripture: list[ScriptureRef] = Field(default_factory=list)
    cross_refs_invoked: list[CrossRefInvoked] = Field(default_factory=list)
    complicating_texts: list[ComplicatingText] = Field(default_factory=list)

    @field_validator("concordance_traversed")
    @classmethod
    def concordance_strongs(cls, v: list[str]) -> list[str]:
        for item in v:
            if not STRONG_REGEX.match(item):
                raise ValueError(f"concordance_traversed entry {item!r} not a Strong's code")
        return v


class Verdict(_Strict):
    affirms: AffirmsValue
    lexical_breadth: LexicalBreadth | None = None
    lexical_directness: LexicalDirectness
    variant_stability: VariantStability | None = None
    variant_robust: bool
    pan_canonical: bool
    rationale: str = Field(min_length=1)

    @field_validator("affirms", mode="before")
    @classmethod
    def affirms_strict(cls, v: object) -> object:
        if v is None or isinstance(v, bool):
            return v
        if v == "disputed":
            return v
        raise ValueError(f"affirms must be true, false, null, or 'disputed'; got {v!r}")

    @model_validator(mode="after")
    def silent_implies_null_affirms(self) -> Verdict:
        if self.lexical_directness == "silent" and self.affirms is not None:
            raise ValueError(
                f"lexical_directness='silent' requires affirms=null; got affirms={self.affirms!r}. "
                f"If the canon does not engage the subject, the lexical pattern is genuinely insufficient."
            )
        return self


class VariantUnit(_Strict):
    ref: str = Field(min_length=1)
    variant_id: str = Field(min_length=1)
    verdict_impact: VerdictImpact
    note: str = Field(min_length=1)


class Variants(_Strict):
    verdict_variant_sensitive: bool
    variant_units_examined: list[VariantUnit] = Field(default_factory=list)
    ecm_status: EcmStatus
    note: str | None = None


class CompetingLensVerdict(_Strict):
    framework: str = Field(min_length=1)
    verdict: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class Hermeneutics(_Strict):
    primary_method: PrimaryMethod
    frameworks_in_play: list[str] = Field(default_factory=list)
    analogia_scripturae: bool
    progressive_revelation: bool
    competing_lens_verdicts: list[CompetingLensVerdict] = Field(default_factory=list)
    notes: str = ""


class StemAudit(_Strict):
    verdict_preloaded: bool
    neutralized_form: str | None
    notes: str = ""


class Citation(_Strict):
    type: CitationType
    source: str
    license: str = Field(min_length=1)
    redistribute: bool
    ref: str = Field(min_length=1)

    @field_validator("source")
    @classmethod
    def source_allowed(cls, v: str) -> str:
        if v not in ALLOWED_SOURCE_SLUGS:
            raise ValueError(
                f"citation source {v!r} not in ALLOWED_SOURCE_SLUGS; "
                f"confessions and magisterial documents are forbidden in Pipeline 2"
            )
        return v


class SourceUsed(_Strict):
    source: str = Field(min_length=1)
    license: str = Field(min_length=1)
    redistribute: bool


class LicenseAudit(_Strict):
    sources_used: list[SourceUsed]
    evidence_safe_to_publish: bool
    non_redistributable_reason: str | None = None

    @model_validator(mode="after")
    def consistency_with_guard(self) -> LicenseAudit:
        per_source_allowed: list[bool] = []
        for src in self.sources_used:
            result = check_redistribute(license_str=src.license, mode="bulk")
            expected = bool(result["allowed"])
            if src.redistribute != expected:
                effective = resolve_composite_license(src.license)
                raise ValueError(
                    f"license_audit.sources_used entry for {src.source!r}: "
                    f"license={src.license!r} resolves to bulk-allowed={expected} "
                    f"(effective {effective!r}), but redistribute={src.redistribute}. "
                    f"guard reason: {result['reason']}"
                )
            per_source_allowed.append(expected)
        expected_safe = all(per_source_allowed) if per_source_allowed else True
        if self.evidence_safe_to_publish != expected_safe:
            raise ValueError(
                f"evidence_safe_to_publish={self.evidence_safe_to_publish} disagrees with "
                f"per-source bulk-redistribute aggregate={expected_safe}"
            )
        if not expected_safe and not self.non_redistributable_reason:
            raise ValueError(
                "non_redistributable_reason required when evidence_safe_to_publish is false"
            )
        return self


class Evidence(_Strict):
    schema_version: Literal["3.1"] = Field(alias="$schema_version")
    id: str = Field(min_length=1)
    question_id: str = Field(min_length=1)
    generated_at: str
    pipeline_version: str = Field(min_length=1)
    model: str = Field(min_length=1)
    verdict: Verdict
    lexical_evidence: LexicalEvidence
    variants: Variants
    hermeneutics: Hermeneutics
    stem_audit: StemAudit
    lay_summary: str
    citations: list[Citation] = Field(default_factory=list)
    license_audit: LicenseAudit
    flags: list[Flag] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("generated_at")
    @classmethod
    def iso_utc(cls, v: str) -> str:
        if not ISO_UTC_REGEX.match(v):
            raise ValueError(f"generated_at {v!r} is not an ISO 8601 UTC timestamp")
        return v

    @field_validator("lay_summary")
    @classmethod
    def lay_summary_constraints(cls, v: str) -> str:
        if DASH_REGEX.search(v):
            raise ValueError("lay_summary contains em-dash or en-dash; use periods, commas, 'and'")
        words = v.split()
        n = len(words)
        if n < 100:
            raise ValueError(f"lay_summary too short: {n} words; minimum 100")
        if n > 500:
            raise ValueError(f"lay_summary too long: {n} words; maximum 500")
        if CULTURAL_DENYLIST.search(v):
            raise ValueError(
                "lay_summary contains cultural-overlay framing; Pipeline 2 is lexical-only"
            )
        return v

    @model_validator(mode="after")
    def id_matches_question_id(self) -> Evidence:
        if self.id != self.question_id:
            raise ValueError(f"id={self.id!r} does not match question_id={self.question_id!r}")
        return self
