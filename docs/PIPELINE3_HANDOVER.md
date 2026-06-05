# Pipeline 3 (self-contained MCP query surface) handover

## Complete and refactored (2026-06-05)

Pipeline 3 is COMPLETE. It was refactored to a self-contained, single-MCP design:

- **No synthesis subagent.** The server does NO synthesis and calls NO LLM. There
  is no `synthesis_fn`, no `make_synthesis_fn`, no dispatcher, and no
  `pipeline3_synthesis` phase prompt. The deleted pieces were `bd_mcp/synthesis.py`,
  the synthesis dispatch seam, and the verdict-fidelity-violation error (the
  verdict is read straight from the evidence file, so it cannot drift and there is
  nothing to re-check).
- **`doctrinal_verdict` returns three structured blocks** side by side: the lexical
  verdict (authoritative, read verbatim from `evidence/<id>.json`), the cultural
  overlay (retrieved live from `cult_col` and formatted by tradition), and the
  historical attestation (read from `historical/<id>.json`). The calling model (the
  MCP client) reasons over the three; the server only assembles structured data.
- **Lifespan + Context.** Store connections live on a FastMCP `lifespan`
  (`bd_mcp/runtime.py`), opened at startup and reached by each tool through the
  injected `Context`. There is no "inject to be functional" duality:
  `python -m bd_mcp.server` is fully functional with all 12 tools live, and
  `build_server()` takes no injector arguments.
- The pure handler is
  `doctrinal_verdict.handle(payload, *, evidence_dir=None, historical_dir=None, cultural_chunks=None)`;
  the tool's `register()` retrieves the cultural chunks via the lifespan and passes
  them in. The end-to-end smoke harness is `scripts/pipeline3_smoke.py`.

The detailed status block and the original hand-off below are preserved for
history; where they describe the now-removed synthesis subagent or the
"injectors built but not wired" state, this note is the current truth.

## Implementation status (2026-06-04)

This status block was added on 2026-06-04 to record progress against the gap
list below. The original handover (everything under "What Pipeline 3 is" onward)
is preserved unchanged for history; this block is the current truth where the two
disagree.

**Done:**

- **Step A. Historical block + `historical_inspect`.** `bd_mcp/tools/doctrinal_verdict.py`
  now reads and validates `historical/<id>.json` (via `load_historical_block`),
  attaches it as `result.historical_attestation` sourced authoritatively from the
  sidecar (never re-derived), and folds its witness `sources_used` into the
  envelope license audit. A missing sidecar yields the empty block; a malformed
  one aborts with `historical_corrupt`. The 12th tool `historical_inspect`
  (`bd_mcp/tools/historical_inspect.py`) mirrors `evidence_inspect` with the same
  question-id regex defense and is registered in `bd_mcp/server.py`. `docs/MCP_TOOLS.md`
  documents 12 tools, the historical block, and the synthesis transform.
- **Step D. Synthesis subagent dispatcher (built).** `bd_mcp/synthesis.py` holds
  `Pipeline3SynthesisDispatcher` and `make_synthesis_fn`, mirroring the Pipeline 2
  and Pipeline 4 injected-`dispatch_fn` pattern with no programmatic Anthropic API.
  It builds the subagent input bundle (locked evidence authoritative, retrieved
  cultural diagnostic, locked historical diagnostic), dispatches once, and returns
  the payload that `doctrinal_verdict.handle(synthesis_fn=...)` transforms. The
  cultural retriever is an optional injected callable; cultural retrieval is
  fail-soft and degrades to an empty overlay.
- **Step B. Cultural injector (built, not yet wired).** `bd_mcp/live/cultural.py`
  performs a dense voyage-4-large search over `cult_col` (60,040 points), filtered
  by tradition and narrowed by the matched question's doctrine slug, returning
  chunks in the exact handler shape. Air-gapped to the cultural store, fail-soft on
  any missing config or unreachable store.

**In progress:**

- **Step C. Lexical injector.** `bd_mcp/live/lexical.py` (lexical Neo4j/Qdrant) is
  being finalized by another agent. The lexical tools remain on injected data until
  it lands.

**Remaining:**

- **Live wiring in `bd_mcp/server.py`.** The injectors above are BUILT but NOT yet
  WIRED. The server still registers the pure handlers with no live injectors bound
  (`register_*` pass `handle(payload)` with `synthesis_fn`, `cultural_chunks`, and
  the lexical retrievers all defaulting to None). The remaining work is to bind the
  cultural injector, the lexical injector (once C lands), and the synthesis
  `dispatch_fn` into the registered tools at server build time.
- **Step E. End-to-end smoke.** NOT done. Both stacks up, server started, a real
  `doctrinal_verdict` query for a question with attestation and one without, all
  three blocks plus a correct `license_audit`, and progress notifications firing,
  has not been run yet.

