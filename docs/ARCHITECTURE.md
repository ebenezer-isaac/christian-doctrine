# Architecture

Canonical reference for the brethren-doctrine engine. This document is the system specification: it describes the engine as it is and why each commitment is made. A new engineer or agent can read this document alone and understand the whole system with zero archaeology.

## Goal

A manuscript-anchored biblical doctrine engine that produces doctrinal verdicts from the original-language manuscript tradition alone, with cultural and denominational material strictly walled off on the other side of an air-gap. The engine surfaces every meaningful variant in the manuscript record with the scholarly debate around it, so the reader can make informed decisions about contested readings. It is built for one user, personal use, single developer, with the engine code intended for public release on GitHub. Derived corpora are not publicly redistributed because most upstream datasets are CC BY 4.0 with attribution requirements, CC BY-NC for some (ETCBC BHSA, MARBLE / SDBH / Louw-Nida word senses, TTESV, ETCBC/dss), and a few are proprietary in their published apparatus (NA28, BHQ, BDAG, HALOT, DCH, full Gottingen LXX).

The end-user question the engine answers takes a form like: *"Does Brethren teaching on the Lord's Supper match Scripture better than Reformed teaching, and what do the original-language texts say?"* The engine produces a lexical verdict from Scripture alone, then attaches a diagnostic cultural overlay showing how each tracked tradition reads the same lexical pattern, and where the question has an extra-biblical attestation dimension (Quirinius census, Theudas, John the Baptist's death, second-temple background) attaches a third diagnostic block from the historical sidecar layer (Josephus, Philo, Pseudepigrapha, Roman historians, Mishnah, Qumran).

## The four pipelines

The engine is organized as four pipelines that share two physical stores (lexical and cultural; the historical sidecar shares the cultural Docker stack with disjoint labels).

```
INGEST (Pipeline 1)               PRE-INFERENCE (Pipeline 2)         QUERY (Pipeline 3)
─────────────────                 ──────────────────────────         ──────────────────

Open datasets       Lexical store   Opus reads only the              User question
   MACULA           (Docker A:        lexical store.                  via MCP
   STEPBible         Neo4j           For each doctrinal                   │
   ETCBC BHSA        lex_db +        proposition in                       ▼
   OSHB              Qdrant          questions.json:                  Router classifies
   MorphGNT          lex_col)                                         intent
   TSK                  │              walks concordance,                  │
   OpenBible            │              cross-refs, semantic                ▼
   Theographic          │              domains, syntax,               Hybrid retrieve
   INTF NTVMR           │              apparatus where ECM.           dense + BM25
                        │                                             + graph expand
                        ▼              Output:                              │
                   AIR GAP             evidence/<id>.json                   ▼
                   (Docker             with lexical verdict,           BGE rerank
                    network            citations, hermeneutics              │
                    boundary)          block, license_audit.                ▼
                        ▲                                              Opus synthesis
                        │              Stored back to                  reads lexical
Cultural corpus     Cultural store     lexical store.                  store + cultural
   CCEL patristics  (Docker B:                                         store + historical
   Vatican.va       Neo4j cult_db    Triangle test: re-run             store at this stage
   Book of Concord  + Qdrant         on identical inputs                    │
   Reformed         cult_col          band-stable.                          ▼
   Anglican          + hist_col)                                       Output envelope:
   Methodist            │                                              lexical verdict
   Anabaptist           │           Opus tags each cultural             + cultural overlay
   Pentecostal          │           chunk with:                         + historical
   Orthodox             │            (doctrine, stance,                   attestation
   Brethren                          confidence, anchor).               (both diagnostic,
   Conciliar                                                              not authoritative)
                                     PRE-INFERENCE (Pipeline 4)        + citations
Historical corpus   Historical chunks  ─────────────────────────       + variant
   Josephus         (in cultural       Opus reads only the                sensitivity flag
   Philo             stack with        historical store +
   Pseudepigrapha    HistoricalSource/  the locked lexical
   Tacitus           HistoricalWork/    verdict (read-only).
   Suetonius         HistoricalChunk    Per question with a
   Pliny             labels and        historical-attestation
   Mishnah           hist_col)          dimension, produces
   ETCBC/dss            │              historical/<id>.json
                        │              sidecar (Josephus,
                        │              Philo, Mishnah, DSS,
                        ▼              etc.) as corroborative,
                                       complicating, parallel,
                                       or silent-where-expected
                                       witnesses.
```

Pipeline 1 ingests open datasets into two stores. Pipeline 2 runs Opus over the lexical store to produce per-question lexical verdicts. Pipeline 4 runs Opus over the historical chunks to produce per-question historical attestation sidecars at `historical/<id>.json`, never modifying the lexical verdict. Pipeline 3 serves runtime queries through an MCP server, synthesizing across all three stores.

## Two air-gapped stores

The single most important architectural commitment in this project is that the lexical pipeline and the cultural pipeline live in physically separate stores with no possibility of cross-contamination.

**Mechanism.** Two Docker stacks. The lexical stack runs Neo4j 5-community and Qdrant on Docker network `lexical_net`. The cultural stack runs a second Neo4j 5-community and a second Qdrant on Docker network `cultural_net`. Containers on `lexical_net` cannot resolve names on `cultural_net`, and the reverse, because Docker user-defined bridge networks are isolated by default. Pipeline 2 (lexical pre-inference) connects only to the lexical stack. Pipeline 4 (historical pre-inference) connects only to the cultural stack and reads disjoint labels (`HistoricalSource`, `HistoricalWork`, `HistoricalChunk`, `ATTESTS`) plus the read-only `evidence/<id>.json` for context. Pipeline 3 (runtime query synthesis) connects to both stacks, but reads them as separate services with separate license stacks (and within the cultural stack reads the cultural overlay collection `cult_col` and the historical sidecar collection `hist_col` separately), never mixing data into a single fused index.

The air-gap is verified in both directions: a read of the lexical store finds zero cultural-labelled nodes, and a read of the cultural store finds zero lexical-labelled nodes. Cross-network DNS lookups fail with name resolution errors and cross-network HTTP fails with network-unreachable; positive controls within each network confirm DNS is healthy so the negative cross-network results are real isolation.

**Rationale.** Biblical RAG systems that retrieve lexical and confessional sources through the same index, rank them with the same scoring function, and synthesize them in the same prompt context contaminate the verdict. Asking "what does Scripture say about real presence?" returns Trent before BDAG `deipnon`, because there is more confessional material to retrieve so the lexical pattern is downweighted.

This engine refuses to mix them at the data-model level. Pipeline 2 cannot see confessional sources because they are not in the database it queries. The synthesis layer in Pipeline 3 attaches a cultural overlay only after the lexical verdict is locked.

**`internal: true` is intentionally not used.** Setting `internal: true` blocks image pull from the public internet, which would prevent first-time bring-up. The air-gap relies on Docker's default isolation between user-defined bridge networks, which is sufficient for inter-stack isolation. This choice is documented in the compose files.

## Layered architecture

Numbered from manuscript floor to client. Data flows downward in the diagram. Lower numbers feed higher numbers; never the reverse.

| Layer | Role | Tech / data sources |
|---|---|---|
| 0 | Manuscript floor | Hebrew: WLC, OSHB. Greek: SBLGNT, Nestle1904. Versions in scope per `docs/data_inventory_catalog.json` procurement entries: Peshitta (ETCBC, CC-BY-SA-4.0), Vulgate Clementine (public domain), Coptic SCRIPTORIUM (CC-BY-4.0); LXX is resolved via STEPBible LXX columns rather than a standalone Rahlfs ingest. Apparatus: NA28 footnotes via INTF NTVMR transcriptions where published. Excluded per inventory `explicit_deadends`: full ECM beyond 3 John, Old Latin Vetus Latina, LXX Rahlfs standalone, and Dead Sea Scrolls; each exclusion carries its catalog reason and evidence. |
| 0.5 | Versification mapping | STEPBible TVTMS. Every cross-version operation routes through it. |
| 1 | Critical text and apparatus | open-cbgm (MIT) over INTF TEI XML where ECM is published. The 3 John pilot is in scope via the local asset at `tmp/poc/cbgm/` (open-cbgm binaries, `3_john.db`, `3_john_collation.xml`). Catholic Letters beyond 3 John are excluded per inventory `explicit_deadends[0]`. |
| 2 | Unified lexical foundation | MACULA Hebrew + Greek (Clear Bible, CC BY 4.0). Includes WLC + OSHB morphology + Westminster syntax + UBS MARBLE Louw-Nida + Berean glosses. STEPBible TAHOT / TAGNT / TTESV layered on top. Access via Text-Fabric (MIT) for BHSA, ETCBC peshitta, ETCBC syrnt; via lxml for OSHB; via direct .txt parse for MorphGNT. The MACULA-Hebrew `sdbh` semantic-domain attribute is present in the upstream but is not ingested in v1 (see Intentional scope boundaries). |
| 3 | Deterministic analytics | Concordance graph, cross-reference topology (TSK + OpenBible), syntactic structure (ETCBC for Hebrew, MACULA Greek trees), semantic domains (Louw-Nida), pericope boundaries (OpenText annotations). Chiasm detection, stylometry, conceptual metaphor mapping, and speech-act classification beyond the Speaker-Quotations dataset are intentionally not built in v1 (see Intentional scope boundaries). |
| 4 | Lexical verdict engine | Pipeline 2. Opus reads layers 0-3 (no cultural data, ever), produces `evidence/<id>.json` per doctrinal proposition. The LLM is constrained to writing structured evidence; a deterministic post-processor computes `lexical_breadth` and `variant_stability` as bands from the structured fields. The LLM sets `lexical_directness` directly. The LLM cannot override the post-processor bands. |
| 5 | Translation view | STEPBible TTESV plus Clear Bible Alignments. Parallel rendering only. Never feeds Layer 4. |
| 6 | Cultural sibling corpus | CCEL patristic + Vatican.va magisterial + Book of Concord + Reformed confessions + 39 Articles + UMC + Schleitheim + AG + OCA + Plymouth Brethren archives + conciliar. Air-gapped store. |
| 6.5 | Light doctrinal tagging | Per-chunk `(tradition, doctrine_coarse, doctrine_fine, stance, confidence, anchor_id)`. No formal ontology. Opus auto-tags; high-confidence tags ship, low-confidence flagged for review. |
| 6.7 | Historical sibling corpus | Extra-biblical historical attestation: Josephus (Perseus TEI, CC-BY-SA-4.0), Philo (Yonge PD), OT Pseudepigrapha (Charles 1913 PD), Roman historians (Tacitus + Suetonius + Pliny, Perseus TEI, CC-BY-SA-4.0; Pliny English via Wikisource Melmoth PD), Mishnah (Sefaria, PD HE + CC-BY EN Kulp), Qumran (ETCBC/dss, CC-BY-NC-4.0). Air-gapped from the lexical store; co-resident in the cultural Docker stack with disjoint labels `HistoricalSource`, `HistoricalWork`, `HistoricalChunk`, `ATTESTS` and a separate Qdrant collection `hist_col`. Per-chunk schema in `docs/HISTORICAL_SCHEMA.md`. Procurement and explicit deadends in `docs/historical_data_inventory_catalog.json`. |
| 6.8 | Historical-attestation tagging | Per-chunk `(source_type, attestation_type, confidence, contested_interpolation, provenance, evidence_phrase, anchor_id)`. Mirrors 6.5 but with `attestation_type` enum (`corroborates`, `complicates`, `neutral`, `parallel`, `silent-where-expected`) instead of `stance`. |
| 7 | Cultural overlay engine | Pipeline 3 synthesis stage. Reads the Layer 4 verdict, Layer 6/6.5 tags, and Layer 7.1 historical sidecar files. Attaches "how each lineage reads this lexical pattern" plus "how the world around Scripture recorded the event" as diagnostic blocks. Never edits the Layer 4 verdict. |
| 7.1 | Historical attestation engine | Pipeline 4 pre-inference. Per question with a historical-attestation dimension (about 30-50 of 231 in v1), produces `historical/<id>.json` sidecar files holding extra-biblical witnesses with `attestation_type` and source citations. Most questions ship with `attestation_present: false` and empty witnesses. The lexical verdict is read-only context; Pipeline 4 cannot modify or contradict it. |
| 8 | Variant debate surface | Per-verse: every variant in Layer 0, every CBGM-derived reading from Layer 1 where ECM exists, every translation choice from Layer 5, every Layer 4 verdict that is variant-sensitive. The "informed decision" reading surface. Variant data is populated for 3 John in v1 via the Layer 1 CBGM ingest; variants for other Catholic Letters books are excluded per `explicit_deadends[0]`. |
| 9 | MCP server and client | Python MCP SDK (`pip install mcp`). 11 tools (specified in docs/MCP_TOOLS.md). Streamable HTTP transport with progress tokens for the long-running `doctrinal_verdict` tool. The Flutter client surface is intentionally not built in v1; v1 ships as MCP-only, queryable from Claude Code or other MCP-native clients. |

## Authority hierarchy

The authority hierarchy is a discipline applied within the lexical pipeline. Cultural sources are not on it.

| Level | Layer | Source |
|---|---|---|
| 0 | Critical apparatus | BHS footnotes (where extractable), NA28 footnotes via INTF NTVMR transcriptions, ECM apparatus where published |
| 1 | Interlinear + concordance | MACULA Hebrew + Greek, STEPBible, OSHB, MorphGNT, TSK + OpenBible cross-references |
| 2 | Formal-equivalence translation | NKJV, ESV, NASB. Used in Layer 5 parallel rendering. Never as Layer 4 exegetical authority. |
| 3 | Dynamic-equivalence translation | NIV, NLT. Useful for narrative grasp only. Forbidden as Layer 4 exegetical authority. |
| 4 | Exegetical application | Personal teaching notes, archaeology, church history. Treated as commentary, not authority. |

**Confessions do not appear on the hierarchy.** They sit on the cultural sibling track at Layer 6. Counter-witness from any tradition is recorded as diagnostic information for the reader; it never settles a Layer 4 verdict.

**Historical attestation does not appear on the hierarchy either.** Josephus, Philo, Tacitus, Mishnah, Qumran, and the OT Pseudepigrapha sit on the historical sibling track at Layer 6.7. Where a historical witness creates a tension with the Layer 4 verdict (e.g., the Quirinius census), the tension is recorded as diagnostic information in the historical sidecar; the lexical verdict stands.

When tiers disagree within the lexical pipeline, the engine surfaces the conflict rather than silently picking a side. A Level 4 sermon claim cannot override a Level 1 interlinear reading. A Level 1 interlinear reading cannot override a Level 0 apparatus footnote where one exists.

## Pipeline 2 walkthrough

For each doctrinal proposition in `questions.json`, the Pipeline 2 orchestrator does the following.

1. Pull the question entry (id, statement, scripture_anchors, confessional_anchors-as-references-only, historical_consensus metadata).
2. Build a lexical context bundle from the lexical store: anchor lemmas with occurrence counts, anchor verses with surface forms and key terms, cross-references via TSK + OpenBible, semantic-domain neighbors via Louw-Nida, syntactic context where ETCBC has it, any variant units where Layer 1 is populated.
3. Hand the question plus context bundle to Opus with the lean prompt (see `docs/EVIDENCE_SCHEMA.md` for the prompt contract). Opus is forbidden from citing confessions, magisterial documents, denominational commentary, or Reformed-aligned commentary sites. Allowed citations: apparatus, MACULA, STEPBible, ETCBC, BibleHub interlinear, INTF NTVMR.
4. Opus produces structured JSON conforming to the evidence v3.1 schema. Fields cover verdict (affirms / lexical_breadth / lexical_directness / variant_stability / variant_robust / pan_canonical / rationale), lexical_evidence (anchor_lemmas, concordance_traversed, scripture with reasoning / supports / genre / figures / macula_anchor, cross_refs_invoked, complicating_texts), variants block, hermeneutics block, stem_audit, lay_summary, citations with license per source, license_audit.
5. The deterministic post-processor reads the structured fields and assigns `lexical_breadth` as a band derived from a weighted aggregate of six factors (pan_canonical 0.25, anchor_lemma breadth 0.20, complicating_resolved rate 0.15, cross_ref density 0.15, variant_robust flag 0.15, concordance_breadth 0.10) then bucketed into `canon_wide`, `broad`, `partial`, or `thin`. The post-processor also assigns `variant_stability` as `stable`, `sensitive`, or `not_in_scope` from the variants block. Both are order-invariant by construction. The LLM sets `lexical_directness` from one of `direct`, `inferred`, `analogical`, `silent` directly; the LLM never writes the two post-processor bands.
6. The triangle test: re-running on identical inputs produces band equality on `lexical_breadth` and `variant_stability` plus `lexical_directness` drift of at most one step on the `direct` to `inferred` to `analogical` to `silent` axis. Permuted-order inputs also produce identical bands.
7. Validate against the v3.1 Pydantic schema (`extra="forbid"` at every level). Write to `evidence/<question_id>.json`.

**Verdict authority.** `verdict.affirms` is one of `true`, `false`, `null`, `disputed`. `null` covers "lexical pattern is open" and "insufficient evidence." `disputed` covers "lexical pattern is genuinely contested across the canon," reserved for cases like paedobaptism where the lexical evidence supports multiple defensible readings.

**LLM cost path.** Pipeline 2 dispatches Claude Code subagents under the user's Max plan rather than calling the Anthropic API directly. This keeps per-question cost at zero relative to the existing Max subscription. A programmatic API client is wired as a fallback if Max-plan quota is exhausted.

## Pipeline 3 walkthrough

A user question arrives at the MCP server. The router classifies intent (scripture / named_figure / comparative / general / doctrinal-verdict). For doctrinal queries:

1. Retrieve the relevant `evidence/<id>.json` from the lexical store.
2. Retrieve cultural overlay chunks from the cultural store (`cult_col`), filtered by the doctrine slugs in the relevant `questions.json` entry.
3. Retrieve the relevant `historical/<id>.json` sidecar from the historical store (`hist_col`) if `attestation_present: true`; otherwise the historical block is empty.
4. Pass all three to Opus for synthesis with a strict instruction: the lexical evidence is authoritative; the cultural material and historical material are both diagnostic, each in its own block. The output envelope segregates the three with separate citation blocks. The license stack is attached to the envelope so the calling agent never accidentally bulk-exports NC content (most notably ETCBC/dss for DSS chunks).

Streaming: long-running tools (`doctrinal_verdict`) accept a `progressToken` and emit `notifications/progress` events keyed by it, with `{stage, pct}` granularity. Partial JSON is not streamed; the final structured response arrives in one piece.

## Pipeline 4 walkthrough

For each doctrinal proposition in `questions.json`, the Pipeline 4 orchestrator does the following.

1. Pull the question entry and the locked lexical verdict from `evidence/<question_id>.json` (read-only context).
2. Build a historical context bundle by querying the historical store: pull all `HistoricalChunk` nodes connected via `ATTESTS` to the question's `doctrine_fine` slug, plus chunks tagged to the question's named entities (Quirinius, Herod the Tetrarch, John the Baptist, etc.) via cross-reference.
3. If zero candidate chunks are returned and the question has no clear historical-attestation dimension, emit `historical/<question_id>.json` with `attestation_present: false`, `witnesses: []`, empty `summary`, and exit. Most questions land here.
4. Else, hand the question plus context bundle plus locked verdict to Opus with the lean prompt at `docs/phase_prompts/pipeline4_attestation.md`. Opus is forbidden from citing confessions, magisterial documents, denominational commentary, or the cultural overlay. Allowed citations: the seven source types defined in `docs/HISTORICAL_SCHEMA.md` (Josephus, Philo, Pseudepigrapha, Roman historians, Mishnah, Qumran sectarian, Qumran biblical).
5. Opus produces structured JSON conforming to the v1.0 schema. Fields cover witnesses (each with source, attestation_type, confidence, evidence_phrase, rationale, contested_interpolation, provenance, text, text_to_embed, license, redistribute), a plain-language summary, license_audit, and flags.
6. Validate against the v1.0 Pydantic schema (`extra="forbid"` at every level). Write to `historical/<question_id>.json`.
7. Triangle test: re-running on identical inputs produces the same set of `witness_id` values and the same per-witness `attestation_type`. Confidence values match within `+/- 0.05` (looser than Pipeline 2's exact band equality because Pipeline 4 is a less structured judgment task).

**Attestation authority.** `witness.attestation_type` is one of `corroborates`, `complicates`, `neutral`, `parallel`, `silent-where-expected`. A `complicates` finding never modifies the lexical verdict. Where a tension exists, the rationale records the mainstream scholarly resolution and the lexical verdict stands.

**LLM cost path.** Pipeline 4 dispatches Claude Code subagents under the user's Max plan, identically to Pipeline 2. A programmatic API client is wired as a fallback if Max-plan quota is exhausted.

## Orchestrator pattern

All agentic work in this architecture is dispatched in-house through a single orchestrator agent running as a Claude Code session under the user's Max plan. **There is no programmatic Anthropic API access.** No `anthropic` Python package is installed; no `ANTHROPIC_API_KEY` is needed in `.env`; no per-call billing occurs. Every LLM call is a Claude Code subagent dispatch, which consumes Max plan quota.

The orchestrator is the only entity that calls the Agent tool. Subagents do not dispatch further subagents (except for read-only Explore agents when warranted). The orchestrator reads `docs/ARCHITECTURE.md` and the phase prompts in `docs/phase_prompts/` on startup, then routes work according to the operational phase.

### Verifier-caste governance

Every commit carries a `Caste: <name>` trailer and the changed file-set is matched against a per-caste allow-list by `tools/check_caste.py`, enforced as a pre-commit hook. Crossing castes within a single commit is rejected. This makes the work auditable: a reader can replay `tools/check_caste.py --range <A.1-sha>..HEAD` and confirm every commit stayed inside its caste. The castes are: `architect` (schema decisions, the two data-inventory catalogs, this document, the phase docs, the reseed manifest, the graph DDL, `tools/expected_counts.json`), `implementer` and its docstring/impl/z1 variants (one source file plus its tooling), `verifier` and `verifier-z1` (tests only), and `auditor` (the manifest-verification output and the audit reports). A `[SCHEMA-REVISION]`-tagged subject is the only mechanism that authorizes the architect caste to move `tools/expected_counts.json` together with its SHA-lock companion `tools/expected_counts.baseline` in one atomic commit; `tools/check_thresholds_immutable.py` enforces that the count contract cannot drift silently outside such a commit.

### Phase prompts

Each operational phase has an explicit, canonical prompt stored under `docs/phase_prompts/`. The orchestrator loads the relevant prompt verbatim and dispatches a subagent with it. Prompts are self-contained: the subagent does not read the conversation history.

| Phase | Prompt file | Dispatched by | Cardinality | Model |
|---|---|---|---|---|
| Orchestrator (master) | `docs/phase_prompts/orchestrator.md` | Bootstrapped by user | 1 per session | Opus 4.7 |
| Lexical ingest | `docs/phase_prompts/pipeline1_lexical_ingest.md` | Orchestrator | 1 per dataset | Sonnet 4.6 |
| Cultural scrape | `docs/phase_prompts/pipeline1_cultural_scrape.md` | Orchestrator | 1 per cultural source | Sonnet 4.6 |
| Cultural auto-tag | `docs/phase_prompts/cultural_autotag.md` | Orchestrator | 1 per batch of ~50 chunks | Sonnet 4.6 |
| Pipeline 2 verdict | `docs/phase_prompts/pipeline2_verdict.md` | Orchestrator | 1 per doctrinal proposition (231 total) | Opus 4.7 |
| Pipeline 4 attestation | `docs/phase_prompts/pipeline4_attestation.md` | Orchestrator | 1 per doctrinal proposition (231 total; about 30-50 produce non-empty witnesses in v1) | Opus 4.7 |
| Pipeline 3 synthesis | `docs/phase_prompts/pipeline3_synthesis.md` | MCP server (thin orchestrator delegate) | 1 per user query | Sonnet 4.6 default; Opus 4.7 for `doctrinal_verdict` |
| Validation | `docs/phase_prompts/validation.md` | Orchestrator | 1 per validation run | Sonnet 4.6 |

The orchestrator does not embed prompts in code. It reads the markdown files and passes the content as the subagent prompt parameter. Prompt updates are git operations on these files, not code changes.

### Dispatch contract

Every subagent receives, at minimum: the verbatim phase prompt; a JSON `inputs` block scoped to its phase; a target output path under `tmp/<phase>/<task_id>/`; explicit `allowed_stores` and `forbidden_stores` lists. Pipeline 2 verdict has `allowed_stores: ["lexical"]`, `forbidden_stores: ["cultural", "historical"]`. Pipeline 4 attestation has `allowed_stores: ["historical"]`, `forbidden_stores: ["lexical", "cultural"]`, with the locked `evidence/<id>.json` passed in as read-only context (not as a store grant).

Every subagent returns, at minimum: a structured result JSON conforming to the phase's output schema; a `license_audit` block enumerating every source touched; a `confidence` self-assessment.

The orchestrator aggregates results and writes them to the appropriate store via the Pipeline 1 adapter modules (no subagent writes to Neo4j or Qdrant directly).

## Standing trustworthiness gate

The data in both stores is trustworthy because a single self-contained gate proves it, and the proof is re-runnable by an independent auditor at any time.

The gate is the recorded claim file `docs/RESEED_MANIFEST_<timestamp>.json`. It enumerates every claim that must hold for the build to be trustworthy: per-source node counts and per-edge counts against `tools/expected_counts.json`, the INSTANCE_OF completeness figure, the cultural-store counts, the threshold-immutability file lock, the adapter-purity scan, the caste-history scan, the snapshot-determinism property, the vector-quality property, and the procurement-list completeness rule. `tools/verify_manifest.py` independently recomputes every observed value first (pytest, script, cypher, file_sha, grep) and only then diffs against the manifest's recorded expected side, writing the regenerable output `docs/MANIFEST_VERIFICATION_<timestamp>.json`. Exit 0 with every claim matching is the trust proof. `tools/generate_trust_report.py` renders a layman PDF from the newest manifest plus its newest verification output; it auto-discovers the newest of each and never reads any narrative doc.

The gate is structured as nine ordered steps so each threshold is pinned independently rather than depending on the manifest authoring it correctly:

- **H0** the manifest exists and is valid JSON with a `claims` array.
- **H1** `tools/verify_manifest.py` re-executes every claim, computing observed values before the expected side is read; exit 0 and byte-for-byte agreement is required.
- **H2** the adapter, embed-text, and Pipeline-2 pytest suites pass with zero failures.
- **H3** every in-scope source's node/edge count equals its `tools/expected_counts.json` figure at its tier tolerance (Tier A exact tol 0; Tier B plus or minus 2 percent capped 1000; Tier C plus or minus 5 percent).
- **H4** the lexical Qdrant point count is in band and the vector-quality property holds: distinct-vector ratio at least 0.999 with the identical-gloss duplicate exception, and direction-dispersion non-degeneracy (mean pairwise cosine at most 0.95 and pairwise-cosine population stdev at least 1e-4). voyage-4-large returns L2-unit-normalized vectors so a vector-norm-variance test is not the degeneracy proxy; direction collapse is detected directly via pairwise cosine over disjoint random pairs with a fixed seed for a deterministic verdict. Each threshold sits roughly three orders of magnitude clear of both the healthy and the degenerate value, and `tools/check_vector_quality.py --self-test` proves the gate still rejects a genuinely collapsed collection.
- **H5** two consecutive `tools/snapshot_counts.py` runs over identical lexical inputs produce an identical `overall_hash`. The ingest is single-pass deterministic: the `ingest/lexical/run.py` DATASETS dispatch order is a schema contract that places every `{strong}`-keyed Lemma/GreekLemma producer before its consumers, so one fresh pass lands every INSTANCE_OF edge and a second pass is a true no-op.
- **H6** `tools/check_adapter_purity.py` proves every `ingest/lexical/` adapter is pure (no subprocess, socket, httpx, requests, urllib, aiohttp, dynamic import, or non-`data/private` path literal).
- **H7** `tools/check_thresholds_immutable.py` exits 0 (the `tools/expected_counts.json` blob SHA equals the locked baseline, or the last change is a `[SCHEMA-REVISION]` commit moving the baseline in the same commit), the file-SHA claim matches the locked value, and `tools/verify_no_deferral.py` finds zero deferral markers in this document and the schema decisions.
- **H8** `tools/check_caste.py --range <A.1-sha>..HEAD` confirms every commit since the Phase A.1 schema-lock has a `Caste:` trailer matching its changed-file set.

Procurement-list completeness is folded into H1 as a hard claim: every `procurement_required` entry in `docs/data_inventory_catalog.json` that is `compatible_with_project` and not a `deadend` has a passed adapter; a `deadend` is exempt only with `deadend_evidence` plus a committed user approval. The in-scope deadends are full ECM beyond 3 John, Old Latin Vetus Latina, LXX Rahlfs standalone, and DSS; 3 John CBGM is in scope via the local asset.

## Intentional scope boundaries and known limitations

The following are deliberate v1 boundaries. Each states what is not built, why, and the contract that governs adding it. Each is a present-tense scope statement, not a deferral; the build is trustworthy with these boundaries in place.

1. **Cultural ADDRESSES edge and the autotag projection are intentionally not built in v1.** The cultural pipeline scrapes, chunks, and persists `CulturalChunk` + `Work` + `HAS_CHUNK` and seeds `Doctrine` + `Question` + `UNDER_QUESTION`, but the per-chunk `doctrine_tags` to `ADDRESSES` projection is a separate Pipeline-1 tagging phase that v1 does not run. Cultural Schema Decision 4 acceptance is written to tolerate zero `ADDRESSES` edges precisely so a freshly built store still passes the gate. This is a missing phase, not a defective one. The contract that governs adding it: an autotag dispatch wired into `ingest/cultural/run.py` plus a label-scoped projection `MATCH (c:CulturalChunk {chunk_id}),(d:Doctrine {slug}) MERGE (c)-[r:ADDRESSES]->(d) SET r.stance, r.confidence, r.evidence_phrase`, both endpoints constraint-backed, gated behind owner scope sign-off because it is a new phase rather than an adapter change.

2. **The MACULA-Hebrew SDBH semantic-domain overlay is not ingested in v1.** The frozen MACULA-Hebrew upstream carries a populated `sdbh` attribute (roughly 244734 non-null morphemes, occurrence rate about 0.514), but no Schema Decision contracts an SDBH node or edge, no adapter reads the attribute, and `graph/lexical.cypher` provisions no SDBH constraint. Semantic-domain encoding in v1 is Greek Louw-Nida only (Schema Decision 2). The contract that governs adding it: a new architect Decision plus an `SdbhDomain` label and uniqueness constraint in `graph/lexical.cypher`, plus the `macula_hebrew` adapter reading the `<w>` `sdbh` attribute and emitting the domain edge at the proven rate, plus the verifier and a re-ingest.

3. **TVTMS condensed-section completeness is bounded by the upstream artifact contract.** The cross-version mapping consumes `data/private/stepbible/tvtms.parsed.json` (1308 faithful rows). A small set of KJV-Hebrew versification shift rows (Joel 2:28-32 = Joel 3 Hebrew, Jonah 1:17 = Jonah 2:1, Deut 12:32 = Deut 13:1) exist in the frozen raw TVTMS Condensed section but are not in the parsed artifact, so the OpenBible cross-ref count is the faithful-given-available-TVTMS figure (342128) rather than the raw CSV row total. The adapter faithfully quarantines the unresolved rows and never fabricates an inline KJV-to-OSIS map. The contract that governs raising the figure: a producer-plus-consumer change that re-derives `tvtms.parsed.json` from the Condensed section including range-bearing rows and adds per-verse range expansion in the OpenBible and TSK consumers, with the committed-artifact-versus-raw-source contract and the range/Absent/NoVerse/Psalm-Title/multi-ref row-scope semantics ruled by the owner before any remap.

4. **TSK CROSS_REF is keyed on osisID and is correct only because all TSK targets are OT.** The TSK adapter resolves its cross-reference targets through `Verse.osisID`. This is correct for the current corpus because every TSK target verse is in the Old Testament, where `osisID` is populated. The constraint is documented here so a reader does not extend TSK to NT targets without hardening. The contract that governs hardening: re-key the TSK `CROSS_REF` endpoint to the universal `Verse.id` (the same fix already applied to the other cross-version edges, Schema Decision 5/15) before any NT TSK source is added.

5. **`GreekLemma.strong` is non-unique by source design.** Multiple source populations (the disjoint macula_greek, the Hebrew-to-Greek bridge sentinel, and ttesv's own namespace) can carry the same canonical Strong string, so a `.strong` lookup fans out. The fan-out is bounded and accepted: the canonical join contract (Schema Decision 18) keys on the canonical `.strong` string and does not force the disjoint populations to merge, which keeps node identity stable and breaks no uniqueness constraint. Population unification is a separate data-model question that v1 deliberately does not decide.

6. **The lexical adapter write-batch size is conservative by choice.** The adapters write in modest UNWIND batches rather than maximal ones. This trades a slightly longer reseed for predictable Neo4j memory behaviour and clean idempotency, which is the correct default for a single-developer personal engine. Tuning the batch size is a performance change, not a correctness change, and is governed by re-running the H5 snapshot-determinism gate after any change.

7. **Louw-Nida codes are not populated on the `Lemma` node in v1.** The embed-text builder selects `strong, lemma, transliteration, gloss` and the embed text degrades gracefully when `pos`/`domain`/`louw_nida` are absent on a row. Louw-Nida lives on the Greek `Word` to `LouwNidaDomain` `IN_DOMAIN` edge (Schema Decision 2), not as a `Lemma` property. The contract that governs adding it: extend the embed-text query to project `pos`/`domain`/`louw_nida` from the lemma neighborhood, which is an embedding-quality enhancement, not a graph-contract change.

8. **Textless Strong-only lexeme shells are intentionally not embedded.** Lemma rows that carry a Strong key but no gloss/definition text are not sent to the embedder. They remain fully Strong-joinable in the graph; the vector layer is a re-rank stage over text-bearing lexemes, not a completeness mirror of the graph. Embedding empty shells would pollute the distinct-vector ratio without adding retrieval value.

9. **The Augsburg Confession is captured at its currently-available extent.** The Augsburg adapter crawls per-article slug pages; the live count can fall short of the canonical 28-article extent if the upstream crawl is partial. The catalog `live_corpus_bound` is the contract; a partial crawl is treated as a parse fault and quarantined, never widened to mask it. The contract that governs closing the gap: a full live crawl that yields the in-band count, or an architect `[SCHEMA-REVISION]` of the bound if the bound itself is demonstrated wrong.

10. **The F.1 source-completeness invariant set is exercised by separate OT and NT questions rather than one combined question.** Running the five invariants once over an OT-anchored question and once over an NT-anchored question exercises both the Hebrew (BHSA syntax, OSHB word-slot) and Greek (MACULA tree, MorphGNT) paths without a single question that spans both. This is a deliberate test-shape choice; it does not weaken any invariant.

The authoritative count contract for every source and edge lives in `tools/expected_counts.json` (SHA-locked by `tools/expected_counts.baseline`), `docs/data_inventory_catalog.json`, and `docs/cultural_data_inventory_catalog.json`. Those three files are the data contract; this section explains the boundaries around it.

## Stack

- **Python**: 3.12 via uv. The `.venv` at repo root is the canonical venv.
- **Neo4j**: 5-community (Docker, two instances). Lexical at host port 7475/7688, cultural at 7476/7689.
- **Qdrant**: latest (Docker, two instances). Lexical at 7100/7102, cultural at 7101/7103.
- **Voyage**: `voyage-4-large` at native 2048 dimensions for v1 (multilingual; Hebrew, Greek, and English in one embedding space). The v1 ingest is roughly 22M tokens, inside the Voyage free allowance, so embedding cost is zero. voyage-4-large is chosen over the older voyage-3-large and voyage-multilingual-2 because it is strictly higher quality at the identical paid-tier rate limits.
- **Reranker**: BGE-reranker-v2-m3 (Apache-2.0, open weights, multilingual). Loaded locally; no API.
- **LLM**: Claude Opus 4.7 for Pipeline 2 lexical verdicts (highest reasoning quality). Sonnet 4.6 for cultural-corpus auto-tagging and Pipeline 3 query synthesis. Haiku is not used. All LLM dispatch is via in-house Claude Code subagents under the user's Max plan. Programmatic Anthropic API access is forbidden in this architecture.
- **MCP**: official Python SDK (`pip install mcp`). FastMCP server pattern. Streamable HTTP transport per the 2025-06-18 spec revision.
- **Text-Fabric**: 13.x for BHSA / ETCBC peshitta / ETCBC syrnt access.
- **Anthropic SDK**: not installed, not used. No programmatic API path. All agentic work routes through Claude Code subagents.

## License posture

Every chunk and node carries an explicit `license` field. Synthesis enforces redistribution rules through the `license_guard.check_redistribute()` function (see `docs/LICENSE_TAGGING.md`). A `redistribute = false` source persists its `text_to_embed` surface in place of the verbatim `text`, in both the Neo4j store and the Qdrant payload, so copyrighted prose is never landed verbatim in either store.

| Tier | Posture | Sources |
|---|---|---|
| Permissive open | Allowed in bulk, attribution required | MACULA (Clear Bible CC BY 4.0), STEPBible TAHOT / TAGNT / TVTMS (CC BY 4.0), OSHB (CC BY 4.0), OpenBible (CC BY), public-domain confessions (WCF, 1689 LBC, Heidelberg, Belgic, Dort, 39 Articles, BCP 1662, Schleitheim, UMC Articles, Book of Concord older translations), CCEL ANF / NPNF (PD), conciliar texts via Wikisource (PD), pre-1923 Plymouth Brethren writings (PD), Philo Yonge 1854 (PD), OT Pseudepigrapha Charles 1913 (PD), Pliny Melmoth 1746 (PD), Mishnah Hebrew Torat Emet 357 (PD), Mishnah English Sefaria Community Translation (CC0), Mishnah English Kulp Mishnah Yomit (CC-BY) |
| Open share-alike | Allowed; derivatives must propagate SA | MorphGNT morphology (CC BY-SA 4.0), Theographic Bible Metadata (CC BY-SA 4.0), First1KGreek (CC BY-SA 4.0), Josephus Perseus TEI (CC BY-SA 4.0), Tacitus + Suetonius + Pliny Perseus TEI (CC BY-SA 4.0) |
| Open non-commercial | Personal use only; bulk export forbidden | ETCBC BHSA (CC BY-NC 4.0), MARBLE / SDBH / Louw-Nida word senses (CC BY-NC), STEPBible TTESV (CC BY-NC 4.0), ETCBC/dss Qumran transliteration and glyph data (CC BY-NC 4.0) |
| EULA-restricted | Snippet quotation OK; bulk forbidden; per-vendor reporting | SBLGNT text (SBLGNT EULA; at most 500 verses per year without a separate license) |
| Proprietary / fair-use only | Snippet only, never bulk | Vatican.va content (Libreria Editrice Vaticana copyright); AG Fundamental Truths; OCA topical articles; modern Book of Concord translations (Tappert / Kolb-Wengert) |

**v1 posture: 100% open.** No proprietary purchases. No paid lexicons. No paid ECM apparatus. The reference budget goes to print NA28 + UBS6 + ECM Catholic Letters Part 1 for human cross-check, not for ingestion.

**Public release of derivatives.** The engine code is intended for GitHub release under MIT or Apache-2.0. Derived corpora are not redistributed; the engine works against the user's locally-ingested data. Sample evidence outputs may be published only when they cite permissively-licensed source layers (the license_audit field `evidence_safe_to_publish` must be `true`).

## Hosting model

Hybrid. Biblical data and both stores run locally in Docker. LLM (Opus, Sonnet via Max plan) and embedding (Voyage via free tier) calls go to cloud APIs. The BGE reranker runs locally.

**Why hybrid.** Local data means the engine works offline for lookups and is independent of upstream service uptime. Cloud LLM means no model runs locally (outside personal scope). The Voyage free tier means embedding is zero-cost at v1 scale.

**Refresh.** Datasets are pinned at commit SHAs in `pipeline1/lockfile.json`. Refresh is manual: bump the SHA, re-ingest, re-embed. No automatic git pulls. OpenBible cross-references drift monthly and are pinned to a release date in the lockfile.

## Database backup and restore

Both Docker stacks are backed up and restorable. The restore procedure, the snapshot layout, and the volume mapping are documented in `backups/RESTORE.md` (this file is local and gitignored; it is the operational runbook for bringing either store back from a snapshot). The standing trustworthiness gate is the post-restore acceptance check: a restored store is trusted only after `tools/verify_manifest.py` exits 0 against it.

## Engineering invariants

These are non-negotiable for implementation.

1. **Canonical Strong's normalization at Pipeline 1 entry.** Five sources use five encodings (MACULA-H zero-pads `0430`, OSHB slash-prefixed `b/7225`, STEPBible curly-brace `{H0430G}`, MACULA-G plain `2316`, TAGNT prefixed `G`). `ingest/canonical_strongs.canonical_strongs()` is the single normaliser; no adapter hand-rolls one. Cross-validation against all five reps is a unit test. The canonical join key is `Lemma.strong` / `GreekLemma.strong` carrying the canonical string (Schema Decision 18).
2. **Hebrew dual-granularity model.** OSHB collapses prefix plus stem (Gen 1:1 = 7 words). MACULA and BHSA split (11 morphemes). Both layers are ingested: `(:Word)-[:HAS_MORPHEME]->(:Morpheme)` with bidirectional edges.
3. **TVTMS is a 3-stage mapping service.** Block-scoped rules, rule types (OneToOne, SubdividedVerse), tradition columns. It is a `VersificationMapper` service, not a lookup table.
4. **MACULA Hebrew Hebrew-to-Greek cross-reference bridge.** Each `<w>` carries `greek` and `greekstrong` attributes, ingested as `BRIDGES_LXX` edges from Hebrew `Lemma` to Greek `GreekLemma` (Schema Decision 4). A null `greekstrong` with a populated `greek` is a meaningful bridge routed to the documented sentinel `GreekLemma`, never dropped; the nullable bridge properties are set after the relationship MERGE so a null pattern property never raises.
5. **MorphGNT is parsed directly.** `pysblgnt` is dead on PyPI; the SBLGNT is read by direct `.txt` parse (space-delimited, 7 columns).
6. **Text-Fabric path quirk.** `use()` resolves `~/github/...`, not `~/text-fabric-data/github/...`. The bootstrap symlinks or passes `locations=`.
7. **OpenBible "To Verse" ranges explode at ingest.** `Rom.1.19-Rom.1.20` becomes two edges. Range queries are handled at retrieval time, not stored as a range property.
8. **Voyage model is `voyage-4-large` at native 2048 dimensions.** Multilingual. At usage tier 1 the limits (3M TPM / 2000 RPM) exceed the v1 ingest budget.
9. **TTESV is CC BY-NC**, unlike the rest of STEPBible. It is tagged explicitly at ingest.
10. **Sparse-checkout strategy.** MACULA Hebrew full clone is 1.5 GB; Greek is 655 MB. TSV-only sparse checkout keeps the total under 500 MB.
11. **Cultural scrape link-rot mitigation.** Wikisource slug drift and TLS-fragile mirrors are handled by recording a canonical URL plus fallback URLs per source and re-probing on failure. A fallback is never a certificate-verification bypass.
12. **Universal `Verse.id` is the cross-version join key.** Every verse-resolving edge (`IN_VERSE`, `PARALLEL_OF`, `OPENBIBLE_CROSS_REF`, `MENTIONS`, `NAMED_AT`) keys on the universal `Verse.id`, never on `Verse.osisID` (which is null on NT verses by Schema Decision 15). This is why those edges resolve on both testaments.
13. **Docker air-gap relies on Docker default bridge isolation**, not `internal: true`. Documented in the compose comments.
14. **Cultural tag count cap.** A Pydantic validator rejects more than 5 doctrine_tags per chunk.
15. **Node-MERGE constraint coverage is complete.** Every `MERGE (n:Label {key})` on both stores is backed by a uniqueness constraint so the reseed index-seeks rather than scans (including `MaculaToken.id`). This is verified against both the DDL files and the live stores.

## Anti-patterns avoided

| Anti-pattern | Mitigation here |
|---|---|
| Lexical / confessional contamination | Two-Docker air-gap at the data-model level |
| LLM-generated verdict | Pipeline 2 score is a deterministic post-processor; the LLM cannot override |
| Hallucinated cross-references | Citation validator: every LLM citation must verify against TSK / OpenBible / MACULA graph membership |
| Translation conflation | Authority hierarchy; dynamic translations forbidden as Layer 4 exegetical authority |
| Strong's-only Greek/Hebrew claims | Disambiguated Strong's mandatory; Louw-Nida semantic context required before any verdict |
| Confessional eisegesis disguised as exegesis | Confessions on the sibling diagnostic track only; the UI segregates them visually |
| Apparatus blindness | INTF NTVMR transcriptions ingested where ECM exists; a variant-inspect tool surfaces variants per verse |
| Versification chaos | STEPBible TVTMS as the canonical versification service; every cross-version operation routes through it |
| Naive RAG chunking on biblical text | Pericope-aware chunking using OpenText context annotations plus MACULA syntactic trees |
| Quotation / speaker attribution errors | Clear Bible Speaker-Quotations dataset treated as gold |
| TR / Byzantine / Majority Text / NA28 conflation | STEPBible TAGNT per-word edition flags respected per chunk |

## Repo layout

```
brethren-doctrine/
├── docs/                                Canonical documentation
│   ├── ARCHITECTURE.md                  (this file: system spec)
│   ├── SCHEMA_DECISIONS.md              Lexical graph contract
│   ├── CULTURAL_SCHEMA_DECISIONS.md     Cultural graph contract
│   ├── CULTURAL_SCHEMA.md               Per-chunk doctrine-tagging schema
│   ├── HISTORICAL_SCHEMA.md             v1.0 historical-attestation sidecar schema + Pipeline 4 prompt contract
│   ├── EVIDENCE_SCHEMA.md               v3.1 evidence schema + Pipeline 2 prompt contract
│   ├── INGESTION_PATTERNS.md            Per-dataset ingestion notes
│   ├── LICENSE_TAGGING.md               License posture + guard contract
│   ├── MCP_TOOLS.md                     11 MCP tool specifications
│   ├── data_inventory_catalog.json      Lexical source + count contract
│   ├── cultural_data_inventory_catalog.json  Cultural source + count contract
│   ├── historical_data_inventory_catalog.json  Historical source + count contract (H.0 pre-ingest blueprint; fixtures + sample_indices captured in H.1)
│   └── RESEED_MANIFEST_<ts>.json        Standing trustworthiness claim file
├── docker/
│   ├── lexical/docker-compose.yml       Lexical Neo4j + Qdrant stack
│   └── cultural/docker-compose.yml      Cultural Neo4j + Qdrant stack
├── graph/
│   ├── lexical.cypher                   Lexical Neo4j schema
│   └── cultural.cypher                  Cultural Neo4j schema
├── ingest/
│   ├── lexical/                         Pipeline 1 lexical adapters
│   ├── cultural/                        Pipeline 1 cultural adapters
│   ├── historical/                      Pipeline 1 historical adapters (Pipeline 4 inputs)
│   ├── canonical_strongs.py             Strong's normalization utility
│   ├── models.py                        Pydantic chunk and node models
│   └── license_guard.py                 Redistribution enforcement
├── embeddings/                          Voyage embed + Qdrant bootstrap
├── retrieval/                           Router, hybrid retrieve, rerank, envelope
├── mcp/                                 FastMCP server with 11 tools
├── pipeline2/                           Per-question Opus dispatcher + score_calc
├── pipeline4/                           Per-question Opus dispatcher for historical attestation
├── tools/                               Gate + verification tooling
├── tests/                               Real test suite
├── questions.json                       231-question bank (locked)
├── evidence/                            Pipeline 2 output (v3.1)
├── historical/                          Pipeline 4 output (v1.0; sidecar files; most ship with attestation_present=false)
├── responses/                           Gitignored per-respondent answers
├── parsed/                              Brethren corpus (cultural-store input, gitignored)
├── backups/                             Local store snapshots + RESTORE.md (gitignored)
└── pyproject.toml, uv.lock, .env        Python project + secrets
```

## Glossary

- **Air-gap**: physical separation between the lexical and cultural data stores. Pipeline 2 cannot reach the cultural store; Pipeline 4 cannot reach the lexical store (it receives the locked verdict as read-only context only); Pipeline 3 reads all three as separate services with separate license stacks.
- **Apparatus**: footnotes in a critical edition listing manuscript variants and editorial decisions.
- **Attestation**: an extra-biblical witness's relation to a doctrinal proposition. One of `corroborates`, `complicates`, `neutral`, `parallel`, `silent-where-expected`. Never adjudicates the lexical verdict.
- **CBGM**: Coherence-Based Genealogical Method. INTF's algorithm for reconstructing manuscript relationships from variant readings.
- **Contested interpolation**: a known scholarly judgment that part of an extra-biblical witness is a later insertion (Testimonium Flavianum in Josephus, Christian recension layer in Testaments of the Twelve Patriarchs, Chrestianos-vs-Christianos in Tacitus Annals 15.44). Surfaced in the historical schema's `contested_interpolation` block.
- **Cultural overlay**: diagnostic information attached after a lexical verdict is locked. Shows how each tracked tradition reads the same lexical pattern. Never authoritative.
- **Doctrinal proposition**: a single testable belief statement from `questions.json`.
- **ECM**: Editio Critica Maior. INTF's full critical edition of the NT.
- **Historical attestation**: diagnostic information attached after a lexical verdict is locked. Shows extra-biblical witnesses to events, figures, or themes the question touches (Quirinius census, Theudas, John the Baptist, Sanhedrin 10.1 on resurrection). Never authoritative.
- **Historical sidecar / historical store**: the Pipeline 4 output (`historical/<id>.json` files) and the per-chunk store under disjoint labels in the cultural Docker stack. Schema in `docs/HISTORICAL_SCHEMA.md`.
- **Lexical store**: the air-gapped Neo4j plus Qdrant pair holding biblical text, morphology, syntax, cross-references, semantic domains, and apparatus where Layer 1 is populated.
- **Lexical verdict**: the engine's Layer 4 output for a doctrinal proposition. Derived from Scripture alone.
- **Pipeline 1 / 2 / 3 / 4**: ingestion / per-question Opus lexical pre-inference / runtime RAG via MCP / per-question Opus historical pre-inference.
- **Provenance chain**: for an extra-biblical witness, the ordered list of language and transmission steps from earliest extant witness to the edition cited (e.g., 1 Enoch: Aramaic Qumran 4Q201-212 to Greek Codex Panopolitanus to Ethiopic to Charles 1913 English).
- **Triangle test**: re-running a deterministic step on identical inputs produces an identical result; order-permutation of inputs produces an identical result. Pipeline 4 triangle is looser (`+/- 0.05` on confidence) than Pipeline 2's (exact band equality on `lexical_breadth` and `variant_stability`, at most one step drift on `lexical_directness`) because Pipeline 4 is a less structured judgment task.
- **TVTMS**: STEPBible's Translators Versification Mapping Specification. Reconciles Hebrew, English, Greek-Brenton, Latin, KJV verse numbering schemes.
```