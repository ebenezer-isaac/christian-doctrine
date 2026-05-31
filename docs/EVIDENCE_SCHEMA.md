# Evidence Schema v3.1

Pipeline 2 output schema. One file per doctrinal proposition in `questions.json`. Filename pattern: `evidence/<question_id>.json`.

The Pydantic v2 model lives at `pipeline2/evidence_schema.py` with `extra="forbid"` at every level. Two deterministic post-processors live at `pipeline2/score_calc.py`: `compute_lexical_breadth()` returns the breadth band, and `compute_variant_stability()` returns the stability band. Both are pure functions: no I/O, no clock, no random.

## Schema versions

- v3.1 (current): three named verdict axes (`lexical_breadth`, `lexical_directness`, `variant_stability`). Breadth and stability are deterministic post-processor output; directness is LLM-set.
- v3.0 (superseded): single `lexical_score` float plus `confidence` enum. All files migrated to v3.1; the migration tooling has been retired.
- v2.0 (archived): mixed lexical and cultural fields in one document. Read-only history.
- v1.0 (deleted): pre-greenfield schema.

## Top-level shape

```json
{
  "$schema_version": "3.1",
  "id": "doc-trinity",
  "question_id": "doc-trinity",
  "generated_at": "2026-05-12T18:00:00Z",
  "pipeline_version": "v1",
  "model": "claude-opus-4-7",

  "verdict": { ... },
  "lexical_evidence": { ... },
  "variants": { ... },
  "hermeneutics": { ... },
  "stem_audit": { ... },
  "lay_summary": "...",
  "citations": [ ... ],
  "license_audit": { ... },
  "flags": []
}
```

## Identity fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `$schema_version` | string | yes | Must equal `"3.1"` |
| `id` | string | yes | Echoes `question_id`; kept for legacy tooling |
| `question_id` | string | yes | Must match a `questions[].id` in `questions.json` |
| `generated_at` | ISO 8601 UTC string | yes | When Pipeline 2 emitted this file |
| `pipeline_version` | string | yes | Currently `"v1"` |
| `model` | string | yes | Model slug, e.g. `"claude-opus-4-7"` |

Pydantic validator: `id == question_id`.

## verdict block

