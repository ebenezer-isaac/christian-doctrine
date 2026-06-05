# MCP Tools

The MCP server is the engine's public surface. Built with the official Python SDK (`pip install mcp`) using the `FastMCP` pattern, served over Streamable HTTP per the 2025-06-18 spec revision.

12 tools, each with a typed input schema and a structured output envelope. Long-running tools (notably `doctrinal_verdict`) accept a `progressToken` and emit progress notifications.

## Common envelope

Every tool response uses this envelope shape:

```json
{
  "ok": true | false,
  "tool": "<tool_name>",
  "result": <tool-specific structured output>,
  "warnings": [<strings>],
  "license_audit": {
    "sources_used": [{"source": "<>", "license": "<>", "redistribute": <bool>}],
    "response_safe_to_share": <bool>,
    "snippet_caps_respected": <bool>,
    "non_redistributable_reason": "<string or null>"
  },
  "trace_id": "<>",
  "error": null
}
```

If `ok: false`, `result` is `null` and `error` is `{"code": "<>", "message": "<>"}`.

## Common `caller_context` input field

Every license-sensitive tool accepts an optional `caller_context` field. Default `"personal"`. Values:

- `"personal"`: caller is using the engine privately; snippet caps still apply but full fair-use latitude is granted.
- `"public-share"`: caller intends to publish; any chunk with `redistribute: false` is paraphrased rather than quoted.
- `"export"`: caller is bulk-exporting; any chunk with `redistribute: false` is excluded entirely.

The license guard's `response_safe_to_share` is derived from `caller_context` plus the set of cited sources. Tools that accept `caller_context`: `parallel_translation`, `cultural_overlay`, `debate_for_verse`, `doctrinal_verdict`, `evidence_inspect`, `historical_inspect`, `license_audit`.

## Tool 1: lexical_lookup

**Purpose**: resolve a Hebrew or Greek lemma, Strong's code, or surface form to its lexical entry.

**Input**:
```json
{
  "query": "string",
  "lang": "hb | gk",
  "id_type": "strong | lemma | surface | gloss",
  "limit": 20
}
```

**Output result**:
```json
{
  "matches": [
    {
      "strong": "G2316",
      "lemma": "θεός",
      "transliteration": "theos",
      "morph_pattern": "N",
      "gloss": "God, deity",
      "louw_nida": "12.1",
      "occurrences_in_canon": 1317,
      "attested_in": ["John.1.1", "John.1.18", "..."],
      "license_components": [{"source": "STEPBible-TBESG", "license": "CC-BY-4.0"}]
    }
  ],
  "total_matches": <int>
}
```

**Touches**: lexical store only.

## Tool 2: concordance_walk

**Purpose**: return all occurrences of a lemma / Strong's code with surrounding context.

**Input**:
```json
{
  "strong": "string (optional)",
  "lemma": "string (optional)",
  "window": 5,
  "filter_book": [<book slugs, optional>],
  "limit": 200
}
```

**Output result**:
```json
{
  "occurrences": [
    {
      "ref": "John.1.1",
      "surface": "θεόν",
      "context_left": "καὶ ὁ λόγος ἦν πρὸς τὸν",
      "context_right": ", καὶ θεὸς ἦν ὁ λόγος.",
      "morph": "N-ASM",
      "license_components": [{"source": "MACULA-Greek", "license": "CC-BY-4.0"}]
    }
  ],
  "total": <int>,
  "truncated": <bool>
}
```

**Touches**: lexical store only.

## Tool 3: cross_ref

**Purpose**: get cross-references for a verse, fused from OpenBible + TSK + Theographic.

**Input**:
```json
{
  "ref": "John.3.16",
  "sources": ["openbible", "tsk", "theographic"],
  "min_votes": 5,
  "limit": 50
}
```

**Output result**:
```json
{
  "edges": [
    {
      "from": "John.3.16",
      "to": "John.5.24",
      "votes": 132,
      "source": "openbible",
      "shared_lemmas": ["G2222", "G166"]
    }
  ],
  "graph_density": <float>
}
```

**Touches**: lexical store only.

## Tool 4: variant_inspect

**Purpose**: pull CBGM variant unit and witness coherence for a verse where ECM is published.

