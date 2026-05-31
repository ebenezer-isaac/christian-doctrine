"""Shared fixtures for pipeline2 tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def minimal_evidence_dict() -> dict[str, Any]:
    """A well-formed minimal v3.1 evidence payload that should validate."""
    return {
        "$schema_version": "3.1",
        "id": "doc-trinity",
        "question_id": "doc-trinity",
        "generated_at": "2026-05-15T12:00:00Z",
        "pipeline_version": "v1",
        "model": "claude-opus-4-7",
        "verdict": {
            "affirms": True,
            "lexical_breadth": None,
            "lexical_directness": "direct",
            "variant_stability": None,
            "variant_robust": True,
            "pan_canonical": True,
            "rationale": (
                "Anchor lemmas YHWH (H3068), Elohim (H430), Theos (G2316), and Logos (G3056) "
                "establish single divine being with relational distinctions across Deut.6.4, "
                "Matt.28.19, and John.1.1."
            ),
        },
        "lexical_evidence": {
            "anchor_lemmas": [
                {
                    "strong": "H3068",
                    "lemma": "YHWH",
                    "transliteration": "yhwh",
                    "occurrences_in_canon": 6828,
                    "in_anchors": True,
                },
                {
                    "strong": "G2316",
                    "lemma": "θεός",
                    "transliteration": "theos",
                    "occurrences_in_canon": 1317,
                    "in_anchors": True,
                },
            ],
            "concordance_traversed": ["H3068", "H0430", "G2316", "G3056"],
            "scripture": [
                {
                    "ref": "Deut.6.4",
                    "key_terms": [{"strong": "H3068", "lemma": "YHWH"}],
                    "reasoning": (
                        "Shema asserts YHWH as the one being of Israel; echad governs the "
                        "predicate, not a numeric reduction of persons."
                    ),
                    "supports": "for",
                    "genre": "law",
                    "figures": [],
                }
            ],
            "cross_refs_invoked": [
                {"from": "Deut.6.4", "to": "Mark.12.29", "source": "openbible", "votes": 130}
            ],
            "complicating_texts": [
                {
                    "ref": "Mark.13.32",
                    "addressed": True,
                    "resolution": (
                        "communicatio idiomatum: the Son in assumed human nature does not "
                        "access divine omniscience for that disclosure"
                    ),
                }
            ],
        },
        "variants": {
            "verdict_variant_sensitive": False,
            "variant_units_examined": [],
            "ecm_status": "n/a",
            "note": None,
        },
        "hermeneutics": {
            "primary_method": "grammatico-historical",
            "frameworks_in_play": [],
            "analogia_scripturae": True,
            "progressive_revelation": True,
            "competing_lens_verdicts": [],
            "notes": "Standard analogia scripturae across Torah, Gospels, and Pauline corpus.",
        },
        "stem_audit": {
            "verdict_preloaded": False,
            "neutralized_form": None,
            "notes": "Stem describes the proposition without loading the verdict.",
        },
        "lay_summary": _make_lay_summary(),
        "citations": [
            {
                "type": "morphology",
                "source": "MorphGNT-morphology",
                "license": "CC-BY-SA-4.0",
                "redistribute": True,
                "ref": "John.1.1",
            }
        ],
        "license_audit": {
            "sources_used": [
                {"source": "MorphGNT-morphology", "license": "CC-BY-SA-4.0", "redistribute": True}
            ],
            "evidence_safe_to_publish": True,
            "non_redistributable_reason": None,
        },
        "flags": [],
    }


def _make_lay_summary() -> str:
    """200-word lexical-only summary, no dashes, no cultural framing."""
    return (
        "The Hebrew name YHWH appears thousands of times across the Old Testament, always "
        "referring to the one God of Israel who speaks, acts, and covenants with humanity. "
        "Elohim, a plural-form noun, takes singular verbs when it refers to this same God, "
        "indicating a unity that is not numerically simple. In the Greek New Testament, "
        "theos identifies the same being, while logos in John 1 is called theos and was "
        "with theos, distinguishing two referents within one divine reality. Matthew 28 "
        "names Father, Son, and Spirit together with one singular name, treating them as "
        "co-equal recipients of baptismal allegiance. The same pattern shows up when Paul "
        "writes blessings that invoke all three together, or when Peter speaks of the Spirit "
        "as God in Acts 5. Complicating verses such as Mark 13.32, where the Son says he "
        "does not know the day, are addressed by reading them in light of the incarnation, "
        "where the Son operates fully within human limits without surrendering deity. The "
        "lexical pattern holds across law, prophecy, gospel, and epistle, and does not "
        "depend on any single contested variant reading. The picture is one being, three "
        "distinct relational referents, sustained at the level of the words themselves."
    )


def deep_copy(d: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(d)
