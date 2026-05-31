# MCP Tools

The MCP server is the engine's public surface. Built with the official Python SDK (`pip install mcp`) using the `FastMCP` pattern, served over Streamable HTTP per the 2025-06-18 spec revision.

11 tools, each with a typed input schema and a structured output envelope. Long-running tools (notably `doctrinal_verdict`) accept a `progressToken` and emit progress notifications.

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

The license guard's `response_safe_to_share` is derived from `caller_context` plus the set of cited sources. Tools that accept `caller_context`: `parallel_translation`, `cultural_overlay`, `debate_for_verse`, `doctrinal_verdict`, `evidence_inspect`, `license_audit`.

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

**Purpose**: synthesize a verdict on a doctrinal proposition. Cites lexical and cultural separately. Long-running.

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

Stages: `lexical-retrieval` (0.0-0.3), `cultural-retrieval` (0.3-0.6), `synthesis` (0.6-1.0).

**Output result**:
```json
{
  "verdict": "affirms | denies | null | disputed",
  "lexical_breadth": "canon_wide | broad | partial | thin",
  "lexical_directness": "direct | inferred | analogical | silent",
  "variant_stability": "stable | sensitive | not_in_scope",

  "lexical_evidence": {
    "summary": "<>",
    "key_lemmas": [{"strong": "<>", "lemma": "<>"}],
    "key_verses": [{"ref": "<>", "force": "<>"}],
    "source_evidence_files": ["evidence/doc-scripture-final-authority.json"]
  },

  "cultural_overlay": {
    "summary": "<>",
    "by_tradition": [{
      "tradition": "<>",
      "stance": "<>",
      "representative_chunks": [{
        "work": "<>",
        "anchor_id": "<>",
        "snippet": "<fair-use>",
        "license": "<>",
        "redistribute": <bool>
      }]
    }]
  },

  "variant_sensitivity": {
    "verdict_variant_sensitive": <bool>,
    "variant_units_in_play": []
  },

  "evidence_file_id": "doc-scripture-final-authority"
}
```

**Touches**: both stores. Dispatched as a Pipeline 3 synthesis subagent. License-aware.

### Synthesis-subagent output → MCP envelope transform

The synthesis subagent (per `docs/phase_prompts/pipeline3_synthesis.md`) writes a structured JSON output to `tmp/pipeline3_synthesis/<task_id>/response.json` with shape:

```json
{
  "task_id": "<>",
  "phase": "pipeline3_synthesis",
  "mcp_tool_name": "doctrinal_verdict",
  "user_query": "<>",
  "lexical_verdict": {
    "summary": "<>",
    "affirms": <bool|null|"disputed">,
    "lexical_breadth": "canon_wide | broad | partial | thin",
    "lexical_directness": "direct | inferred | analogical | silent",
    "variant_stability": "stable | sensitive | not_in_scope",
    "key_lemmas": [...],
    "key_verses": [...],
    "variant_robust": <bool>,
    "pan_canonical": <bool>,
    "source_evidence_files": [...]
  },
  "cultural_overlay": { ... },
  "variant_sensitivity": { ... },
  "license_audit": { ... },
  "confidence": <float>,
  "warnings": [...]
}
```

The doctrinal_verdict tool handler at `bd_mcp/tools/doctrinal_verdict.py` calls a pure function `transform_synthesis_to_envelope(synthesis_output: dict) -> EnvelopeResult` that produces the MCP-public output shape above. The transform:

1. `lexical_verdict.affirms` → `result.verdict` (rename).
2. `lexical_verdict.lexical_breadth` → `result.lexical_breadth` (flatten one level).
3. `lexical_verdict.lexical_directness` → `result.lexical_directness` (flatten one level).
4. `lexical_verdict.variant_stability` → `result.variant_stability` (flatten one level).
5. `lexical_verdict` block (minus the above) → `result.lexical_evidence`.
6. `cultural_overlay` → `result.cultural_overlay` (pass through).
7. `variant_sensitivity` → `result.variant_sensitivity` (pass through).
8. `lexical_verdict.source_evidence_files[0]` (the matched question id stripped of path/.json) → `result.evidence_file_id`.
9. `synthesis_output.license_audit.sources_used` → `envelope.license_audit.sources_used`.
10. The handler then computes `envelope.license_audit.response_safe_to_share` via `license_guard.check_redistribute(...)` for every cited source, respecting `caller_context`.

**Verdict-fidelity rule**: `result.verdict` must equal the `verdict.affirms` of the underlying `evidence/<evidence_file_id>.json`. The handler reads the stored evidence file and asserts the equality before returning. Re-derivation of the verdict at query time is FORBIDDEN; the handler is a retrieval-and-synthesis layer.

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

## Server configuration

```python
# bd_mcp/server.py (sketch)
from mcp.server.fastmcp import FastMCP  # PyPI SDK; the local package is named bd_mcp/ to avoid collision.

server = FastMCP(name="brethren-doctrine")

# Register tools (local imports from bd_mcp.tools, NOT the PyPI mcp package)
from bd_mcp.tools import (
    lexical_lookup, concordance_walk, cross_ref, variant_inspect,
    parallel_translation, versification_resolve, cultural_overlay,
    debate_for_verse, doctrinal_verdict, evidence_inspect, license_audit
)
for tool in [lexical_lookup, concordance_walk, ..., license_audit]:
    server.add_tool(tool)

# Transport: Streamable HTTP per 2025-06-18 spec
server.run(transport="streamable-http", port=8765)
```

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
| `license_audit` | ✓ | ✓ |