**Input**:
```json
{
  "ref": "1John.5.7",
  "include_witnesses": true,
  "phase": "ph2 (optional, INTF-specific)"
}
```

**Output result**:
```json
{
  "variant_units": [
    {
      "vu_id": "1Jn5.7/comma_johanneum",
      "readings": [
        {
          "label": "a",
          "text": "<critical text reading>",
          "witnesses_count": 458,
          "ga_sample": ["03", "01", "02"]
        }
      ],
      "split_line": true,
      "cbgm_coherence_score": 0.87
    }
  ],
  "ecm_published": true,
  "book_coverage": "Catholic Letters phase 2"
}
```

If ECM is not published for the cited book: returns `ecm_published: false` and an empty `variant_units` array. **Deferred from v1; tool stub returns ecm_published=false for all books until Layer 1 is activated.**

**Touches**: lexical store only.

## Tool 5: parallel_translation

**Purpose**: show same verse across N open-licensed translations plus the underlying Hebrew or Greek.

**Input**:
```json
{
  "ref": "John.1.1",
  "translations": ["ESV", "NASB", "NKJV", "NIV", "NLT"],
  "include_original": true,
  "caller_context": "personal | public-share | export"
}
```

**Output result**:
```json
{
  "ref": "John.1.1",
  "ref_resolved": {
    "osis": "John.1.1",
    "tvtms_alternates": []
  },
  "original": {
    "lang": "gk",
    "text": "Ἐν ἀρχῇ ἦν ὁ λόγος, καὶ ὁ λόγος ἦν πρὸς τὸν θεόν, καὶ θεὸς ἦν ὁ λόγος.",
    "morphology_anchor": "MACULA-Greek-SBLGNT"
  },
  "rows": [
    {"translation": "ESV", "text": "...", "license": "©Crossway", "redistribute": false},
    {"translation": "NLT", "text": "...", "license": "©Tyndale-House", "redistribute": false}
  ]
}
```

**Touches**: lexical store only. License-guard enforces: non-PD translation text is provided as snippet only (under fair-use caps); bulk export requires per-translation license.

## Tool 6: versification_resolve

**Purpose**: map a verse reference between OSIS / KJV / Hebrew / LXX / Vulgate schemes via STEPBible TVTMS.

**Input**:
```json
{
  "ref": "Psa.51.1",
  "from_scheme": "english | hebrew | lxx | vulgate | osis",
  "to_scheme": "english | hebrew | lxx | vulgate | osis"
}
```

**Output result**:
```json
{
  "from": {"scheme": "english", "ref": "Psa.51.1"},
  "to": {"scheme": "hebrew", "ref": "Psa.51.3"},
  "all_mappings": [
    {"scheme": "english", "ref": "Psa.51.1"},
    {"scheme": "hebrew", "ref": "Psa.51.3"},
    {"scheme": "vulgate", "ref": "Psa.50.3"}
  ],
  "rule_type": "OneToOne",
  "block_scope": "$Psa.51:1-51:19"
}
```

**Touches**: lexical store only.

## Tool 7: cultural_overlay

**Purpose**: RAG into cultural store for a verse or doctrine.

**Input**:
```json
{
  "ref": "John.6.53 (optional)",
  "doctrine": "sacraments (optional)",
  "traditions": ["catholic-magisterial", "reformed", "lutheran"],
  "k": 8,
  "caller_context": "personal | public-share | export"
}
```

**Output result**:
```json
{
  "passages": [
    {
      "chunk_id": "vatican.va.ccc.1366",
      "tradition": "catholic-magisterial",
      "doctrine_tags": [{"doctrine_coarse": "sacraments", "stance": "affirms", "confidence": 0.96}],
      "work": "Catechism of the Catholic Church",
      "anchor_id": "CCC.1366",
      "snippet": "<fair-use snippet, max 100 words>",
      "license": "©Libreria-Editrice-Vaticana",
      "redistribute": false,
      "tradition_paraphrase_if_not_redistributable": "<paraphrase>"
    }
  ],
  "by_tradition_summary": {
    "catholic-magisterial": {"affirms": 4, "denies": 0, "qualifies": 1},
    "reformed": {"affirms": 0, "denies": 5, "qualifies": 0}
  }
}
```

