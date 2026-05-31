# Usage

Cross-session guide. How to drive the engine from a Claude Code session. Assumes the architecture and PoC docs in [docs/](docs/) have been read.

## Boot the orchestrator

To run any operational phase, start a Claude Code session at the repo root and invoke the orchestrator phase prompt.

1. Open Claude Code in `e:/projects-working-dir/brethren-doctrine/`.
2. Have Claude read `docs/phase_prompts/orchestrator.md` (it loads on session start if you reference it).
3. Tell the orchestrator what to do, in plain language. Example:
   - "Run the lexical ingest pass for MACULA Hebrew and MACULA Greek only."
   - "Run Pipeline 2 verdict derivation for question id `doc-trinity`."
   - "Auto-tag the doctrine_tags on the latest cultural scrape batch."

The orchestrator routes the work, dispatches subagents (via the Agent tool, consuming Max plan quota), tracks progress with TodoWrite, and aggregates results.

## Query the engine

The engine is exposed via an MCP server. From any MCP-native client (Claude Code, Claude Desktop, custom client):

```bash
# Start the MCP server (target; implementation pending)
uv run python -m bd_mcp.server
```

Then call tools. The 11 tools are documented in [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md). Example tool calls:

```jsonc
// Look up Strong's G2316
{"tool": "lexical_lookup", "input": {"query": "G2316", "id_type": "strong", "lang": "gk"}}

// Walk every occurrence of theos
{"tool": "concordance_walk", "input": {"strong": "G2316", "window": 5, "limit": 50}}

// Get cross-references for John 3:16
{"tool": "cross_ref", "input": {"ref": "John.3.16", "sources": ["openbible", "tsk"], "min_votes": 10}}

// Resolve a verse between schemes (Hebrew Psa 51:3 == English Psa 51:1)
{"tool": "versification_resolve", "input": {"ref": "Psa.51.1", "from_scheme": "english", "to_scheme": "hebrew"}}

// Cultural overlay for a doctrine
{"tool": "cultural_overlay", "input": {"doctrine": "sacraments", "traditions": ["catholic-magisterial", "reformed"], "k": 8}}

// Long-running doctrinal verdict (streams progress)
{
  "tool": "doctrinal_verdict",
  "input": {
    "proposition": "Scripture is the sole and final authority for the rule of faith",
    "denominations": ["plymouth-brethren", "reformed", "catholic-magisterial"],
    "depth": "deep",
    "progressToken": "abc-123"
  }
}

// Read back a stored evidence file
{"tool": "evidence_inspect", "input": {"question_id": "doc-trinity"}}

// Audit the license stack on a prior response
{"tool": "license_audit", "input": {"subject_type": "response_trace", "subject_id": "<trace_id>"}}
```

## Query the parsed Brethren corpus directly

Until the cultural store is ingested, the `parsed/` JSON files are queryable from any Claude Code session via Read + Grep + jq. This is the Tier 1 access path that pre-dates the cultural store.

```bash
# List all chunks across the corpus
ls parsed/*.json

# Search for a topic across all parsed documents
grep -l "baptism" parsed/*.json

# Read the aggregate index
cat parsed/_index.json | jq '.documents[] | {slug, topics}'

# Read cross-doc perspective comparisons
cat parsed/_perspectives.json | jq '.perspectives[] | {doctrine, viewpoints}'
```

Once the cultural store is up, the same data is queryable via `cultural_overlay` and `debate_for_verse` MCP tools under `tradition=plymouth-brethren`.

## Run validation

Validation is a phase prompt; the orchestrator dispatches a subagent that reads pipeline outputs and verifies them against schemas. The phase prompt is at [docs/phase_prompts/validation.md](docs/phase_prompts/validation.md).

Tell the orchestrator:

- "Validate every file in `evidence/` against the v3.1 schema."
- "Run a triangle test on `evidence/doc-trinity.json` vs `tmp/triangle/doc-trinity_run2.json`."
- "Run license audit on the last 20 evidence files; surface any with `evidence_safe_to_publish: false`."

## Inspect license posture

```bash
# List all sources with non-redistributable license
cat docs/LICENSE_TAGGING.md | grep -A1 "redistribute" | grep "false"

# Check redistribution for a specific evidence file
uv run python -c "
import json
e = json.load(open('evidence/doc-trinity.json'))
print('safe to publish:', e['license_audit']['evidence_safe_to_publish'])
print('reason:', e['license_audit'].get('non_redistributable_reason'))
"
```