```json
{
  "verdict": {
    "affirms": true | false | null | "disputed",
    "lexical_breadth": null,
    "lexical_directness": "direct | inferred | analogical | silent",
    "variant_stability": null,
    "variant_robust": <bool>,
    "pan_canonical": <bool>,
    "rationale": "<2-5 sentence dense rationale>"
  }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `affirms` | enum: `true`, `false`, `null`, `"disputed"` | yes | Four-state verdict |
| `lexical_breadth` | enum: `"canon_wide"`, `"broad"`, `"partial"`, `"thin"`, or null | no | Always null at LLM emission. Post-processor fills it from structural factors |
| `lexical_directness` | enum: `"direct"`, `"inferred"`, `"analogical"`, `"silent"` | yes | LLM-set. How directly the canon's words name the subject under test |
| `variant_stability` | enum: `"stable"`, `"sensitive"`, `"not_in_scope"`, or null | no | Always null at LLM emission. Post-processor derives from `variant_robust` and `variants.ecm_status` |
| `variant_robust` | bool | yes | Verdict survives all plausible variant readings (input to `variant_stability`) |
| `pan_canonical` | bool | yes | Anchor lemmas span multiple canon sections (input to `lexical_breadth`) |
| `rationale` | string | yes | 2-5 sentences citing key lemmas and verse refs |

Schema constraint: `lexical_directness == "silent"` requires `affirms is null`. The Pydantic model rejects any other pairing.

### `affirms` semantics

- `true`: the lexical pattern across the canon supports the proposition.
- `false`: the lexical pattern contradicts it.
- `null`: lexical evidence is genuinely insufficient (sparse anchor lemmas, narrow textual base, or silent canon).
- `"disputed"`: the lexical pattern is materially contested across the canon (e.g., paedobaptism, women in eldership) such that multiple defensible readings exist.

### `lexical_breadth` semantics

How widely the canon's vocabulary engages the proposition. Computed by `compute_lexical_breadth()` from six structural factors (see Post-processor below).

- `canon_wide`: factors saturate; evidence spans multiple canon sections; complicating texts addressed; variant robust.
- `broad`: most factors fire; one canon section dominant, or saturation present without pan-canonical spread.
- `partial`: some factors fire; narrow textual base; gaps unresolved.
- `thin`: sparse lemmas, narrow base, or several factors absent.

The float backing these bands is intermediate-only and never emitted; only the band reaches `evidence/<id>.json`.

### `lexical_directness` semantics

How directly the canon's words name the subject under test. LLM-set. This axis is epistemic, not structural: a proposition can be `canon_wide` in breadth and still `analogical` in directness if the canon engages the subject only by general principle.

- `direct`: an anchor lemma's primary canonical sense IS the subject under test. Example: alcohol is `direct` because `oinos` (G3631) and `yayin` (H3196) name the subject.
- `inferred`: no lemma names the subject, but a canonical category catches it. Example: cannabis intoxication is `inferred` because the `methysko`-class state vocabulary (G3182 etc.) condemns the impaired condition regardless of substance.
- `analogical`: no naming lemma and no category-catch; the verdict reaches the subject only via general principle. Example: tobacco is `analogical` because the verdict rests on 1 Cor 6:19 bodily stewardship and 1 Cor 6:12 mastery rather than any lemma or category that contains the subject.
- `silent`: the canon does not engage the subject at all. Example: subjects unknown to the biblical world that admit no category-catch or analogical hook. Pair with `affirms: null`.

Typical pairings: `direct` and `inferred` pair with `affirms: true|false|disputed`. `analogical` is honest about a weaker lexical footing. `silent` must pair with `affirms: null` (enforced by the Pydantic validator).

### `variant_stability` semantics

Derived enum from `variant_robust` plus `variants.ecm_status`. Computed by `compute_variant_stability()`.

- `stable`: `variant_robust: true` AND `ecm_status` is not `"n/a"`.
- `sensitive`: `variant_robust: false` AND `ecm_status` is not `"n/a"`.
- `not_in_scope`: `ecm_status: "n/a"` (typically OT-only doctrines where the NT manuscript apparatus does not apply). This band takes precedence; `variant_robust` is irrelevant.

## lexical_evidence block

```json
{
  "lexical_evidence": {
    "anchor_lemmas": [
      {
        "strong": "H3068",
        "lemma": "YHWH",
        "transliteration": "yhwh",
        "occurrences_in_canon": 6828,
        "in_anchors": true
      }
    ],
    "concordance_traversed": ["H3068", "H430", "H259", "G2316", "G3056"],
    "scripture": [ ... ],
    "cross_refs_invoked": [ ... ],
    "complicating_texts": [ ... ]
  }
}
```

### anchor_lemmas

The canonical lemmas the verdict rests on. Drives `pan_canonical` and `anchor_lemma_factor` in the breadth formula.

```json
{
  "strong": "<canonical Strong's; H#### or G####>",
  "lemma": "<UTF-8 lemma>",
  "transliteration": "<Latin transliteration>",
  "occurrences_in_canon": <int>,
  "in_anchors": <bool>
}
```

Validator: `strong` matches regex `^[HG]\d{4}[A-Z]?$`.

### concordance_traversed

Flat list of all Strong's codes the subagent examined while deriving the verdict (broader than anchor_lemmas; includes semantic-domain neighbors). Drives `concordance_breadth_factor`.

### scripture

The verses cited as evidence. Each entry:

```json
{
  "ref": "Deut.6.4",
  "key_terms": [{"strong": "H3068", "lemma": "YHWH"}],
  "force": "<dense description of what this verse contributes>",
  "supports": "for | complicates | neutral",
  "genre": "law | narrative | wisdom | prophecy | gospel | epistle | apocalyptic",
  "figures": ["metaphor", "simile", "personification", "chiasm", "merism", "idiom", "hyperbole"],
  "macula_anchor": "OT.Deut.06.004.001-005 (optional)"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `ref` | OSIS BCV string | yes | e.g. `John.1.1` |
| `key_terms` | array | yes | At least 1 entry |
| `force` | string | yes | Dense lexical reasoning |
| `supports` | enum | yes | `for`, `complicates`, `neutral` |
| `genre` | enum | yes | One of 7 |
| `figures` | array | yes | Empty array if no figures |
| `macula_anchor` | string | no | Token-level pointer for reproducibility |

### cross_refs_invoked

Cross-references the subagent followed during concordance walking.

```json
{
  "from": "Deut.6.4",
  "to": "Mark.12.29",
  "source": "openbible | tsk",
  "votes": 130
}
```

### complicating_texts

Verses that could be read against the verdict. Each must be addressed.

```json
{
  "ref": "Mark.13.32",
  "addressed": true,
  "resolution": "communicatio idiomatum: the Son in assumed human nature does not access divine omniscience for that disclosure"
}
```

`complicating_resolved_factor` in the breadth formula is the fraction of `complicating_texts[]` with `addressed: true`.

## variants block

```json
{
  "variants": {
    "verdict_variant_sensitive": <bool>,
    "variant_units_examined": [
      {
        "ref": "1John.5.7",
        "variant_id": "comma_johanneum",
        "verdict_impact": "none | minor | material",
        "note": "Verdict holds without the comma."
      }
    ],
    "ecm_status": "ecm-published | ecm-shadow | n/a",
    "note": "<optional overall note>"
  }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `verdict_variant_sensitive` | bool | yes | True if any contested variant materially affects the verdict |
| `variant_units_examined` | array | yes | Empty array if no variants in play |
| `ecm_status` | enum | yes | `ecm-published` if Layer 1 has ECM data for the cited books, `ecm-shadow` if NA28-apparatus-only, `n/a` for OT-only doctrines |
| `note` | string or null | no | Overall variant-coverage note |

In v1 (CBGM deferred), `ecm_status` is typically `n/a` or `ecm-shadow`; `variant_units_examined` is typically empty.

## hermeneutics block

```json
{
  "hermeneutics": {
    "primary_method": "grammatico-historical | redemptive-historical | quadriga | patristic-typological | accommodation",
    "frameworks_in_play": ["covenant_theology", "dispensationalism", "new_covenant_theology", "progressive_covenantalism", "historic_premillennialism"],
    "analogia_scripturae": <bool>,
    "progressive_revelation": <bool>,
    "competing_lens_verdicts": [],
    "notes": "<>"
  }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `primary_method` | enum (5 values) | yes | Default `grammatico-historical` |
| `frameworks_in_play` | array | yes | Empty if no framework is contested |
| `analogia_scripturae` | bool | yes | Was scripture-interprets-scripture invoked |
| `progressive_revelation` | bool | yes | Does the verdict use progressive revelation reasoning |
| `competing_lens_verdicts` | array | yes | Empty if no competing lens produces a different verdict |
| `notes` | string | yes | Explanation |

If multiple frameworks produce different verdicts (e.g., covenant theology vs dispensationalism on a millennium question), `competing_lens_verdicts` records each:

```json
{
  "framework": "covenant_theology",
  "verdict": "affirms",
  "rationale": "<>"
}
```

## stem_audit block

```json
{
  "stem_audit": {
    "verdict_preloaded": <bool>,
    "neutralized_form": "<string or null>",
    "notes": "<>"
  }
}
```

Flags whether `questions.json[].statement` smuggles a verdict. Examples:
- "Scripture is the sole and final authority" smuggles `sola scriptura` (Reformed framing).
- "Believer's baptism is the New Testament pattern" assumes the verdict.

If `verdict_preloaded: true`, `neutralized_form` provides a tradition-neutral rephrasing. The verdict is still derived on the original stem; the neutralized form is a flag for human review.

## lay_summary

A single string field, 100-500 words, plain language, lexical reasoning only.

Constraints:
- No em-dashes or en-dashes.
- No "the historic Christian position is..." framing (that's cultural overlay).
- No "Reformed teach X; Catholics teach Y" (that's cultural overlay).
- Plain prose that explains what the lexical pattern says.

Validator: `100 <= word_count <= 500`; rejects em-dash and en-dash characters; rejects cultural-overlay phrasing matched by the denylist regex.

## citations array

Sources actually cited in the verdict. Each entry:

```json
{
  "type": "morphology | syntax | cross_ref | variant | interlinear | lexicon",
  "source": "<source slug from docs/LICENSE_TAGGING.md>",
  "license": "<license slug>",
  "redistribute": <bool>,
  "ref": "<verse ref or lemma id>"
}
```

Allowed `source` slugs (from `docs/LICENSE_TAGGING.md`):
- `MACULA-Greek`, `MACULA-Hebrew`, `MACULA-Hebrew-marble-sdbh`, `MACULA-Greek-louw-nida`
- `STEPBible-TAHOT`, `STEPBible-TAGNT`, `STEPBible-TVTMS`, `STEPBible-TBESH`, `STEPBible-TBESG`, `STEPBible-TFLSJ`
- `OSHB-morphology`
- `MorphGNT-morphology`
- `SBLGNT-text`, `Nestle1904-text`
- `ETCBC-BHSA`, `ETCBC-Peshitta`, `ETCBC-syrnt`, `ETCBC-DSS`
- `OpenBible-cross-refs`, `TSK`
- `Theographic-Bible-Metadata`
- `INTF-NTVMR`, `open-cbgm-3-john-sample`
- `BibleHub-interlinear` (cross-validation only, snippet-cite only)

TTESV (STEPBible Tagged ESV) is deliberately excluded from the allowed citation slugs even though it is registered in `docs/LICENSE_TAGGING.md`. Reason: TTESV is a CC-BY-NC tagged translation output, not a lexical primary source. Pipeline 2 cites lexical primaries (apparatus, interlinear, concordance) only. TTESV is ingested into the lexical store (Phase 02) for translation alignment but is not promotable to verdict citations.

Forbidden source slugs: any confession, magisterial document, denominational commentary, or Reformed-aligned commentary site. Pipeline 2 cannot see these (cultural store air-gap), and the schema validator rejects them.

## license_audit block

```json
{
  "license_audit": {
    "sources_used": [
      {"source": "MACULA-Greek", "license": "CC-BY-4.0", "redistribute": true},
      {"source": "ETCBC-BHSA", "license": "CC-BY-NC-4.0", "redistribute": false}
    ],
    "evidence_safe_to_publish": false,
    "non_redistributable_reason": "Cites BHSA syntactic features under CC-BY-NC-4.0."
  }
}
```

Derivation:
```
evidence_safe_to_publish = all(check_redistribute(license=src.license, mode="bulk", ...)["allowed"] for src in sources_used)
```

The Pydantic validator cross-checks each `redistribute` flag against `ingest.license_guard.check_redistribute`; caller-supplied flags that disagree with the registry are rejected. If `evidence_safe_to_publish: false`, the orchestrator records the question id in `evidence/_non_redistributable.txt`.

## flags array

Free-form list of slug-style flags. Standard slugs:
- `ecm-shadow`: variant data is NA28-apparatus-shadow, not ECM-published
- `concordance-thin`: anchor_lemmas count is below a threshold (e.g., < 3)
- `variant-sensitive`: `verdict_variant_sensitive: true`
- `lexically-disputed`: verdict is `"disputed"` rather than true/false/null
- `cross-tradition-divergent`: set by Pipeline 3 synthesis, not Pipeline 2 (verdict diverges from majority cultural-overlay stance; informational only, does not change verdict)
- `complicating-unresolved`: at least one complicating text has `addressed: false`

## Pipeline 2 prompt contract

The lean prompt that Pipeline 2 subagents follow lives at `docs/phase_prompts/pipeline2_verdict.md`. It specifies:
- Hard constraints (no cultural sources, no LLM-written breadth or stability, no personal-decision booleans).
- Input schema (lexical_context_bundle).
- Output schema (this document).
- Verdict guidance per `affirms` and `lexical_directness` values, including the directness quick self-check.
- Stem audit guidance.
- Citation discipline.
- Conditional WebSearch and WebFetch fallback rules with transparency requirements.
- Same-question sub-dispatch rules.
- Acceptance criteria.

## Post-processor: lexical_breadth and variant_stability

Two pure deterministic functions at `pipeline2/score_calc.py`. No I/O, no clock, no random. Order-invariant by construction.

### `compute_lexical_breadth(evidence) -> str`

Internally computes a [0, 1] float from six weighted factors, then buckets the float into a named band. The float is intermediate; only the band is emitted to `evidence/<id>.json`.

```
breadth_score = (
    0.25 * pan_canonical_factor +
    0.20 * anchor_lemma_factor +
    0.15 * complicating_resolved_factor +
    0.15 * cross_ref_density_factor +
    0.15 * variant_robust_factor +
    0.10 * concordance_breadth_factor
)
```

Factor formulas:

| Factor | Weight | Formula |
|---|---|---|
| `pan_canonical_factor` | 0.25 | 1.0 if `pan_canonical: true` else 0.3 |
| `anchor_lemma_factor` | 0.20 | `min(len(anchor_lemmas), 8) / 8` |
| `complicating_resolved_factor` | 0.15 | `addressed_count / len(complicating_texts)`; 1.0 if list is empty |
| `cross_ref_density_factor` | 0.15 | `min(len(cross_refs_invoked), 12) / 12` |
| `variant_robust_factor` | 0.15 | 1.0 if `variant_robust: true` else 0.5 |
| `concordance_breadth_factor` | 0.10 | `min(len(concordance_traversed), 10) / 10` |

Band thresholds:

| Band | Condition |
|---|---|
| `canon_wide` | `breadth_score >= 0.85` AND `pan_canonical: true` |
| `broad` | `0.70 <= breadth_score < 0.85`, OR (`breadth_score >= 0.85` AND `pan_canonical: false`) |
| `partial` | `0.50 <= breadth_score < 0.70` |
| `thin` | `breadth_score < 0.50` |

The `pan_canonical` gate on the top band prevents a high score driven entirely by single-section density from being labelled canon-wide.

### `compute_variant_stability(evidence) -> str`

```
if evidence.variants.ecm_status == "n/a":
    return "not_in_scope"
if evidence.verdict.variant_robust:
    return "stable"
return "sensitive"
```

`not_in_scope` takes precedence over the robust check: when the NT manuscript apparatus does not apply, variant_robust is irrelevant.

## Triangle test

Pipeline 2 outputs are subject to a triangle test:

1. Run Pipeline 2 on `question_id=X` once, save as `evidence/X.json`.
2. Run again on the same inputs, save to `tmp/triangle/X_run2.json`.
3. Verify:
   - Schema validation passes for both.
   - `verdict.affirms` matches.
   - `verdict.lexical_breadth` matches exactly (same band).
   - `verdict.variant_stability` matches exactly (same band).
   - `verdict.lexical_directness` matches, or differs by at most one adjacent step on the axis `direct -> inferred -> analogical -> silent`.
   - Order-permutation of inputs produces the same breadth and stability bands.

Band equality is strict for breadth and stability because both are deterministic post-processor output. Directness drift up to one step is tolerated because the axis is LLM-set; a two-step drift (e.g., `direct` to `analogical`) is flagged. No epsilon-based float comparison is used: the schema does not emit a float.

## Migration history

v2.0 -> v3.0: not implemented. The 111 v2.0 evidence files at the prior session's commit are archived per the user decision to re-derive from scratch under the lean schema. v2.0 mixed lexical and cultural fields; v3.0 split them and added the deterministic `lexical_score`, `variants`, `license_audit`, and `citations` blocks.

v3.0 -> v3.1: complete. All 231 evidence files migrated. The hybrid migration was deterministic for `lexical_breadth` (recomputed by `compute_lexical_breadth()` from the six factors already in the file) and `variant_stability` (derived by `compute_variant_stability()` from `variant_robust` plus `variants.ecm_status`); one LLM call per file produced `lexical_directness` from the existing rationale and anchor_lemmas. The migration tooling has been retired; future drift is gated by `tools/verify_no_v30_dead_refs.py`, `tools/verify_evidence_files_v31.py`, and `tools/verify_schema_consistency.py`.