**Touches**: cultural store only. License-guard enforces snippet caps. Non-redistributable sources receive a paraphrase rather than verbatim snippet.

## Tool 8: debate_for_verse

**Purpose**: return contested doctrinal stances on a single verse, one entry per tradition. Used by the variant-debate UI in v2.

**Input**:
```json
{
  "ref": "John.1.18",
  "doctrines": ["christology (optional)"],
  "caller_context": "personal | public-share | export"
}
```

**Output result**:
```json
{
  "ref": "John.1.18",
  "variant_in_play": {
    "vu_id": "John1.18/monogenes-theos-vs-huios",
    "readings": ["monogenes theos", "monogenes huios"],
    "lexical_verdict_variant_sensitive": true
  },
  "by_tradition": {
    "patristic": [{"work": "Athanasius Contra Arianos", "stance": "affirms monogenes theos", "snippet": "<>"}],
    "reformed": [{"work": "Calvin Commentary on John", "stance": "affirms monogenes theos"}],
    "modern-translation-divergence": [{"translation": "ESV", "reads": "the only God"}, {"translation": "KJV", "reads": "the only begotten Son"}]
  }
}
```

**Touches**: both stores (lexical for variant data, cultural for tradition stances). License-aware.

## Tool 9: doctrinal_verdict

**Purpose**: return the three diagnostic blocks for a doctrinal proposition: the lexical verdict (authoritative), the cultural overlay, and the historical attestation. The server does NO synthesis and calls NO LLM. It assembles structured data and the calling model (the MCP client) reasons over the three blocks. The lexical verdict is read verbatim from `evidence/<id>.json`, so it cannot drift.

**Input**:
```json
{
  "proposition": "Scripture is the sole and final authority for the rule of faith",
  "denominations": ["plymouth-brethren", "reformed", "catholic-magisterial (optional)"],
  "depth": "fast | deep",
  "progressToken": "<client-supplied>",
  "caller_context": "personal | public-share | export"
}
```

**Progress notifications** (emitted periodically):
```json
{
  "method": "notifications/progress",
  "params": {
    "progressToken": "<echoed>",
    "progress": 0.4,
    "total": 1.0,
    "message": "Stage: cultural overlay retrieval"
  }
}
```

Stages: `lexical-read` (0.0-0.4), `cultural-retrieval` (0.4-0.8), `historical-read` (0.8-1.0). These are read-and-assemble stages; no synthesis stage exists because the server does not synthesize.

**Output result**:
```json
{
  "verdict": "affirms | denies | null | disputed",
  "lexical_breadth": "canon_wide | broad | partial | thin",
  "lexical_directness": "direct | inferred | analogical | silent",
  "variant_stability": "stable | sensitive | not_in_scope",

  "lexical_evidence": {
    "rationale": "<>",
    "lay_summary": "<>",
    "pan_canonical": <bool>,
    "variant_robust": <bool>,
    "source_evidence_files": ["evidence/doc-scripture-final-authority.json"]
  },

  "cultural_overlay": {
    "passages": [{
      "tradition": "<>",
      "source": "<>",
      "stance": "<>",
      "snippet": "<fair-use snippet or null>",
      "tradition_paraphrase_if_not_redistributable": "<paraphrase or null>"
    }],
    "by_tradition": {
      "<tradition>": [{"tradition": "<>", "source": "<>", "stance": "<>", "snippet": "<>"}]
    }
  },

  "variant_sensitivity": {
    "verdict_variant_sensitive": <bool>,
    "variant_units_in_play": []
  },

  "historical_attestation": {
    "attestation_present": <bool>,
    "witnesses": [ <Witness>, ... ],
    "summary": "<>",
    "license_audit": {
      "sources_used": [{"source_slug": "<>", "license": "<>", "redistribute": <bool>}],
      "evidence_safe_to_publish": <bool>,
      "non_redistributable_reason": "<>|null"
    },
    "flags": ["<>"]
  },

  "evidence_file_id": "doc-scripture-final-authority"
}
```

The three blocks are returned directly, side by side, never fused. The server does not synthesize them and calls no LLM. The calling model (the MCP client) reads the structured data and does the synthesis itself.