**Known follow-ups surfaced during implementation:**

- **Cultural autotag pass has not run.** `cult_col` carries an empty `doctrine_tags`
  array on its chunks, so `bd_mcp/live/cultural.py` derives `stance: None` for every
  chunk (it never invents a stance). Cultural stance attribution stays None until
  the autotag pass populates the tags.
- **`cul_col` collection-name typo at `retrieval/hybrid.py:87`. FIXED 2026-06-04.**
  The cultural branch of `HybridRetriever._collection` read `"cul_col"` where the
  live cultural collection is `cult_col`. Corrected to `cult_col`, and the two
  `tests/retrieval/test_hybrid.py` cases that had codified the wrong name updated
  to match. `bd_mcp/live/cultural.py` was already using the correct name.

---

Status as of 2026-06-04. Pipelines 1, 2, and 4 are complete: the lexical store
is ingested and certified, `evidence/<id>.json` holds 231 lexical verdicts, and
`historical/<id>.json` holds 231 historical-attestation sidecars (27 with
witnesses). Pipeline 3 is the last functional gap: the runtime query surface
that synthesizes all of it for a user.

This document is the implementation hand-off. Read it alone and you can finish
Pipeline 3.

## What Pipeline 3 is

An MCP server (`bd_mcp/`) that answers a doctrinal query by returning three
diagnostic blocks side by side, never fused:

1. the **lexical verdict** (authoritative, from `evidence/<id>.json`),
2. the **cultural overlay** (diagnostic, from the cultural store `cult_col`),
3. the **historical attestation** (diagnostic, from `historical/<id>.json` and `hist_col`).

The lexical verdict is final. Cultural and historical material is recorded, never
adjudicates. The air-gap holds at query time too: lexical tools never read the
cultural or historical stores; only the synthesis stage reads all three, as
separate blocks with separate license stacks.

## What already exists (do not rebuild)

- **`bd_mcp/server.py`** FastMCP server, registers all 11 tools, streamable-HTTP
  transport, `MCP_HOST` / `MCP_PORT` env. `build_server()` works; `python -m bd_mcp.server` starts it.
- **11 tool handlers** under `bd_mcp/tools/` (lexical_lookup, concordance_walk,
  cross_ref, variant_inspect, parallel_translation, versification_resolve,
  cultural_overlay, debate_for_verse, doctrinal_verdict, evidence_inspect,
  license_audit). **All handlers are PURE**: they transform injected data
  (e.g. `cultural_overlay.handle(payload, cultural_chunks=...)`,
  `doctrinal_verdict.handle(payload, synthesis_fn=...)`). They do NOT query the
  live stores themselves. This is the seam you wire into.
- **Envelope + license guard** `retrieval/envelope.py` and `bd_mcp/tools/_common.py`:
  the common `{ok, tool, result, warnings, license_audit, trace_id, error}`
  envelope, `response_safe_to_share` derivation via `ingest.license_guard.check_redistribute`,
  `caller_context` (personal / public-share / export) snippet-vs-bulk modes,
  path-traversal defense on question_id. Solid; reuse as is.
- **Retrieval building blocks** `retrieval/`: `HybridRetriever` (dense via voyage
  + sparse, `_query_dense`/`_query_sparse`), `rrf_fuse`, `router.py`, `rerank.py`
  (BGE-reranker-v2-m3). These are written but NOT connected to the tool handlers.
- **Tests** `tests/bd_mcp/` (test_server, test_tools, test_streaming,
  test_acceptance) pass against fixtures (~227 green). They test the pure
  handlers and the envelope, not live stores.
- **Stores up**: lexical (`bolt://localhost:7688`, `lex_col` on `:7100`, certified
  by `tools/verify_manifest.py`); cultural+historical (`bolt://localhost:7689`,
  `cult_col` and `hist_col` on `:7101`; `hist_col` has 65,555 points).

## The gaps to close (in priority order)

### A. Attach the historical block (Pipeline 4 -> Pipeline 3). The headline item.

`doctrinal_verdict` currently returns `lexical_evidence` + `cultural_overlay` +
`variant_sensitivity`. There is NO historical block anywhere in `bd_mcp/` or
`retrieval/` (verified). The whole point of Pipeline 4 is to surface here.

Do:
1. Extend the `doctrinal_verdict` result schema in `docs/MCP_TOOLS.md` with a
   `historical_attestation` block: `{attestation_present, witnesses[], summary,
   license_audit, flags}` sourced from `historical/<evidence_file_id>.json`.
2. In `bd_mcp/tools/doctrinal_verdict.py`: after resolving `qid`, read
   `historical/<qid>.json` (mirror how it reads `evidence/<qid>.json`),
   validate with `pipeline4.historical_schema.HistoricalAttestation`, and pass it
   through `transform_synthesis_to_envelope` into `result.historical_attestation`.
   Most questions are `attestation_present: false` (empty block); 27 carry witnesses.
