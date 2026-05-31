# Historical Attestation Schema v1.0

Sidecar layer parallel to `evidence/<id>.json` (Pipeline 2 lexical) and to the cultural overlay (Pipeline 3). Surfaces extra-biblical historical witnesses (Jewish historians, Jewish philosophy, second-temple literature, Roman historians, rabbinic literature, Qumran texts) as corroborative, complicating, or parallel attestation for doctrinal propositions in `questions.json`.

The Pydantic v2 model lives at `pipeline4/historical_schema.py` with `extra="forbid"` at every level.

## Position in the architecture

The historical layer is air-gapped from Pipeline 2 by the same Docker isolation that protects the lexical store. It shares physical infrastructure with the cultural Docker stack (Neo4j + Qdrant on `cultural_net`) but uses disjoint labels (`HistoricalSource`, `HistoricalWork`, `HistoricalChunk`, `ATTESTS`) and a separate Qdrant collection (`hist_col`). Pipeline 2 verdicts never read this layer; Pipeline 3 synthesis attaches it as a third diagnostic block alongside the lexical verdict and the cultural overlay.

```
evidence/<id>.json        cultural overlay         historical/<id>.json
(lexical verdict)         (Pipeline 3 cult_col)    (this schema)
       │                         │                          │
       ▼                         ▼                          ▼
                    Pipeline 3 synthesis envelope
                    lexical verdict + cultural overlay + historical attestation
```

The historical layer is diagnostic. It NEVER overrides a Pipeline 2 verdict. Where a historical witness complicates a verdict (e.g., the Quirinius census tension at Luke 2:2), the historical block records the complication and the mainstream scholarly resolution; the lexical verdict stands.

## Top-level shape: `historical/<question_id>.json`