- `verdict` plus the three flattened axes (`lexical_breadth`, `lexical_directness`, `variant_stability`) and the `lexical_evidence` block are read verbatim from `evidence/<evidence_file_id>.json` (Pipeline 2). The `verdict` is the stored `verdict.affirms`, copied straight from the file. Because it is read, not re-derived, it cannot drift; there is no query-time re-derivation and nothing to re-check.
- `cultural_overlay` is retrieved live from the cultural store (`cult_col`) at request time, filtered by tradition and by the doctrine slug of the matched question, then formatted by `build_cultural_overlay` into license-redacted `passages` and a `by_tradition` grouping. It is diagnostic and never settles the verdict. If the cultural store is unavailable the overlay degrades to empty.
- `variant_sensitivity` is the `variants` block from the evidence file.
- `historical_attestation` is the Pipeline 4 sidecar (`historical/<evidence_file_id>.json`), read and validated against `HistoricalAttestation` before it is attached. Most of the 231 questions carry no attestation (`attestation_present: false`, empty `witnesses`); 27 carry witnesses. The witness shape is the `Witness` model in `pipeline4/historical_schema.py`. A sidecar that fails validation aborts the response with `error.code: "historical_corrupt"`.
- `evidence_file_id` is the resolved question id.

**License audit folds all three stacks.** The envelope `license_audit.sources_used` is the union of the lexical sources (from the evidence file), the cultural sources (from the retrieved chunks), and the historical witness sources (from the sidecar, `source_slug` mapped to `source`). `response_safe_to_share` is then computed via `license_guard.check_redistribute(...)` over every cited source, respecting `caller_context`. A non-redistributable source in any block (for example a DSS witness under CC-BY-NC-4.0) flips `response_safe_to_share` under `public-share` and `export`.

**Implementation**: the pure handler is `doctrinal_verdict.handle(payload, *, evidence_dir=None, historical_dir=None, cultural_chunks=None)` in `bd_mcp/tools/doctrinal_verdict.py`. The tool's `register()` retrieves the cultural chunks live (via the cultural clients held on the FastMCP lifespan, reached through the injected `Context`) and passes them in. There is no synthesis subagent, no `synthesis_fn`, and no dispatch.

**Touches**: the cultural store (live retrieval) plus the `evidence/` and `historical/` filesystem. License-aware as described above.

## Tool 10: evidence_inspect

**Purpose**: read back a stored evidence/<id>.json file from Pipeline 2.

**Input**:
```json
{
  "question_id": "doc-trinity",
  "include_full_schema": true,
  "caller_context": "personal | public-share | export"
}
```

**Path-traversal defense**: `question_id` must match regex `^[a-z][a-z0-9-]{2,80}$` (kebab-case slug). Any other input is rejected with `error.code: "invalid_question_id"`. The handler resolves to `evidence/<question_id>.json` only after this validation; `..` and `/` are unreachable.

**Output result**:
```json
{
  "question_id": "doc-trinity",
  "evidence": <full evidence v3.1 JSON contents>,
  "file_path": "evidence/doc-trinity.json",
  "schema_version": "3.1"
}
```

**Touches**: filesystem (reads `evidence/` directly). No store touched. Useful for deep-linking from `doctrinal_verdict` results.

## Tool 11: license_audit

**Purpose**: return the merged license stack used for a given response or evidence file.

**Input**:
```json
{
  "subject_type": "evidence_file | response_trace",
  "subject_id": "doc-trinity | <trace_id>",
  "caller_context": "personal | public-share | export"
}
```

**Path-traversal defense**: for `subject_type: "evidence_file"`, `subject_id` must match the question-id regex `^[a-z][a-z0-9-]{2,80}$`. For `subject_type: "response_trace"`, `subject_id` must match a UUID regex.

**Output result**:
```json
{
  "subject_type": "evidence_file",
  "subject_id": "doc-trinity",
  "sources_used": [
    {"source": "MACULA-Greek", "license": "CC-BY-4.0", "redistribute": true},
    {"source": "ETCBC-BHSA", "license": "CC-BY-NC-4.0", "redistribute": false}
  ],
  "evidence_safe_to_publish": false,
  "non_redistributable_reason": "Cites BHSA syntactic features under CC-BY-NC-4.0.",
  "snippet_caps_respected": true
}
```