3. Fold the historical `license_audit.sources_used` into the envelope license
   computation so a DSS (CC-BY-NC-4.0) witness flips `response_safe_to_share`
   correctly. In v1 no DSS was cited, but the guard must still handle it.
4. Consider a 12th tool `historical_inspect` (mirror `evidence_inspect`, same
   question-id regex defense) for deep-linking the raw sidecar. Optional.
5. Update `tests/bd_mcp/` fixtures + add a case using
   `historical/doc-bodily-resurrection-of-christ.json` (5 witnesses).

This step alone makes Pipeline 4's output visible and is low-risk (file read +
transform, same pattern already in place for evidence).

### B. Wire live cultural retrieval into `cultural_overlay` and the synthesis path.

`cultural_overlay.handle` takes `cultural_chunks` injected. Build the injector:
a `HybridRetriever` against `cult_col` (Qdrant `:7101`) + the cultural Neo4j,
filtered by the doctrine slugs of the matched `questions.json` entry and by
`traditions`. Return chunks shaped as the handler expects (tradition, source,
stance, text, license, redistribute, source_work_word_count). Respect the
snippet caps already enforced in the handler.

Prerequisite to verify: confirm `cult_col` is actually populated. The cultural
Pipeline 1 adapters exist (`ingest/cultural/`) but may not have been run in this
environment. If `cult_col` is empty, run the cultural ingest + `embeddings/embed_cultural.py`
first (see README bring-up). The historical side is the model to copy: it was
ingested and embedded the same way.

### C. Wire live lexical retrieval into the lexical tools.

`lexical_lookup`, `concordance_walk`, `cross_ref`, `variant_inspect`,
`parallel_translation`, `versification_resolve` should query the lexical store.
Reuse the query idioms already proven in `pipeline2/context_builder.py` (anchor
lemmas, cross-refs, variant units keyed on `Verse.id`, Louw-Nida neighbors). Key
invariant: lexical tools touch the lexical store ONLY. `variant_inspect` stays a
stub returning `ecm_published: false` except for 3 John (the only ECM in scope).

### D. Wire the synthesis subagent dispatch. SUPERSEDED (see the 2026-06-05 note above).

This step is no longer applicable. The refactor removed the synthesis subagent
entirely: there is no `synthesis_fn` injection point, no dispatcher, and no
`pipeline3_synthesis` phase prompt. `doctrinal_verdict` returns the three
structured blocks directly and the calling model synthesizes. The verdict is read
verbatim from `evidence/<id>.json`, so verdict fidelity holds by construction and
there is no `verdict_fidelity_violation` to raise.

### E. End-to-end smoke.

Bring up both stacks, start the server, and query `doctrinal_verdict` for a
question with attestation (e.g. the resurrection of Christ) and one without.
Confirm all three blocks plus a correct `license_audit`, and that progress
notifications fire for the long-running path.

## Invariants you must not break

- Air-gap at query time: lexical tools never read cultural or historical stores.
  `doctrinal_verdict` reads all three as separate blocks with separate license
  stacks, never a single fused index.
- Historical and cultural are diagnostic; neither changes the lexical verdict.
- License guard: snippet caps under `personal`, paraphrase under `public-share`,
  exclude under `export` for any `redistribute: false` chunk (DSS, BHSA,
  proprietary translations, Vatican.va). The guard is `ingest.license_guard`.
- `bd_mcp/` is named to avoid colliding with the PyPI `mcp` package. Keep it.

## Pointers

- Contracts: `docs/MCP_TOOLS.md` (12 tools), `docs/ARCHITECTURE.md` Layer 7 /
  Pipeline 3 walkthrough. There is no synthesis phase prompt; the server returns
  structured data and the calling model synthesizes.
- Patterns to mirror: `bd_mcp/runtime.py` (the FastMCP lifespan that holds the
  store connections), `pipeline4/context_builder.py` (store retrieval + graceful
  degradation), `embeddings/embed_cultural.py` (cult_col).
- Output schemas: `pipeline4/historical_schema.py` (HistoricalAttestation),
  `pipeline2/evidence_schema.py` (Evidence).

## Bring-up and test

```bash
docker compose --env-file .env -p brethren-lexical  -f docker/lexical/docker-compose.yml  up -d
docker compose --env-file .env -p brethren-cultural -f docker/cultural/docker-compose.yml up -d
python -m bd_mcp.server                         # serves on MCP_HOST:MCP_PORT (default 127.0.0.1:8765)
python -m pytest tests/bd_mcp -q                # the existing skeleton suite
```

Suggested first commit: step A (historical block) on its own; it is self-contained
and makes Pipeline 4 immediately visible through the query surface.
