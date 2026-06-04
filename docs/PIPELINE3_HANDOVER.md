# Pipeline 3 (MCP query + synthesis) handover

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

### D. Wire the synthesis subagent dispatch.

`doctrinal_verdict.handle(synthesis_fn=...)` is the injection point. Implement a
`synthesis_fn` that dispatches an Opus subagent using the canonical prompt at
`docs/phase_prompts/pipeline3_synthesis.md`, exactly mirroring the Pipeline 2 and
Pipeline 4 dispatcher pattern (`pipeline2/dispatcher.py`, an injected
`dispatch_fn`, no programmatic Anthropic API). The subagent reads: the locked
`evidence/<id>.json`, the retrieved cultural chunks (B), and the historical
sidecar (A), and writes `tmp/pipeline3_synthesis/<task_id>/response.json` in the
shape documented in `docs/MCP_TOOLS.md` "Synthesis-subagent output". The handler
transforms that to the envelope.

Hard rule to preserve: **verdict fidelity**. `result.verdict` must equal
`evidence[<id>].verdict.affirms`. The handler already asserts this and returns
`verdict_fidelity_violation` on mismatch. Re-deriving the verdict at query time
is forbidden; Pipeline 3 is retrieval + synthesis only.

### E. End-to-end smoke.

Bring up both stacks, start the server, and query `doctrinal_verdict` for a
question with attestation (e.g. the resurrection of Christ) and one without.
Confirm all three blocks plus a correct `license_audit`, and that progress
notifications fire for the long-running path.

## Invariants you must not break

- Air-gap at query time: lexical tools never read cultural or historical stores.
  Synthesis reads all three as separate blocks with separate license stacks,
  never a single fused index.
- Historical and cultural are diagnostic; neither changes the lexical verdict.
- License guard: snippet caps under `personal`, paraphrase under `public-share`,
  exclude under `export` for any `redistribute: false` chunk (DSS, BHSA,
  proprietary translations, Vatican.va). The guard is `ingest.license_guard`.
- `bd_mcp/` is named to avoid colliding with the PyPI `mcp` package. Keep it.

## Pointers

- Contracts: `docs/MCP_TOOLS.md` (11 tools), `docs/phase_prompts/pipeline3_synthesis.md`
  (synthesis subagent), `docs/ARCHITECTURE.md` Layer 7 / Pipeline 3 walkthrough.
- Patterns to mirror: `pipeline2/dispatcher.py` + `pipeline4/dispatcher.py`
  (injected dispatch_fn), `pipeline4/context_builder.py` (store retrieval +
  graceful degradation), `embeddings/embed_cultural.py` (cult_col).
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