**Touches**: filesystem. Useful for callers deciding whether to re-share an output.

## Tool 12: historical_inspect

**Purpose**: read back a stored Pipeline 4 historical-attestation sidecar `historical/<id>.json`. The deep-link counterpart to `evidence_inspect`, for the historical layer.

**Input**:
```json
{
  "question_id": "doc-bodily-resurrection-of-christ",
  "include_full_schema": true,
  "caller_context": "personal | public-share | export"
}
```

**Path-traversal defense**: identical to `evidence_inspect`. `question_id` must match `^[a-z][a-z0-9-]{2,80}$`; the handler resolves to `historical/<question_id>.json` only after validation. The sidecar is validated against `HistoricalAttestation` before return; a malformed file returns `error.code: "historical_corrupt"`, a missing one returns `error.code: "historical_missing"`.

**Output result**: the full validated `HistoricalAttestation` JSON when `include_full_schema: true`, otherwise a digest `{question_id, attestation_present, summary, flags}`.

**Touches**: filesystem (reads `historical/` directly). No store touched. Diagnostic only; it never adjudicates the lexical verdict. Useful for deep-linking from `doctrinal_verdict` results.

## Server configuration

```python
# bd_mcp/server.py (sketch)
from mcp.server.fastmcp import FastMCP  # PyPI SDK; the local package is named bd_mcp/ to avoid collision.

from bd_mcp.runtime import lifespan  # opens the store connections on startup, closes them on shutdown

# The lifespan holds the live store connections; tools reach them through the
# injected Context. The server is fully functional with no external wiring.
server = FastMCP(name="brethren-doctrine", lifespan=lifespan)

# Register all 12 tools (local imports from bd_mcp.tools, NOT the PyPI mcp package).
# Each module exposes register(server); build_server() calls them in order.
from bd_mcp.tools.lexical_lookup import register as register_lexical_lookup
# ... the other 11 register imports ...
register_lexical_lookup(server)
# ... register the remaining 11 tools ...

# Transport: Streamable HTTP per 2025-06-18 spec
server.run(transport="streamable-http")
```

`python -m bd_mcp.server` serves every tool live against the real stores. `build_server()` takes no injector arguments; there is no "inject to be functional" duality.

## Long-running tool conventions

For tools that may take more than 2 seconds (`doctrinal_verdict` is the primary case, occasionally `cultural_overlay` and `debate_for_verse` with broad inputs):

1. Accept a `progressToken` field in the input.
2. Emit `notifications/progress` notifications keyed by that token with `{progress, total, message}`.
3. Hold the connection open via Streamable HTTP SSE.
4. Emit the final structured response in a single chunk; do not stream partial JSON.

Progress message conventions: state the current stage in `message`, advance `progress` monotonically.

## What the MCP tools do NOT expose

- Direct Cypher / Neo4j query interface (security boundary).
- Direct Qdrant query interface.
- Write operations to either store.
- Anthropic API passthrough.
- File-write operations beyond evidence/ inspection.

All write operations to the stores happen via Pipeline 1 ingest adapters orchestrated by the master orchestrator, never through the MCP server.

## Tool deferral table (v1 vs v2)

| Tool | v1 | v2 |
|---|---|---|
| `lexical_lookup` | ✓ | ✓ |
| `concordance_walk` | ✓ | ✓ |
| `cross_ref` | ✓ | ✓ |
| `variant_inspect` | stub returns `ecm_published: false` (CBGM deferred per user decision) | full implementation after 3 John pilot proves value |
| `parallel_translation` | ✓ (open-licensed translations only) | adds proprietary translations under per-license guards |
| `versification_resolve` | ✓ | ✓ |
| `cultural_overlay` | ✓ | ✓ |
| `debate_for_verse` | ✓ (without variant_in_play details) | ✓ with variant data once Layer 1 lands |
| `doctrinal_verdict` | ✓ | ✓ |
| `evidence_inspect` | ✓ | ✓ |
| `historical_inspect` | ✓ | ✓ |
| `license_audit` | ✓ | ✓ |