## Refresh a dataset

Each Pipeline 1 dataset is pinned at a commit SHA in `pipeline1/lockfile.json` (when implemented). To refresh:

1. Bump the SHA in `pipeline1/lockfile.json` to the desired upstream commit.
2. Tell the orchestrator: "Re-ingest dataset `<dataset_name>` at the new pinned SHA."
3. The orchestrator dispatches a fresh Pipeline 1 lexical ingest subagent.
4. After ingest, run a validation pass to confirm record counts and license tags.

For cultural sources, the same pattern but the "pin" is a content hash of the scraped HTML (so we can detect when an upstream source changes meaningfully).

## Inspect the air-gap

To verify the two-Docker air-gap is in place after stacks are running:

```bash
# Lexical Neo4j should respond
curl -sf http://localhost:7475 && echo "lexical Neo4j: up"

# Cultural Neo4j should respond
curl -sf http://localhost:7476 && echo "cultural Neo4j: up"

# Cross-network DNS lookup must FAIL
docker exec lexical-neo4j getent hosts cultural-neo4j  # expect exit 2 (NSS_NOTFOUND)
docker exec cultural-neo4j getent hosts lexical-neo4j  # expect exit 2

# Cross-network HTTP must FAIL
docker exec lexical-neo4j wget -qO- http://cultural-neo4j:7474  # expect exit 4
docker exec cultural-neo4j wget -qO- http://lexical-neo4j:7474  # expect exit 4
```

The PoC equivalent of this is at `tmp/poc/infra/docker/test_airgap.ps1`. See [docs/POC_FINDINGS.md](docs/POC_FINDINGS.md) H8.

## Common pitfalls

- **Do not install the `anthropic` Python package.** The engine has no programmatic API path. All LLM work is via Claude Code subagents under the Max plan. Adding the package signals a violation of the orchestrator pattern.
- **Do not modify `evidence/<id>.json` files by hand.** They are Pipeline 2 outputs; modifications break the audit trail. To re-derive, dispatch a Pipeline 2 verdict subagent.
- **Do not bypass `license_guard.check_redistribute`** when emitting responses or exports. Every export path goes through the guard. Bypassing it can leak NC-licensed bulk content.
- **Do not cross stores.** Pipeline 2 subagents read only the lexical store; Pipeline 3 synthesis reads both as separate services. Direct cross-store traversal (e.g., a Cypher query that spans both Neo4j databases) is not just bad practice; it is not possible at the network layer because the air-gap blocks it.
- **Do not over-tag cultural chunks.** Pydantic validator caps `doctrine_tags` at 5 per chunk.
- **Do not use em-dashes or en-dashes anywhere** in committed output. The validator at multiple layers rejects them.

## Cost posture

- Voyage embedding for v1 ingest: ~22 M tokens estimated, well within Voyage's 200 M free tier. **Cost: $0.**
- LLM (Opus + Sonnet) via Claude Code subagents under Max plan: **Cost: $0** (covered by existing Max subscription).
- No proprietary lexicon, ECM, or DSS purchases for v1.
- Optional v1 print reference (NA28 Large Print + UBS6 + ECM Catholic Letters Part 1): ~£190-230 if you want physical books for human cross-check. **Not required for the engine to work.**

## Where to read more

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): canonical reference, full 10-layer architecture, three pipelines, two air-gapped stores, all 15 PoC-validated deltas.
- [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md): 11 tools with I/O schemas.
- [docs/EVIDENCE_SCHEMA.md](docs/EVIDENCE_SCHEMA.md): Pipeline 2 evidence v3.1 schema.
- [docs/CULTURAL_SCHEMA.md](docs/CULTURAL_SCHEMA.md): cultural-store per-chunk schema.
- [docs/INGESTION_PATTERNS.md](docs/INGESTION_PATTERNS.md): per-dataset and per-source ingest recipes.
- [docs/LICENSE_TAGGING.md](docs/LICENSE_TAGGING.md): license posture per source, redistribution rules.
- [docs/POC_FINDINGS.md](docs/POC_FINDINGS.md): 15 hypotheses validated 2026-05-12.
- [docs/phase_prompts/](docs/phase_prompts/): explicit prompts the orchestrator dispatches.
