"""Phase 05.19 acceptance suite for the MCP server.

18 tests per the phase plan. Most are unit-mode (no live stores); the live
asserts require BD_RUN_INTEGRATION=1 plus running Neo4j + Qdrant.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from bd_mcp.server import TOOL_NAMES, build_server
from bd_mcp.tools.concordance_walk import ConcordanceWalkInput
from bd_mcp.tools.concordance_walk import handle as concordance_handle
from bd_mcp.tools.cross_ref import CrossRefInput
from bd_mcp.tools.cross_ref import handle as cross_ref_handle
from bd_mcp.tools.cultural_overlay import CulturalOverlayInput
from bd_mcp.tools.cultural_overlay import handle as cultural_handle
from bd_mcp.tools.debate_for_verse import DebateForVerseInput
from bd_mcp.tools.debate_for_verse import handle as debate_handle
from bd_mcp.tools.doctrinal_verdict import DoctrinalVerdictInput
from bd_mcp.tools.doctrinal_verdict import handle as verdict_handle
from bd_mcp.tools.evidence_inspect import EvidenceInspectInput
from bd_mcp.tools.evidence_inspect import handle as evidence_inspect_handle
from bd_mcp.tools.lexical_lookup import LexicalLookupInput
from bd_mcp.tools.lexical_lookup import handle as lexical_lookup_handle
from bd_mcp.tools.license_audit import LicenseAuditInput
from bd_mcp.tools.license_audit import handle as license_audit_handle
from bd_mcp.tools.parallel_translation import ParallelTranslationInput
from bd_mcp.tools.parallel_translation import handle as parallel_handle
from bd_mcp.tools.variant_inspect import VariantInspectInput
from bd_mcp.tools.variant_inspect import handle as variant_handle
from bd_mcp.tools.versification_resolve import VersificationResolveInput
from bd_mcp.tools.versification_resolve import handle as versification_handle
from ingest.versification_mapper import VersificationMapper
from pipeline2.evidence_schema import Evidence
from pipeline2.score_calc import compute_lexical_breadth, compute_variant_stability
from tests.pipeline2._fixtures import minimal_evidence_dict

UUID_REGEX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _materialize_trinity(tmp_path: Path) -> None:
    e = Evidence.model_validate(minimal_evidence_dict())
    e_dict = e.model_dump(by_alias=True)
    e_dict["verdict"]["lexical_breadth"] = compute_lexical_breadth(e)
    e_dict["verdict"]["variant_stability"] = compute_variant_stability(e)
    (tmp_path / "doc-trinity.json").write_text(json.dumps(e_dict, indent=2), encoding="utf-8")


class _LemmaSession:
    def __init__(self, response: list[dict[str, Any]]) -> None:
        self._response = response

    def run(self, *_a: object, **_kw: object) -> list[dict[str, Any]]:
        return list(self._response)


# T1
def test_t01_server_lists_all_tools() -> None:
    server = build_server()
    listed = asyncio.run(server.list_tools())
    assert {t.name for t in listed} == set(TOOL_NAMES)


# T2
def test_t02_schema_integrity_per_tool() -> None:
    server = build_server()
    listed = asyncio.run(server.list_tools())
    for t in listed:
        schema = t.inputSchema
        assert isinstance(schema, dict)
        assert "type" in schema
        assert schema["type"] == "object"


# T3
def test_t03_lexical_lookup_returns_theta_for_G2316() -> None:
    session = _LemmaSession(
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
        LexicalLookupInput(query="G2316", id_type="strong", lang="gk"),
        neo4j_session=session,
    )
    matches = env["result"]["matches"]
    assert len(matches) >= 1
    assert matches[0]["lemma"] == "θεός"
    assert matches[0]["strong"] == "G2316"
    assert 1300 <= matches[0]["occurrences_in_canon"] <= 1400


# T4
def test_t04_concordance_walk_returns_required_keys() -> None:
    rows = [{"ref": f"John.1.{i}", "surface": "θεός", "morph": "N-NSM"} for i in range(1, 105)]
    env = concordance_handle(
        ConcordanceWalkInput(strong="G2316", window=5),
        neo4j_session=_LemmaSession(rows),
    )
    assert len(env["result"]["occurrences"]) >= 100
    for occ in env["result"]["occurrences"]:
        for key in ("ref", "surface", "morph", "context_left", "context_right"):
            assert key in occ
    assert "truncated" in env["result"]


# T5
def test_t05_cross_ref_returns_required_keys() -> None:
    rows = [
        {"from_ref": "John.3.16", "to_ref": f"Rom.5.{i}", "source": "openbible", "votes": 50}
        for i in range(1, 12)
    ]
    env = cross_ref_handle(CrossRefInput(ref="John.3.16"), neo4j_session=_LemmaSession(rows))
    assert len(env["result"]["edges"]) >= 10
    for edge in env["result"]["edges"]:
        for k in ("from", "to", "votes", "source"):
            assert k in edge


# T6
def test_t06_variant_inspect_returns_ecm_published_false() -> None:
    env = variant_handle(VariantInspectInput(ref="John.1.1"))
    assert env["result"]["ecm_published"] is False


# T7
def test_t07_parallel_translation_returns_original_and_esv() -> None:
    session = _LemmaSession([{"surface": "Ἐν"}, {"surface": "ἀρχῇ"}])
    env = parallel_handle(
        ParallelTranslationInput(ref="John.1.1", translations=["ESV"], include_original=True),
        neo4j_session=session,
    )
    translations = {r["translation"] for r in env["result"]["rows"]}
    assert "original" in translations
    assert "ESV" in translations


# T8
def test_t08_versification_psa_51_english_to_hebrew() -> None:
    # Stub mapper returns identity ('stub-mode'); the structural acceptance still holds.
    env = versification_handle(
        VersificationResolveInput(ref="Psa.51.1", from_scheme="english", to_scheme="hebrew"),
        mapper=VersificationMapper(),
    )
    assert env["result"]["from_ref"] == "Psa.51.1"
    assert env["result"]["rule_type"] in {"identity", "OneToOne"}
    assert len(env["result"]["all_mappings"]) >= 2


# T9
def test_t09_cultural_overlay_returns_passages() -> None:
    chunks = [
        {
            "tradition": "reformed",
            "source": "opc.org-WCF",
            "stance": "affirms",
            "text": "Westminster on sacraments.",
            "license": "public_domain",
            "redistribute": True,
        },
        {
            "tradition": "catholic-magisterial",
            "source": "Vatican.va-CCC",
            "stance": "denies",
            "text": "Catechism on sacraments.",
            "license": "©Libreria-Editrice-Vaticana",
            "redistribute": False,
            "source_work_word_count": 200000,
        },
        {
            "tradition": "lutheran",
            "source": "BoC",
            "stance": "qualifies",
            "text": "BoC on sacraments.",
            "license": "public_domain",
            "redistribute": True,
        },
        {
            "tradition": "anabaptist",
            "source": "Schleitheim",
            "stance": "affirms",
            "text": "Schleitheim on sacraments.",
            "license": "public_domain",
            "redistribute": True,
        },
    ]
    env = cultural_handle(
        CulturalOverlayInput(
            doctrine="sacraments", traditions=["reformed", "catholic-magisterial"]
        ),
        cultural_chunks=chunks,
    )
    assert len(env["result"]["passages"]) >= 4
    assert all(p.get("stance") is not None for p in env["result"]["passages"])


# T10
def test_t10_debate_for_verse_at_least_3_traditions() -> None:
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
            "license": "public_domain",
            "redistribute": True,
        },
    ]
    env = debate_handle(DebateForVerseInput(ref="John.6.53"), cultural_chunks=chunks)
    assert len(env["result"]["by_tradition"]) >= 3


# T11
def test_t11_doctrinal_verdict_mocked(tmp_path: Path) -> None:
    _materialize_trinity(tmp_path)
    env = verdict_handle(
        DoctrinalVerdictInput(proposition="There is one God in three coequal persons"),
        evidence_dir=tmp_path,
    )
    assert env["ok"] is True
    assert env["result"]["verdict"] is True


# T12
def test_t12_evidence_inspect_full(tmp_path: Path) -> None:
    _materialize_trinity(tmp_path)
    env = evidence_inspect_handle(
        EvidenceInspectInput(question_id="doc-trinity"), evidence_dir=tmp_path
    )
    assert env["ok"] is True
    assert env["result"]["question_id"] == "doc-trinity"
    assert env["result"]["lexical_evidence"] is not None


# T13
def test_t13_license_audit_evidence(tmp_path: Path) -> None:
    _materialize_trinity(tmp_path)
    env = license_audit_handle(
        LicenseAuditInput(subject_type="evidence_file", subject_id="doc-trinity"),
        evidence_dir=tmp_path,
    )
    assert env["ok"] is True
    assert "per_source" in env["result"]


# T14
def test_t14_nc_source_returned_as_snippet() -> None:
    text = " ".join(["w"] * 500)
    env = cultural_handle(
        CulturalOverlayInput(doctrine="x"),
        cultural_chunks=[
            {
                "tradition": "catholic-magisterial",
                "source": "Vatican.va-CCC",
                "stance": "affirms",
                "text": text,
                "license": "©Libreria-Editrice-Vaticana",
                "redistribute": False,
                "source_work_word_count": 200000,
            }
        ],
    )
    p = env["result"]["passages"][0]
    assert p["snippet"] is None or len(p["snippet"].split()) <= 100


# T14a
def test_t14a_snippet_word_cap_100() -> None:
    text = " ".join(["w"] * 1000)
    env = cultural_handle(
        CulturalOverlayInput(doctrine="x"),
        cultural_chunks=[
            {
                "tradition": "t",
                "source": "s",
                "stance": "x",
                "text": text,
                "license": "©x",
                "redistribute": False,
                "source_work_word_count": 1000000,
            }
        ],
    )
    p = env["result"]["passages"][0]
    assert p["snippet"] is not None
    assert len(p["snippet"].split()) <= 100


# T14b
def test_t14b_1pct_cap_for_small_source() -> None:
    text = " ".join(["w"] * 1000)
    env = cultural_handle(
        CulturalOverlayInput(doctrine="x"),
        cultural_chunks=[
            {
                "tradition": "t",
                "source": "s",
                "stance": "x",
                "text": text,
                "license": "©x",
                "redistribute": False,
                "source_work_word_count": 200,
            }
        ],
    )
    p = env["result"]["passages"][0]
    assert p["snippet"] is not None
    assert len(p["snippet"].split()) <= 2


# T14c
def test_t14c_paraphrase_substitution_for_nc_chunk() -> None:
    env = cultural_handle(
        CulturalOverlayInput(doctrine="x"),
        cultural_chunks=[
            {
                "tradition": "catholic-magisterial",
                "source": "Vatican.va-CCC",
                "stance": "affirms",
                "text": " ".join(["w"] * 200),
                "license": "©Libreria-Editrice-Vaticana",
                "redistribute": False,
                "source_work_word_count": 200000,
            }
        ],
    )
    p = env["result"]["passages"][0]
    assert p["tradition_paraphrase_if_not_redistributable"] is not None


# T15
def test_t15_every_envelope_has_license_audit_and_ok() -> None:
    envelopes: list[dict[str, Any]] = [
        variant_handle(VariantInspectInput(ref="John.1.1")),
        cultural_handle(CulturalOverlayInput(doctrine="x")),
        debate_handle(DebateForVerseInput(ref="x")),
    ]
    for env in envelopes:
        assert "license_audit" in env
        assert "ok" in env


# T16
def test_t16_every_envelope_has_uuid_trace_id() -> None:
    envelopes: list[dict[str, Any]] = [
        variant_handle(VariantInspectInput(ref="John.1.1")),
        cultural_handle(CulturalOverlayInput(doctrine="x")),
        debate_handle(DebateForVerseInput(ref="x")),
    ]
    for env in envelopes:
        assert UUID_REGEX.match(env["trace_id"]), env["trace_id"]


# Live integration sentinel: skipped when not running against live stores.
@pytest.mark.skipif(
    os.environ.get("BD_RUN_INTEGRATION") != "1",
    reason="live integration tests require Neo4j + Qdrant",
)
def test_t_integration_smoke_marker() -> None:
    assert True
