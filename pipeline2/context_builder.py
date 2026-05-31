"""Build the lexical context bundle that Pipeline 2 subagents consume.

Queries the lexical Neo4j (apparatus + interlinear + concordance) only. No
cultural store touch. The output shape matches the "Inputs" contract in
docs/phase_prompts/pipeline2_verdict.md.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from neo4j import Driver

from ingest.lexical._common import Settings, get_lexical_driver

QUESTIONS_PATH = Path(__file__).resolve().parent.parent / "questions.json"

CROSS_REF_LIMIT = 20
SEMANTIC_NEIGHBOR_LIMIT = 15
VARIANT_LIMIT = 10
SYNTACTIC_LIMIT = 20
ANCHOR_LEMMA_LIMIT = 40

_REF_PATTERN = re.compile(
    r"^(?P<book>[1-3]?\s?[A-Za-z]+)\s+(?P<chapter>\d+):(?P<verses>\d+(?:-\d+)?)$"
)

_OSIS_BOOKS: dict[str, str] = {
    "Genesis": "Gen",
    "Exodus": "Exod",
    "Leviticus": "Lev",
    "Numbers": "Num",
    "Deuteronomy": "Deut",
    "Joshua": "Josh",
    "Judges": "Judg",
    "Ruth": "Ruth",
    "1 Samuel": "1Sam",
    "2 Samuel": "2Sam",
    "1 Kings": "1Kgs",
    "2 Kings": "2Kgs",
    "1 Chronicles": "1Chr",
    "2 Chronicles": "2Chr",
    "Ezra": "Ezra",
    "Nehemiah": "Neh",
    "Esther": "Esth",
    "Job": "Job",
    "Psalm": "Ps",
    "Psalms": "Ps",
    "Proverbs": "Prov",
    "Ecclesiastes": "Eccl",
    "Song of Solomon": "Song",
    "Isaiah": "Isa",
    "Jeremiah": "Jer",
    "Lamentations": "Lam",
    "Ezekiel": "Ezek",
    "Daniel": "Dan",
    "Hosea": "Hos",
    "Joel": "Joel",
    "Amos": "Amos",
    "Obadiah": "Obad",
    "Jonah": "Jonah",
    "Micah": "Mic",
    "Nahum": "Nah",
    "Habakkuk": "Hab",
    "Zephaniah": "Zeph",
    "Haggai": "Hag",
    "Zechariah": "Zech",
    "Malachi": "Mal",
    "Matthew": "Matt",
    "Mark": "Mark",
    "Luke": "Luke",
    "John": "John",
    "Acts": "Acts",
    "Romans": "Rom",
    "1 Corinthians": "1Cor",
    "2 Corinthians": "2Cor",
    "Galatians": "Gal",
    "Ephesians": "Eph",
    "Philippians": "Phil",
    "Colossians": "Col",
    "1 Thessalonians": "1Thess",
    "2 Thessalonians": "2Thess",
    "1 Timothy": "1Tim",
    "2 Timothy": "2Tim",
    "Titus": "Titus",
    "Philemon": "Phlm",
    "Hebrews": "Heb",
    "James": "Jas",
    "1 Peter": "1Pet",
    "2 Peter": "2Pet",
    "1 John": "1John",
    "2 John": "2John",
    "3 John": "3John",
    "Jude": "Jude",
    "Revelation": "Rev",
}


def to_osis(human_ref: str) -> list[str]:
    """Convert a human ref like 'John 1:1-3' to OSIS BCV refs.

    Returns a list of single-verse refs (one per verse in a range).
    """
    m = _REF_PATTERN.match(human_ref.strip())
    if not m:
        return []
    book = m.group("book").strip()
    osis_book = _OSIS_BOOKS.get(book)
    if not osis_book:
        return []
    chapter = m.group("chapter")
    verses = m.group("verses")
    if "-" in verses:
        lo_s, hi_s = verses.split("-")
        lo, hi = int(lo_s), int(hi_s)
        return [f"{osis_book}.{chapter}.{v}" for v in range(lo, hi + 1)]
    return [f"{osis_book}.{chapter}.{verses}"]


def load_question(question_id: str) -> dict[str, Any]:
    raw = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    for q in raw["questions"]:
        if q["id"] == question_id:
            return q  # type: ignore[no-any-return]
    raise KeyError(f"question id {question_id!r} not in questions.json")


def _anchor_refs(question: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for human in question.get("scripture_anchors", []):
        refs.extend(to_osis(human))
    return refs


# RESEED_PLAN F.1 invariant 4 / Decision 6 / phase_02 variant scope:
# the only ECM/CBGM apparatus ingested is 3 John, verse range 1.1
# through 1.15 inclusive. Any anchor verse outside this exact window
# has no variant apparatus by construction, so the bundle must declare
# not_in_ecm_scope honestly rather than emit a silently empty
# variant_units with no signal that the silence is structural.
_ECM_SCOPE_BOOK = "3John"
_ECM_SCOPE_CHAPTER = 1
_ECM_SCOPE_VERSE_LO = 1
_ECM_SCOPE_VERSE_HI = 15

_ECM_REF_PATTERN = re.compile(r"^3John\.(?P<chapter>\d+)\.(?P<verse>\d+)$")


def _in_ecm_scope(osis_refs: list[str]) -> bool:
    """True iff at least one anchor ref lies in the ingested ECM window.

    Pure: no I/O. The ingested apparatus is exactly
    3John.1.1 .. 3John.1.15 (Decision 6). A single in-window anchor is
    enough for the bundle to be "in scope"; only when every anchor is
    outside the window is the apparatus structurally absent.
    """
    for ref in osis_refs:
        m = _ECM_REF_PATTERN.match(ref)
        if m is None:
            continue
        if int(m.group("chapter")) != _ECM_SCOPE_CHAPTER:
            continue
        verse = int(m.group("verse"))
        if _ECM_SCOPE_VERSE_LO <= verse <= _ECM_SCOPE_VERSE_HI:
            return True
    return False


def _query_anchor_lemmas(driver: Driver, refs: list[str]) -> list[dict[str, Any]]:
    # Decision 15: the universal anchor key is Verse.id = 'verse:' + osisRef.
    # osisID is OT-only (NULL for all NT verses), so keying on it is blind to
    # the entire New Testament. The lemma-bearing token is the STEPBible
    # TaggedToken (it carries the canonical Strong for both OT and NT and
    # INSTANCE_OF lands on Lemma for Hebrew and GreekLemma for Greek; the raw
    # MorphGNT Word carries no Strong). We aggregate by canonical Strong so a
    # lemma that exists under several edition-scoped GreekLemma nodes (Nestle,
    # SBLGNT, ...) yields one row, not duplicates. occurrences_in_canon is the
    # distinct TaggedToken count for that Strong across the whole canon. The
    # canon count anchors on the lexeme node keyed by .strong (then walks
    # INSTANCE_OF back to TaggedToken) so the planner uses a node lookup
    # instead of a full TaggedToken scan, and it is computed only for the
    # rows that survive the LIMIT.
    cypher = """
    UNWIND $refs AS ref
    MATCH (v:Verse {id: 'verse:' + ref})<-[:IN_VERSE]-(t:TaggedToken)
          -[:INSTANCE_OF]->(l)
    WHERE l.strong IS NOT NULL
    WITH l.strong AS strong,
         count(DISTINCT t) AS local_count,
         head(collect(DISTINCT l.lemma)) AS lemma
    ORDER BY local_count DESC, strong
    LIMIT $limit
    CALL (strong) {
        MATCH (tc:TaggedToken)-[:INSTANCE_OF]->(lc)
        WHERE (lc:Lemma OR lc:GreekLemma) AND lc.strong = strong
        RETURN count(DISTINCT tc) AS occurrences_in_canon
    }
    RETURN strong AS strong,
           lemma AS lemma,
           coalesce(lemma, strong) AS transliteration,
           occurrences_in_canon,
           true AS in_anchors
    ORDER BY local_count DESC, occurrences_in_canon DESC, strong
    LIMIT $limit
    """
    with driver.session() as session:
        result = session.run(cypher, refs=refs, limit=ANCHOR_LEMMA_LIMIT)
        return [dict(rec) for rec in result]


def _query_anchor_verses(driver: Driver, refs: list[str]) -> list[dict[str, Any]]:
    # Decision 15: resolve by Verse.id (universal), not osisID (OT-only).
    # Word surface is `surface`/`strong` on the OT OSHB Word and `text` on the
    # NT MorphGNT Word, so coalesce both. Morpheme carries `text`/`strong`
    # (no `morph` property in the live schema).
    cypher = """
    UNWIND $refs AS ref
    MATCH (v:Verse {id: 'verse:' + ref})
    OPTIONAL MATCH (v)<-[:IN_VERSE]-(w:Word)
    OPTIONAL MATCH (w)-[:HAS_MORPHEME]->(m:Morpheme)
    WITH v, w, collect(DISTINCT {morph: coalesce(m.text, ''), lemma: m.strong}) AS morphology
    RETURN v.osis AS ref,
           collect(DISTINCT {
             surface: coalesce(w.surface, w.text, ''),
             strong: w.strong,
             morphology: morphology
           }) AS words,
           '' AS syntactic_role
    """
    with driver.session() as session:
        result = session.run(cypher, refs=refs)
        return [
            {"ref": rec["ref"], "morphology": rec["words"], "syntactic_role": rec["syntactic_role"]}
            for rec in result
        ]


def _query_cross_refs(driver: Driver, refs: list[str]) -> list[dict[str, Any]]:
    # CrossRef.from_ref is the BCV string (e.g. 'Heb.1.1'), populated for NT
    # too, so this anchor key was never osisID-broken; the real edge is
    # (CrossRef)-[:CROSS_REF]->(Verse) (Phase D.4 rev2). Order
    # deterministically by votes then to_ref so the bundle is stable.
    cypher = """
    UNWIND $refs AS ref
    MATCH (cr:CrossRef {from_ref: ref})-[:CROSS_REF]->(:Verse)
    WITH DISTINCT cr
    RETURN cr.from_ref AS from_ref,
           cr.to_ref AS to_ref,
           coalesce(cr.source, 'openbible') AS source,
           coalesce(cr.votes, 1) AS votes
    ORDER BY votes DESC, cr.to_ref, cr.from_ref
    LIMIT $limit
    """
    with driver.session() as session:
        result = session.run(cypher, refs=refs, limit=CROSS_REF_LIMIT)
        return [
            {
                "from": rec["from_ref"],
                "to": rec["to_ref"],
                "source": rec["source"],
                "votes": rec["votes"],
            }
            for rec in result
        ]


def _query_semantic_neighbors(driver: Driver, anchor_strongs: list[str]) -> list[dict[str, Any]]:
    if not anchor_strongs:
        return []
    # Louw-Nida domains attach to MACULA Words via IN_DOMAIN -> LouwNidaDomain
    # (Phase D.4 rev2); the lexeme join key is GreekLemma.strong. A neighbour
    # is any other Greek lexeme sharing a Louw-Nida domain code with an anchor
    # lexeme. The traversal first collapses to the (small) set of anchor
    # domain codes, then fans out to neighbour lexemes in just those codes, so
    # the planner never materialises the full Word x Word co-domain product.
    # It is pinned to one MACULA-Greek edition (SBLGNT) so the same lexeme
    # under several edition-scoped GreekLemma nodes is not multiplied. Hebrew
    # anchors have no IN_DOMAIN edge so this returns empty for OT (not a
    # defect). Deterministic order by domain code then strong.
    cypher = """
    UNWIND $strongs AS s
    MATCH (w:Word {source: 'MACULA-Greek-SBLGNT'})
          -[:INSTANCE_OF]->(gl:GreekLemma)
    WHERE gl.strong = s
    WITH DISTINCT s, w
    MATCH (w)-[:IN_DOMAIN]->(d:LouwNidaDomain)
    WITH collect(DISTINCT d.domain_code) AS codes,
         collect(DISTINCT s) AS anchors
    UNWIND codes AS code
    MATCH (nw:Word {source: 'MACULA-Greek-SBLGNT'})
          -[:IN_DOMAIN]->(:LouwNidaDomain {domain_code: code})
    MATCH (nw)-[:INSTANCE_OF]->(nl:GreekLemma)
    WHERE nl.strong IS NOT NULL AND NOT nl.strong IN anchors
    WITH DISTINCT nl.strong AS strong,
                  head(collect(DISTINCT nl.lemma)) AS lemma,
                  code AS louw_nida
    ORDER BY louw_nida, strong
    LIMIT $limit
    RETURN strong AS strong,
           lemma AS lemma,
           louw_nida AS louw_nida,
           '' AS sdbh
    """
    with driver.session() as session:
        result = session.run(cypher, strongs=anchor_strongs, limit=SEMANTIC_NEIGHBOR_LIMIT)
        return [dict(rec) for rec in result]


def _query_variant_units(driver: Driver, refs: list[str]) -> list[dict[str, Any]]:
    # The apparatus node is VariantUnit keyed by (book, chapter, verse)
    # components, not a Verse relationship; readings attach via
    # (Reading)-[:ATTESTED_BY]->(VariantUnit) (Phase D.4 rev2). Decision 6:
    # only 3 John 1.1..1.15 has apparatus. We split the OSIS BCV ref to key
    # the unit and order deterministically by variant_unit_id.
    cypher = """
    UNWIND $refs AS ref
    WITH ref, split(ref, '.') AS p
    MATCH (vu:VariantUnit {
        book: p[0], chapter: toInteger(p[1]), verse: toInteger(p[2])
    })
    OPTIONAL MATCH (rd:Reading)-[:ATTESTED_BY]->(vu)
    WITH ref, vu,
         collect({witness: rd.reading_id, text: rd.text}) AS readings
    ORDER BY ref, vu.variant_unit_id
    RETURN ref AS ref,
           vu.variant_unit_id AS variant_id,
           readings
    LIMIT $limit
    """
    with driver.session() as session:
        result = session.run(cypher, refs=refs, limit=VARIANT_LIMIT)
        return [
            {"ref": rec["ref"], "variant_id": rec["variant_id"], "readings": rec["readings"]}
            for rec in result
        ]


def _query_syntactic_context(driver: Driver, refs: list[str]) -> list[dict[str, Any]]:
    # ETCBC-BHSA syntax: (BhsaClause)-[:CONTAINS_PHRASE]->(BhsaPhrase)
    # -[:CONTAINS_WORD]->(BhsaWord)-[:IN_VERSE]->(Verse) (Phase D.4 rev2).
    # BHSA covers the Hebrew Bible only; Greek NT verses have no BHSA tree, so
    # the section is structurally empty for NT anchors (not a defect). Order
    # deterministically by clause then phrase id. Decision 15: key by
    # Verse.id, not osisID.
    cypher = """
    UNWIND $refs AS ref
    MATCH (v:Verse {id: 'verse:' + ref})
    OPTIONAL MATCH (v)<-[:IN_VERSE]-(:BhsaWord)<-[:CONTAINS_WORD]-(p:BhsaPhrase)
                   <-[:CONTAINS_PHRASE]-(c:BhsaClause)
    WITH v, c, p
    ORDER BY v.osis, c.id, p.id
    RETURN v.osis AS ref,
           coalesce(c.txt, '') AS clause,
           coalesce(p.txt, '') AS phrase,
           coalesce(p.function, '') AS etcbc_function
    LIMIT $limit
    """
    with driver.session() as session:
        result = session.run(cypher, refs=refs, limit=SYNTACTIC_LIMIT)
        return [dict(rec) for rec in result]


def build_lexical_context_bundle(
    question_id: str, settings: Settings | None = None
) -> dict[str, Any]:
    """Construct the lexical bundle for one question."""
    question = load_question(question_id)
    osis_refs = _anchor_refs(question)

    if settings is None:
        settings = Settings()  # type: ignore[call-arg]
    driver = get_lexical_driver(settings)
    try:
        anchor_lemmas = _query_anchor_lemmas(driver, osis_refs)
        anchor_strongs = [al["strong"] for al in anchor_lemmas]
        anchor_verses = _query_anchor_verses(driver, osis_refs)
        cross_refs = _query_cross_refs(driver, osis_refs)
        semantic_neighbors = _query_semantic_neighbors(driver, anchor_strongs)
        variant_units = _query_variant_units(driver, osis_refs)
        syntactic_context = _query_syntactic_context(driver, osis_refs)
    finally:
        driver.close()

    # RESEED_PLAN F.1 invariant 4: anchors outside the ingested ECM
    # window (3John.1.1 .. 3John.1.15, Decision 6) have no variant
    # apparatus by construction. Declare that structurally rather than
    # leave an unexplained empty variant_units. Variant population logic
    # above is unchanged; this only adds the honest scope flag.
    not_in_ecm_scope = not _in_ecm_scope(osis_refs)

    return {
        "question_id": question_id,
        "question_statement": question["statement"],
        "question_metadata": {
            "category": question.get("category"),
            "subcategory": question.get("subcategory"),
            "kind": question.get("kind"),
            "scripture_anchors": question.get("scripture_anchors", []),
            "historical_consensus": question.get("historical_consensus"),
            "brethren_distinctive": question.get("brethren_distinctive", False),
        },
        "lexical_context_bundle": {
            "anchor_lemmas": anchor_lemmas,
            "anchor_verses": anchor_verses,
            "cross_refs": cross_refs,
            "semantic_domain_neighbors": semantic_neighbors,
            "variant_units": variant_units,
            "not_in_ecm_scope": not_in_ecm_scope,
            "syntactic_context": syntactic_context,
        },
        "schema_version": "3.1",
    }