```json
{
  "$schema_version": "1.0",
  "id": "doc-john-the-baptist-death",
  "question_id": "doc-john-the-baptist-death",
  "generated_at": "2026-06-XXTXX:XX:XXZ",
  "pipeline_version": "v1",
  "model": "claude-opus-4-7",

  "attestation_present": true,
  "witnesses": [ ... ],
  "summary": "...",

  "license_audit": { ... },
  "flags": []
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `$schema_version` | string | yes | Must equal `"1.0"` |
| `id` | string | yes | Echoes `question_id`; kept for tooling symmetry with `evidence/` |
| `question_id` | string | yes | Must match a `questions[].id` in `questions.json` |
| `generated_at` | ISO 8601 UTC | yes | When Pipeline 4 emitted this file |
| `pipeline_version` | string | yes | Currently `"v1"` |
| `model` | string | yes | Model slug, e.g. `"claude-opus-4-7"` |
| `attestation_present` | bool | yes | True if `witnesses[]` non-empty. Most questions are lexical-only and ship with `attestation_present: false` and `witnesses: []`. |
| `witnesses` | array | yes | Per-witness entries; empty array allowed |
| `summary` | string | yes | 50-300 words plain language. Plain prose explaining what the extra-biblical record adds. Empty allowed when `attestation_present: false`. |
| `license_audit` | object | yes | Aggregated license stack across all `witnesses[].license` |
| `flags` | array | yes | Free-form slug list |

Pydantic validator: `id == question_id`. If `attestation_present: false`, `witnesses[]` must be empty; if `true`, must have at least one entry.

## witness object

Each entry in `witnesses[]`:

```json
{
  "witness_id": "josephus.ant.18.116",
  "source_type": "jewish-historian",

  "source": {
    "source_slug": "josephus",
    "work_id": "josephus.ant",
    "work_title": "Antiquities of the Jews",
    "author": "Flavius Josephus",
    "date_written_range": "93-94 CE",
    "anchor_id": "josephus.ant.18.116",
    "anchor_alt_citation": "Ant 18.5.2 (Whiston)",
    "language": "en",
    "translator": "William Whiston (1737)",
    "edition": "Perseus TEI tlg0526.tlg001.perseus-eng2"
  },

  "attestation_type": "complicates",
  "confidence": 0.85,
  "evidence_phrase": "Now some of the Jews thought that the destruction of Herod's army came from God ... as a just punishment of what Herod had done against John, that was called the Baptist",
  "rationale": "Josephus attributes the political motive (fear of insurrection) without naming Herodias's grudge. Reads as complementary, not contradictory, to Mark 6:17-29; both motives can be simultaneously true.",

  "contested_interpolation": {
    "type": "none",
    "note": null
  },

  "provenance": {
    "original_language": "el",
    "witness_chain": ["greek-niese", "english-whiston-1737"],
    "extant_witnesses": ["MSS A, M, V, W per Niese"],
    "loss_status": "complete"
  },

  "text": "Now some of the Jews thought that the destruction of Herod's army came from God ...",
  "text_to_embed": "Now some of the Jews thought that the destruction of Herod's army came from God ...",

  "license": "CC-BY-SA-4.0",
  "redistribute": true,
  "license_note": "Perseus TEI encoding under CC-BY-SA-4.0; underlying Whiston translation is PD by age."
}
```

### witness_id

Globally unique. Convention: same string as `source.anchor_id`. Multiple witnesses with the same `anchor_id` on the same question are not allowed; if multiple translations of the same passage are wanted, encode them as parallel entries on the same `anchor_id` only when they materially differ in attestation.

### source_type enum

Single value per witness. Seven types tracked in v1.

| Slug | Covers |
|---|---|
| `jewish-historian` | Josephus (Antiquities, Wars, Vita, Against Apion) |
| `jewish-philosopher` | Philo of Alexandria |
| `second-temple-literature` | OT Pseudepigrapha (1 Enoch, Jubilees, Testaments, 2 Baruch, 4 Ezra, Psalms of Solomon, Sibylline Oracles) |
| `roman-historian` | Tacitus, Suetonius, Pliny the Younger |
| `jewish-rabbinic` | Mishnah in v1; Bavli and Yerushalmi deferred to v2 |
| `qumran-sectarian` | DSS non-biblical scrolls (1QS, 1QM, 1QpHab, 1QHa, CD, 11Q19, 4QMMT, etc.) |
| `qumran-biblical` | DSS biblical manuscripts (1QIsa-a, 4QSam, 4QDeut, 11QPs-a, etc.) |

Validator: enum membership only.

### source block

```json
{
  "source_slug": "<canonical-slug>",
  "work_id": "<source_slug>.<work-slug>",
  "work_title": "<full title>",
  "author": "<full name, or null for anonymous works>",
  "date_written_range": "<year or range; BCE/CE explicit>",
  "anchor_id": "<stable per-source anchor>",
  "anchor_alt_citation": "<optional alternate canonical citation>",
  "language": "<ISO 639-1 of text/text_to_embed>",
  "translator": "<name or null>",
  "edition": "<verifiable edition identifier>"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `source_slug` | string | yes | One of the seven values below |
| `work_id` | string | yes | Slug like `josephus.ant`, `philo.de-opificio`, `mishnah.sanhedrin`, `tacitus.annals`, `1enoch`, `1qs` |
| `work_title` | string | yes | Full title in English |
| `author` | string or null | yes | Null for anonymous (Pseudepigrapha attributed to biblical figures), null for collective rabbinic, null for Qumran |
| `date_written_range` | string | yes | Composition date best-estimate (e.g., `"93-94 CE"` for Antiquities, `"c. 200 CE"` for Mishnah, `"c. 100 BCE"` for 1QS); ranges are first-class because most extra-biblical works do not have a single attested year |
| `anchor_id` | string | yes | Stable identifier within the work; see source-specific patterns below |
| `anchor_alt_citation` | string or null | no | Secondary citation for citation parity with classic apologetics (e.g., Whiston's `Ant 18.5.2` alongside the Niese `Ant 18.116`) |
| `language` | string | yes | ISO 639-1 of `text` and `text_to_embed`; `he`, `en`, `la`, `el` are the common values |
| `translator` | string or null | yes | Null for source-language entries |
| `edition` | string | yes | Verifiable edition identifier (Perseus TEI URN, Sefaria version title plus license, CCEL mirror identifier, ETCBC `.tf` version, Wikisource page identifier) |

### Allowed source_slug values

```
josephus
philo
1enoch
jubilees
test12
2baruch
4ezra
pssol
sibor
tacitus
suetonius
pliny
mishnah
1qs        # Community Rule
1qsa
1qsb
1qm        # War Scroll
1qha       # Hodayot
1qphab     # Pesher Habakkuk
cd         # Damascus Document
11q19      # Temple Scroll
4qmmt      # via sigla 4Q394-399
1qisaa
4qsam-a
4qsam-b
4qdeut-q
11qpsa
```

Other Qumran sigla allowed under the convention `<provenance><cave>Q<number>` (e.g., `4q174` for Florilegium). The validator accepts any slug matching `^\d?Q[a-z0-9-]+$` for Qumran in addition to the named list.

### Anchor-id patterns per source

| Source | Pattern | Example |
|---|---|---|
| Josephus | `josephus.<work>.<book>.<niese_section>` where `<work>` in `{ant, vita, apion, wars}` | `josephus.ant.18.116` |
| Philo | `philo.<treatise-slug>.<cohn-wendland-paragraph>` | `philo.de-opificio.1`, `philo.leg-gai.299` |
| Pseudepigrapha | `<work>.<chapter>.<verse>` (sub-verse splits allowed: `1enoch.5.6a`) | `1enoch.1.9`, `jubilees.6.32`, `test12.reuben.1.1` |
| Tacitus | `tacitus.annals.<book>.<chapter>` | `tacitus.annals.15.44` |
| Suetonius | `suetonius.<life>.<chapter>[.<section>]` | `suetonius.claudius.25.4`, `suetonius.nero.16.2` |
| Pliny | `pliny.ep.<book>.<letter>[.<section>]` | `pliny.ep.10.96`, `pliny.ep.10.97` |
| Mishnah | `mishnah.<tractate>.<chapter>.<mishnah>` | `mishnah.sanhedrin.10.1` |
| DSS columnar | `<scroll-slug>.<col>.<line>` | `1qs.col04.line03`, `1qpha.col11.line05` |
| DSS fragmentary | `<scroll-slug>.f<fragment>[.<col>].<line>` | `4q427.f7ii.line14` |

Stability requirement: the anchor MUST be reproducible from the underlying source edition without proprietary lookup tables. A reader holding Niese 1885-1895 or the Perseus TEI must be able to locate the cited passage.

### attestation_type enum

- `corroborates`: external witness aligns with the scriptural claim and adds independent support.
- `complicates`: external witness creates tension with the scriptural claim; the lexical verdict stands but the tension is recorded.
- `neutral`: external witness mentions the event or figure without endorsing or contradicting.
- `parallel`: external witness preserves the same tradition independently (e.g., Jude citing 1 Enoch 1:9; Sanhedrin 10:1 paralleling Pauline resurrection vocabulary).
- `silent-where-expected`: external witness should attest but does not (negative evidence; rare but doctrinally significant when present).

Validator: enum membership.

### confidence

Float in `[0.0, 1.0]`. Self-reported by the Pipeline 4 subagent at emission time.

| Range | Meaning |
|---|---|
| `>= 0.85` | Witness explicitly addresses the proposition |
| `0.60 - 0.85` | Implicit but clearly inferable |
| `< 0.60` | Speculative connection; flagged for human review |

Policy: confidence `< 0.60` writes to `tmp/pipeline4/<task_id>/low_confidence.jsonl` instead of shipping. The orchestrator surfaces the file to the user, who reviews, accepts, modifies, or rejects each witness.

### evidence_phrase

Verbatim phrase from `text` that justifies the attestation. Max 60 words (semantic cap enforced by Pydantic `@field_validator`). Higher than the cultural schema's 30-word cap because historical witnesses often need the surrounding clause for context (e.g., Tacitus on Christus needs both `auctor nominis eius Christus` and `Tiberio imperitante per procuratorem Pontium Pilatum supplicio adfectus erat` to land its force).

### rationale

2-4 sentences explaining why this witness is relevant to the question and how `attestation_type` was assigned. Plain prose. No em or en dashes.

### contested_interpolation block

```json
{
  "type": "none | partial-interpolation | recension-layer | text-critical-variant",
  "note": "<string, null when type is none>",
  "redact_for_embedding": <bool>
}
```

| Type | When to use |
|---|---|
| `none` | Default. Witness is textually stable and uncontested. |
| `partial-interpolation` | Established scholarly view that part of the witness is a later Christian or sectarian insertion. Canonical example: Josephus Antiquities 18.63 (Testimonium Flavianum), where "He was [the] Christ" is universally bracketed. |
| `recension-layer` | The witness as preserved is a known Christianized or sectarian recension of an earlier source. Canonical example: Testaments of the Twelve Patriarchs (Levi-Judah messianism and explicit naming of Jesus). |
| `text-critical-variant` | The cited text is variably read across the manuscript tradition in a way that materially affects attestation. Canonical example: Tacitus Annals 15.44 `Christianos` vs `Chrestianos` in Mediceus II. |

`redact_for_embedding`: when `true`, the contested span is excluded from `text_to_embed` (so retrieval does not surface the disputed prose); the verbatim text is preserved in `text` for citation honesty. Required when `type != none` and the contested span carries material weight.

### provenance block

```json
{
  "original_language": "<ISO 639-1 or ISO 639-3>",
  "witness_chain": ["<earliest extant>", "<intermediate>", "<edition used here>"],
  "extant_witnesses": ["<manuscript sigla or codex names>"],
  "loss_status": "complete | partial | fragmentary | reconstructed"
}
```

Required because the historical layer cites witnesses whose transmission chains are non-trivial. Philo's `De Providentia` survives only in Armenian via Latin via English; 1 Enoch was preserved complete only in Ge'ez; 2 Baruch only in Syriac. A reader needs to see the chain to weigh the witness.

| Field | Notes |
|---|---|
| `original_language` | Use ISO 639-3 (`gez` for Ge'ez, `syr` for Syriac) where ISO 639-1 is insufficient |
| `witness_chain` | Ordered list from earliest extant to the edition cited here. Single-language witnesses use a single-element list (Tacitus Annals 15.44 = `["latin-mediceus-ii"]`). |
| `extant_witnesses` | Manuscript sigla, codex names, or scroll sigla, in scholarly form |
| `loss_status` | `complete` (full work survives), `partial` (some books lost; Tacitus Annals books 7-10 are lost), `fragmentary` (only fragments survive; Hypothetica), `reconstructed` (text is editorially reconstructed from quotation; Hypothetica via Eusebius) |

### text and text_to_embed

```json
{
  "text": "<full verbatim chunk, NFC-normalized>",
  "text_to_embed": "<surface for voyage-4-large; equal to text unless redact_for_embedding is true or DSS chunk under the Option A discipline>"
}
```

For most witnesses, `text_to_embed == text`. Two exceptions in v1.

1. `contested_interpolation.redact_for_embedding == true`: the disputed span is removed from `text_to_embed` while staying in `text`.
2. **DSS (Option A discipline)**: both `text` and `text_to_embed` carry the ETCBC transliteration verbatim. No engine-authored English gloss is pre-baked. At Pipeline 3 synthesis, Opus 4.7 reads the transliteration directly and renders English meaning per query. The Option A bet is that voyage-4-large's multilingual coverage plus the graph-based retrieval path (`HistoricalChunk` to `Doctrine` to `Question`) is sufficient; if retrieval quality proves inadequate after v1 ingest, the same chunks can be augmented in place by setting `text_to_embed` to an engine-authored gloss (Option B fallback) without re-ingesting source data.

### license fields

```json
{
  "license": "<license slug>",
  "redistribute": <bool>,
  "license_note": "<optional clarification>"
}
```

Allowed license slugs per source (v1 scope):

| Source | License | redistribute |
|---|---|---|
| Josephus (Perseus TEI) | `CC-BY-SA-4.0` | true (engine code is MIT/Apache; sidecar JSON inherits SA via separate per-file LICENSE notice) |
| Philo (Yonge, earlychristianwritings.com primary) | `PD` | true |
| Pseudepigrapha (Charles 1913) | `PD` | true |
| Tacitus and Suetonius (Perseus TEI) | `CC-BY-SA-4.0` | true |
| Pliny Latin (Perseus TEI) | `CC-BY-SA-4.0` | true |
| Pliny English (Wikisource Melmoth 1746) | `PD` | true |
| Mishnah Hebrew (Torat Emet 357 or Vilna 1913 via Sefaria) | `PD` | true |
| Mishnah English (Kulp Mishnah Yomit) | `CC-BY` | true |
| Mishnah English (Sefaria Community Translation fallback) | `CC0` | true |
| DSS (ETCBC/dss transliteration and glyph) | `CC-BY-NC-4.0` | false (NC clause blocks engine code redistribution of the data; local storage and personal query is fine) |

Forbidden in v1: William Davidson Bavli English (CC-BY-NC), Wikisource Bavli Hebrew (CC-BY-SA viral), Mechon-Mamre Yerushalmi Hebrew (license unknown), Wise-Abegg-Cook, Vermes, Charlesworth.

## summary

50-300 words plain language. Constraints:

- No em or en dashes.
- No "the historic Christian position is..." framing (that is cultural overlay).
- No "Reformed teach X; Catholics teach Y" (that is cultural overlay).
- Plain prose explaining what the extra-biblical record adds to or complicates about the lexical verdict.
- When `attestation_present: false`, may be an empty string or a one-sentence "No material extra-biblical witness in v1 sources."

Validator: 0 to 300 words when `attestation_present: false`; 50 to 300 words when `true`; rejects em-dash and en-dash characters.

## license_audit block

```json
{
  "license_audit": {
    "sources_used": [
      {"source_slug": "josephus", "license": "CC-BY-SA-4.0", "redistribute": true},
      {"source_slug": "mishnah", "license": "CC-BY", "redistribute": true},
      {"source_slug": "1qpha", "license": "CC-BY-NC-4.0", "redistribute": false}
    ],
    "evidence_safe_to_publish": false,
    "non_redistributable_reason": "Cites ETCBC/dss data under CC-BY-NC-4.0 (1qpha)."
  }
}
```

Derivation matches `evidence/`:
```
evidence_safe_to_publish = all(check_redistribute(license=src.license, mode="bulk", ...)["allowed"] for src in sources_used)
```

If `evidence_safe_to_publish: false`, the orchestrator records the question id in `historical/_non_redistributable.txt` for the publish-time guard.

## flags array

Free-form slug list. Standard slugs:

- `contains-tf-interpolation`: any witness has `contested_interpolation.type == "partial-interpolation"` referencing the Testimonium Flavianum.
- `contains-test12-recension-layer`: any witness has `contested_interpolation.type == "recension-layer"` for Testaments of the Twelve Patriarchs.
- `dss-witness`: any witness has `source_type` in `qumran-sectarian` or `qumran-biblical`. Used by the publish guard to filter at export time.
- `armenian-via-latin`: any Philo witness flagged with this provenance.
- `composite-tradition`: witness preserves the same tradition independently and reading it as direct dependence would overstate the claim (Jude/1 Enoch is the canonical example).
- `silent-where-expected`: any witness has `attestation_type == "silent-where-expected"`.
- `low-confidence-witness-held`: at least one Pipeline 4 candidate was held in `tmp/pipeline4/<task_id>/low_confidence.jsonl` for human review.

## Neo4j historical-attestation store

The historical layer shares the cultural Docker stack but uses disjoint labels.

```cypher
(:HistoricalSource {slug, label, source_type})
    -[:CONTAINS]->
(:HistoricalWork {work_id, title, author, date_written_range, language, original_language, loss_status})
    -[:HAS_CHUNK]->
(:HistoricalChunk {chunk_id, anchor_id, anchor_alt_citation, text, text_to_embed,
                   language, license, redistribute,
                   contested_interpolation_type, provenance_loss_status})
    -[:ATTESTS {attestation_type, confidence, evidence_phrase}]->
(:Doctrine {slug, coarse, fine})

(:Doctrine)-[:UNDER_QUESTION]->(:Question {id})
```

The `:Doctrine` and `:Question` nodes are the same nodes used by the cultural overlay (`:Doctrine` is a shared anchor; the cultural and historical layers attest to the same doctrine vocabulary but through different relationships, `ADDRESSES` for cultural and `ATTESTS` for historical).

Constraint coverage required for the H4 trustworthiness gate: uniqueness on `HistoricalSource.slug`, `HistoricalWork.work_id`, `HistoricalChunk.chunk_id`.

## Qdrant historical collection (`hist_col`) payload

```json
{
  "chunk_id": "<>",
  "source_slug": "<>",
  "source_type": "<>",
  "work_id": "<>",
  "anchor_id": "<>",
  "doctrine_coarse_list": ["..."],
  "doctrine_fine_list": ["..."],
  "attestation_per_doctrine": {"<doctrine_fine>": "corroborates"},
  "contested_interpolation_type": "none",
  "language": "<>",
  "license": "<>",
  "redistribute": <bool>
}
```

Filterable by `source_type`, `attestation_per_doctrine`, `contested_interpolation_type`, `redistribute`.

## Pipeline 4 dispatch contract

Pipeline 4 runs over `questions.json` similarly to Pipeline 2.

1. Pull the question entry.
2. Build a historical-context bundle from the historical store: pull all chunks under `:ATTESTS` to the question's `doctrine_fine` slug. Most questions return zero chunks; only ~30-50 of 231 produce material attestation in v1.
3. If zero chunks, emit `historical/<question_id>.json` with `attestation_present: false`, `witnesses: []`, empty `summary`, and exit.
4. Else, hand the question plus chunks to Opus 4.7 with the Pipeline 4 prompt (see `docs/phase_prompts/pipeline4_attestation.md`).
5. The subagent emits structured JSON conforming to this schema. The deterministic post-processor validates against the v1.0 Pydantic schema (`extra="forbid"`) and writes to `historical/<question_id>.json`.

Pipeline 4 is **resumable from the filesystem**: a question whose `historical/<question_id>.json` already exists is skipped unless explicitly re-dispatched. The same discipline as Pipeline 2.

### Dispatch contract specifics

- `allowed_stores`: `["historical"]` (the historical chunks live under the cultural Docker stack but the dispatch only reads `HistoricalSource | HistoricalWork | HistoricalChunk | ATTESTS` nodes/edges).
- `forbidden_stores`: `["lexical"]` (Pipeline 4 attests; it does not re-derive the lexical verdict).
- The lexical verdict from `evidence/<question_id>.json` is passed in as **context-only** so the subagent understands what the verdict was; Pipeline 4 may not modify or contradict it.
- Cultural overlay chunks are NOT passed to Pipeline 4. The historical layer must read the extra-biblical witness on its own terms, not through a denominational lens.

### Per-source ingest adapters

| Source | Adapter | License | Verified during recon |
|---|---|---|---|
| Josephus | `ingest/historical/josephus.py` | CC-BY-SA-4.0 | Yes (recon GREEN; Testimonium Flavianum interpolation flag required) |
| Philo | `ingest/historical/philo.py` | PD | Yes (recon GREEN; QG and De Providentia provenance flag required for Armenian-via-Latin) |
| Pseudepigrapha | `ingest/historical/pseudepigrapha.py` | PD | Yes (recon GREEN; Test12 recension flag required) |
| Roman historians | `ingest/historical/roman_historians.py` (dual-schema, P4 milestone + P5 EpiDoc) | CC-BY-SA-4.0 | Yes (recon GREEN; Pliny English requires separate Wikisource Melmoth fetch) |
| Pliny English | `ingest/historical/pliny_melmoth.py` | PD | Wikisource fetch, license verified |
| Mishnah | `ingest/historical/sefaria_mishnah.py` | PD HE + CC-BY EN | Yes (recon GREEN) |
| DSS | `ingest/historical/etcbc_dss.py` | CC-BY-NC-4.0 | Yes (recon YELLOW; Option A transliteration-only discipline locked) |

Bavli and Yerushalmi adapters are written and license-flagged but disabled by config in v1 per the recon's split deferral.

## Triangle test

Pipeline 4 outputs are subject to a triangle test analogous to Pipeline 2:

1. Run Pipeline 4 on `question_id=X` once, save to `historical/X.json`.
2. Run again on identical inputs, save to `tmp/pipeline4_triangle/X_run2.json`.
3. Verify:
   - Schema validation passes for both.
   - Set of `witness_id` values matches.
   - `attestation_type` and `confidence` per witness match within `[+/- 0.05]` (slightly looser than Pipeline 2's `0.01` because Pipeline 4 is a less structured judgment task).
   - Order-permutation of inputs produces the same set of witnesses.

## Validator rules

Pydantic validator at `pipeline4/historical_schema.py` enforces:

1. `id == question_id`.
2. `question_id` exists in `questions.json`.
3. `attestation_present` consistent with `witnesses[]` length.
4. Each `witness.source_type` is one of the seven enum values.
5. Each `witness.source.source_slug` is in the allowed list or matches the Qumran regex.
6. Each `witness.anchor_id` matches the per-source pattern (per-source regex set).
7. Each `witness.attestation_type` is one of five enum values.
8. `evidence_phrase.split()` count is `<= 60`.
9. `contested_interpolation.note` is non-null when `type != none`.
10. `contested_interpolation.redact_for_embedding` and `text_to_embed` are consistent (when `redact_for_embedding: true`, `text_to_embed != text`).
11. `provenance.witness_chain` non-empty; `loss_status` in enum.
12. `text` and `text_to_embed` are non-empty NFC strings.
13. `license` is a registered slug in `docs/LICENSE_TAGGING.md`; `redistribute` matches the registry.
14. `summary` word count rule (0-300 if `attestation_present: false`; 50-300 if `true`).
15. No em-dash, no en-dash, anywhere in `summary`, `rationale`, `evidence_phrase`, `note`.

## What is NOT in this schema

- `tradition_weight`: there is no weighting across source types. A rabbinic witness and a Roman witness on the same question carry equal interpretive weight at the schema level; the synthesis stage in Pipeline 3 may render them differently.
- `verdict` field on a chunk or witness: witnesses do not carry verdicts. The lexical verdict comes from `evidence/<id>.json`. The historical witness only attests, complicates, or stands silent.
- `counter_witness_for_lexical_verdict`: explicitly NO. Historical attestation is diagnostic, never adjudicative.
- `denominational_framing`: that is cultural overlay's job.
- `engine_authored_english_gloss` field: not in v1. Option A defers gloss to query-time synthesis. If retrieval quality forces Option B later, the field is added in a v1.1 schema revision.
- `archaeological_attestation`: a separate dimension (epigraphy, numismatics, archaeology). Deferred to a future schema if scope expands.
