"""Pydantic v2 model for the Historical Attestation Schema v1.0.

Canonical spec: ``docs/HISTORICAL_SCHEMA.md``. This module is the executable
contract for ``historical/<question_id>.json`` (the Pipeline 4 output sidecar)
and for the ``HistoricalChunk`` ingest record produced by the
``ingest/historical/`` adapters.

Every model sets ``extra="forbid"`` so an unexpected key is a hard error, not a
silent pass. All free-text fields reject em-dashes (U+2014) and en-dashes
(U+2013) per the standing dash-discipline rule.

The fifteen validator rules enumerated in docs/HISTORICAL_SCHEMA.md
("Validator rules") are each implemented here and cross-referenced by number.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ingest.license_guard import check_redistribute

# ---------------------------------------------------------------------------
# Enumerations (docs/HISTORICAL_SCHEMA.md)
# ---------------------------------------------------------------------------

SourceType = Literal[
    "jewish-historian",
    "jewish-philosopher",
    "second-temple-literature",
    "roman-historian",
    "jewish-rabbinic",
    "qumran-sectarian",
    "qumran-biblical",
]

AttestationType = Literal[
    "corroborates",
    "complicates",
    "neutral",
    "parallel",
    "silent-where-expected",
]

ContestedType = Literal[
    "none",
    "partial-interpolation",
    "recension-layer",
    "text-critical-variant",
]

LossStatus = Literal[
    "complete",
    "partial",
    "fragmentary",
    "reconstructed",
    # The Pipeline 4 prompt's provenance guidance uses these compound forms for
    # works that survive complete only in a downstream language.
    "complete-in-ethiopic",
    "complete-in-syriac",
]

# The named source_slug values (docs/HISTORICAL_SCHEMA.md "Allowed source_slug
# values"). Qumran sigla outside this list are accepted via QUMRAN_SLUG_RE.
NAMED_SOURCE_SLUGS = frozenset(
    {
        "josephus",
        "philo",
        "1enoch",
        "jubilees",
        "test12",
        "2baruch",
        "4ezra",
        "pssol",
        "sibor",
        "tacitus",
        "suetonius",
        "pliny",
        "mishnah",
        "1qs",
        "1qsa",
        "1qsb",
        "1qm",
        "1qha",
        "1qphab",
        "cd",
        "11q19",
        "4qmmt",
        "1qisaa",
        "4qsam-a",
        "4qsam-b",
        "4qdeut-q",
        "11qpsa",
    }
)

# Other Qumran sigla under the convention <cave>Q<number>. The cave number is
# one or two digits (caves 1 through 11), so 11Q19 (Temple Scroll) and 11QpsA
# validate alongside the single-digit caves.
QUMRAN_SLUG_RE = re.compile(r"^\d{1,2}Q[a-z0-9-]+$", re.IGNORECASE)

QUMRAN_SOURCE_TYPES = frozenset({"qumran-sectarian", "qumran-biblical"})

# Rule 13: license registry. A registered slug maps to its canonical
# redistribute flag (docs/HISTORICAL_SCHEMA.md "license fields"). The lexical
# guard recognizes these (PD and CC0 added to _ALWAYS_ALLOWED for the
# historical layer); this table additionally pins the redistribute value so a
# witness cannot mislabel a CC-BY-NC source as redistributable.
LICENSE_REGISTRY: dict[str, bool] = {
    "CC-BY-SA-4.0": True,
    "PD": True,
    "CC-BY": True,
    "CC0": True,
    "CC-BY-NC-4.0": False,
}

# Rule 6: per-source anchor_id patterns (docs/HISTORICAL_SCHEMA.md
# "Anchor-id patterns per source"). Keyed by source_slug. Qumran slugs use the
# DSS columnar/fragmentary patterns regardless of the specific scroll slug.
_PSEUDEP_WORKS = "(?:1enoch|jubilees|2baruch|4ezra|pssol|sibor)"
ANCHOR_PATTERNS: dict[str, re.Pattern[str]] = {
    "josephus": re.compile(r"^josephus\.(?:ant|vita|apion|wars)\.\d+\.\d+$"),
    "philo": re.compile(r"^philo\.[a-z0-9-]+\.\d+$"),
    "tacitus": re.compile(r"^tacitus\.annals\.\d+\.\d+$"),
    "suetonius": re.compile(r"^suetonius\.[a-z0-9-]+\.\d+(?:\.\d+)?$"),
    "pliny": re.compile(r"^pliny\.ep\.\d+\.\d+(?:\.\d+)?$"),
    "mishnah": re.compile(r"^mishnah\.[a-z0-9-]+\.\d+\.\d+$"),
    # Pseudepigrapha: <work>.<chapter>.<verse> with optional sub-verse letter.
    "1enoch": re.compile(rf"^{_PSEUDEP_WORKS}\.\d+\.\d+[a-z]?$"),
    "jubilees": re.compile(rf"^{_PSEUDEP_WORKS}\.\d+\.\d+[a-z]?$"),
    "2baruch": re.compile(rf"^{_PSEUDEP_WORKS}\.\d+\.\d+[a-z]?$"),
    "4ezra": re.compile(rf"^{_PSEUDEP_WORKS}\.\d+\.\d+[a-z]?$"),
    "pssol": re.compile(rf"^{_PSEUDEP_WORKS}\.\d+\.\d+[a-z]?$"),
    "sibor": re.compile(rf"^{_PSEUDEP_WORKS}\.\d+\.\d+[a-z]?$"),
    # test12: <work>.<patriarch>.<chapter>.<verse> (extra named segment).
    "test12": re.compile(r"^test12\.[a-z]+\.\d+\.\d+[a-z]?$"),
}

# DSS columnar: <scroll>.col<NN>.line<NN>; fragmentary:
# <scroll>.f<fragment>[.<col>].line<NN> (e.g. 4q427.f7ii.line14, 1qs.col04.line03).
DSS_ANCHOR_RE = re.compile(
    r"^\d{1,2}q[a-z0-9-]+\.(?:col\d+|f[0-9a-z]+(?:\.col\d+)?)\.line\d+$",
    re.IGNORECASE,
)

_DASH_CHARS = ("—", "–")  # em-dash, en-dash


def _reject_dashes(value: str, field_name: str) -> str:
    """Rule 15: no em-dash and no en-dash in any free-text field."""
    for dash in _DASH_CHARS:
        if dash in value:
            raise ValueError(f"{field_name} contains a forbidden dash character")
    return value


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class ContestedInterpolation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: ContestedType = "none"
    note: str | None = None
    redact_for_embedding: bool = False

    @field_validator("note")
    @classmethod
    def _note_no_dashes(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _reject_dashes(v, "contested_interpolation.note")

    @model_validator(mode="after")
    def _note_required_when_contested(self) -> ContestedInterpolation:
        # Rule 9: note is non-null when type != none.
        if self.type != "none" and (self.note is None or not self.note.strip()):
            raise ValueError(
                f"contested_interpolation.note required when type={self.type!r}"
            )
        if self.type == "none" and self.note is not None:
            # A note on type=none is harmless but the schema reserves note for
            # contested cases; keep it strict so the field carries signal.
            raise ValueError("contested_interpolation.note must be null when type=none")
        return self


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    original_language: str = Field(min_length=1)
    witness_chain: list[str] = Field(min_length=1)  # Rule 11: non-empty
    extant_witnesses: list[str] = Field(default_factory=list)
    loss_status: LossStatus

    @field_validator("witness_chain")
    @classmethod
    def _chain_non_empty_elements(cls, v: list[str]) -> list[str]:
        if any(not isinstance(x, str) or not x.strip() for x in v):
            raise ValueError("provenance.witness_chain has an empty element")
        return v


class WitnessSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_slug: str = Field(min_length=1)
    work_id: str = Field(min_length=1)
    work_title: str = Field(min_length=1)
    author: str | None
    date_written_range: str = Field(min_length=1)
    anchor_id: str = Field(min_length=1)
    anchor_alt_citation: str | None = None
    language: str = Field(min_length=1)
    translator: str | None
    edition: str = Field(min_length=1)

    @field_validator("source_slug")
    @classmethod
    def _slug_registered(cls, v: str) -> str:
        # Rule 5: source_slug is in the named list or matches the Qumran regex.
        if v in NAMED_SOURCE_SLUGS or QUMRAN_SLUG_RE.match(v):
            return v
        raise ValueError(f"source.source_slug {v!r} not allowed")


class Witness(BaseModel):
    model_config = ConfigDict(extra="forbid")
    witness_id: str = Field(min_length=1)
    source_type: SourceType
    source: WitnessSource
    attestation_type: AttestationType
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_phrase: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    contested_interpolation: ContestedInterpolation
    provenance: Provenance
    text: str = Field(min_length=1)
    text_to_embed: str = Field(min_length=1)
    license: str = Field(min_length=1)
    redistribute: bool
    license_note: str | None = None

    @field_validator("text", "text_to_embed")
    @classmethod
    def _nfc_normalize(cls, v: str) -> str:
        # Rule 12: text and text_to_embed are non-empty NFC strings.
        return _nfc(v)

    @field_validator("evidence_phrase")
    @classmethod
    def _evidence_phrase_caps(cls, v: str) -> str:
        # Rule 8: <= 60 words. Rule 15: no dashes.
        _reject_dashes(v, "evidence_phrase")
        if len(v.split()) > 60:
            raise ValueError("evidence_phrase exceeds 60 words")
        return v

    @field_validator("rationale")
    @classmethod
    def _rationale_no_dashes(cls, v: str) -> str:
        return _reject_dashes(v, "rationale")

    @field_validator("license_note")
    @classmethod
    def _license_note_no_dashes(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _reject_dashes(v, "license_note")

    @model_validator(mode="after")
    def _consistency(self) -> Witness:
        # Rule 6: anchor_id matches the per-source pattern.
        slug = self.source.source_slug
        anchor = self.source.anchor_id
        if self.source_type in QUMRAN_SOURCE_TYPES:
            if not DSS_ANCHOR_RE.match(anchor):
                raise ValueError(f"anchor_id {anchor!r} does not match the DSS pattern")
        else:
            pattern = ANCHOR_PATTERNS.get(slug)
            if pattern is None:
                raise ValueError(f"no anchor pattern registered for slug {slug!r}")
            if not pattern.match(anchor):
                raise ValueError(
                    f"anchor_id {anchor!r} does not match the {slug} pattern"
                )

        # witness_id convention: same string as source.anchor_id.
        if self.witness_id != anchor:
            raise ValueError(
                f"witness_id {self.witness_id!r} must equal source.anchor_id {anchor!r}"
            )

        # Rule 13: license registered and redistribute matches the registry.
        expected = LICENSE_REGISTRY.get(self.license)
        if expected is None:
            raise ValueError(f"license {self.license!r} not a registered slug")
        if self.redistribute != expected:
            raise ValueError(
                f"redistribute={self.redistribute} disagrees with registry "
                f"value {expected} for license {self.license!r}"
            )

        # Rule 10: redact_for_embedding consistency with text_to_embed.
        if self.contested_interpolation.redact_for_embedding:
            if self.text_to_embed == self.text:
                raise ValueError(
                    "redact_for_embedding is true but text_to_embed equals text"
                )

        return self


class SourceUsed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_slug: str = Field(min_length=1)
    license: str = Field(min_length=1)
    redistribute: bool


class LicenseAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources_used: list[SourceUsed] = Field(default_factory=list)
    evidence_safe_to_publish: bool
    non_redistributable_reason: str | None = None

    @field_validator("non_redistributable_reason")
    @classmethod
    def _reason_no_dashes(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _reject_dashes(v, "non_redistributable_reason")


# ---------------------------------------------------------------------------
# Top-level Pipeline 4 output: historical/<question_id>.json
# ---------------------------------------------------------------------------


class HistoricalAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["1.0"] = Field(alias="$schema_version")
    id: str = Field(min_length=1)
    question_id: str = Field(min_length=1)
    generated_at: str = Field(min_length=1)
    pipeline_version: str = Field(min_length=1)
    model: str = Field(min_length=1)

    attestation_present: bool
    witnesses: list[Witness] = Field(default_factory=list)
    summary: str = ""

    license_audit: LicenseAudit
    flags: list[str] = Field(default_factory=list)

    @field_validator("summary")
    @classmethod
    def _summary_no_dashes(cls, v: str) -> str:
        return _reject_dashes(v, "summary")

    @model_validator(mode="after")
    def _top_level_consistency(self) -> HistoricalAttestation:
        # Rule 1: id == question_id.
        if self.id != self.question_id:
            raise ValueError(
                f"id {self.id!r} must equal question_id {self.question_id!r}"
            )

        # Rule 3: attestation_present consistent with witnesses length.
        if self.attestation_present and not self.witnesses:
            raise ValueError("attestation_present is true but witnesses is empty")
        if not self.attestation_present and self.witnesses:
            raise ValueError("attestation_present is false but witnesses is non-empty")

        # Rule 14: summary word count.
        word_count = len(self.summary.split())
        if self.attestation_present:
            if not (50 <= word_count <= 300):
                raise ValueError(
                    f"summary must be 50-300 words when attestation_present "
                    f"(got {word_count})"
                )
        else:
            if word_count > 300:
                raise ValueError(
                    f"summary must be 0-300 words when not attestation_present "
                    f"(got {word_count})"
                )

        # No duplicate anchor_id within a single question (witness_id uniqueness).
        seen: set[str] = set()
        for w in self.witnesses:
            if w.witness_id in seen:
                raise ValueError(f"duplicate witness_id {w.witness_id!r}")
            seen.add(w.witness_id)

        return self

    def recompute_evidence_safe_to_publish(self) -> bool:
        """Derive evidence_safe_to_publish from witness licenses (schema formula).

        evidence_safe_to_publish = every source used permits bulk redistribution.
        Mirrors the evidence/ derivation: routes through
        ``ingest.license_guard.check_redistribute(license, "bulk")``.
        """
        return all(
            check_redistribute(src.license, "bulk")["allowed"]
            for src in self.license_audit.sources_used
        )


# ---------------------------------------------------------------------------
# Ingest record: HistoricalChunk (produced by ingest/historical/ adapters)
# ---------------------------------------------------------------------------


class HistoricalChunk(BaseModel):
    """One ingestible unit of an extra-biblical source.

    This is the Pipeline 1 (historical procurement) record. Attestation
    (``attestation_type``, ``confidence``, ``evidence_phrase``) is NOT carried
    on the chunk: it is assigned later by Pipeline 4 on the ``ATTESTS`` edge.
    The chunk is the neutral textual unit that the Pipeline 4 context builder
    surfaces as a candidate for a question.
    """

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1)
    source_type: SourceType
    source: WitnessSource
    contested_interpolation: ContestedInterpolation
    provenance: Provenance
    text: str = Field(min_length=1)
    text_to_embed: str = Field(min_length=1)
    license: str = Field(min_length=1)
    redistribute: bool
    license_note: str | None = None

    @field_validator("text", "text_to_embed")
    @classmethod
    def _nfc_normalize(cls, v: str) -> str:
        return _nfc(v)

    @field_validator("license_note")
    @classmethod
    def _license_note_no_dashes(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _reject_dashes(v, "license_note")

    @model_validator(mode="after")
    def _consistency(self) -> HistoricalChunk:
        slug = self.source.source_slug
        anchor = self.source.anchor_id
        if self.source_type in QUMRAN_SOURCE_TYPES:
            if not DSS_ANCHOR_RE.match(anchor):
                raise ValueError(f"anchor_id {anchor!r} does not match the DSS pattern")
        else:
            pattern = ANCHOR_PATTERNS.get(slug)
            if pattern is None:
                raise ValueError(f"no anchor pattern registered for slug {slug!r}")
            if not pattern.match(anchor):
                raise ValueError(
                    f"anchor_id {anchor!r} does not match the {slug} pattern"
                )

        expected = LICENSE_REGISTRY.get(self.license)
        if expected is None:
            raise ValueError(f"license {self.license!r} not a registered slug")
        if self.redistribute != expected:
            raise ValueError(
                f"redistribute={self.redistribute} disagrees with registry "
                f"value {expected} for license {self.license!r}"
            )

        if self.contested_interpolation.redact_for_embedding:
            if self.text_to_embed == self.text:
                raise ValueError(
                    "redact_for_embedding is true but text_to_embed equals text"
                )
        return self
