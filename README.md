# christian-doctrine

A manuscript-anchored personal Bible-doctrine engine. It produces a doctrinal verdict from the original-language manuscript alone, then attaches a separate diagnostic overlay showing how each tracked Christian tradition reads the same lexical pattern. The system runs two physically separate, air-gapped data stores: a lexical store (Scripture, lexicon, morphology, syntax, cross-references, apparatus where published) and a cultural store (church teaching: confessions, patristic, magisterial, denominational). An in-house orchestrator dispatches the work and voyage-4-large supplies embeddings at native 2048 dimensions for both stores. Pipeline 2 derives the Scripture-only doctrinal baseline and is air-gapped from the cultural store at the data-model level; the cultural side is a separate diagnostic overlay that records, never adjudicates. It is single-user, personal-use tooling.

The aim is *calibrated discernment*, not church-scoring. A church that checks green on all markers can still fall flat in practical execution. There is a difference between believing the doctrine and practicing the doctrine.

## How I got here

I was born into a [Christian Brethren](https://en.wikipedia.org/wiki/Plymouth_Brethren) family, but my personality has always been to be a skeptic. For a long time I wasn't sure if God even existed. I used to pray something like: *I'm willing to forgo the blessing of believing without seeing because reaching heaven with one less blessing seems better than going altogether to hell for unbelief.* It was Pascal's Wager dressed up as humility, but I meant it. This is in reference to the line in [John 20:29](https://www.biblegateway.com/passage/?search=John+20%3A29) "Blessed are those who have not seen and yet have believed".

The conviction came during my early 20s during daily meditations. I used to sit under a tree and think about how the world was actually working. And I realized something obvious that I hadn't actually faced: if even one year all the trees never came back to life, the whole universe collapses. No oxygen, no food chain, no anything. Every life on the planet dies. For a system that delicate to operate flawlessly for thousands of years, *someone* has to be pulling the strings from the background. That's not naive. That's the [teleological argument](https://en.wikipedia.org/wiki/Teleological_argument) restated in the only terms I had at the time. From there I was convinced there was a God.

Then the next question landed. *If* God exists, *who* is God? Why are there so many gods? Was I leaning toward Jesus only because I'd been raised Christian? Would I have leaned toward Krishna or Allah if I'd been born somewhere else? The honest version of the question demanded I do real comparative work. So I started talking to friends, religious leaders from other traditions, reading their texts.

What I found was that only Christianity had bulletproof theology, philosophy, science, and history. It withstood every question I threw at it, to the point that it started to feel too perfect to be true. Almost like a conspiracy that was infallible, defensible from every angle. But the more I looked at the world itself, the more I saw the same signature: the same character, the same internal logic. The God of the Bible and the operations of the world ran on the same source code. Which brought me back, hard, to [John 1:1](https://www.biblegateway.com/passage/?search=John+1%3A1): *In the beginning was the Word.* Watching [Lee Strobel's *Case for Christ*](https://en.wikipedia.org/wiki/The_Case_for_Christ) put the last nail in my old self and forced me to publicly declare that there is no God other than Jesus.

That should have been the end of it. But I'm now in the next phase, and it's harder than the first two.

Back home in India, the answer to *which church?* was obvious: Brethren. It was what I was born into, what I knew, and the doctrine matched what I was taught. But the same skeptic question that pushed me through stages 1 and 2 keeps coming back: am I leaning toward Brethren only because I was raised in a Brethren family? Is my conviction inheritance, or is it verified? That question got significantly louder when I landed in London. There are very few distinct Brethren denominational churches here and the others have substantially changed over time. So I'm forced to go in search of the truth again.

I came to Christianity *because of* its infallible truth and singular logic, grounded in Scripture. So why are there so many denominations within Christianity itself? If truth is singular, shouldn't there be a singular church?

The answer I've landed on, at least as a working frame: our access to truth was muddled when [Adam ate of the forbidden fruit](https://www.biblegateway.com/passage/?search=Genesis+3). Our ability to distinguish right from wrong has been compromised ever since. And it's further muddied by the devil, who [disguises himself as an angel of light](https://www.biblegateway.com/passage/?search=2+Corinthians+11%3A14) to spread misinformation. Whatever effort we put into defining truth is still just a best effort, because we lost the ability to share directly in God's truth. What we have left is one gift: the Bible, the ultimate source of truth God gave us. Interpretation is human best-effort aided by the Holy Spirit. The practice of doctrines is debatable. There's no escaping that, and pretending otherwise produces either fundamentalism or cynicism.

**This endeavour aims to identify, for myself, the truths I'm willing to lay my life down for, and the truths I'm willing to live and let live.**

That sentence is not rhetorical. It maps directly onto the boolean pattern of every respondent answer built into this engine. `would_die_for=true` is "die for"; `would_be_member=true` is "live and let live"; everything in between is graduated. The standings emerge from the booleans rather than being pre-assigned to the question. The whole point of the engine is to calibrate that line *against primary sources* rather than inherit it from any single teacher, including the Brethren tradition I was formed in.

## The three-stage progression

This project sits at the third step of a deliberate sequence:

1. *Does God exist?* Settled, under that tree.
2. *Is Jesus God?* Settled, after the comparative-religions work and Strobel.
3. *If Jesus is truth, why are there so many denominations, and which one is right?* **Open.** This engine is the diagnostic tool I'm building to investigate this.

Each stage closes one trust gap so the next can be examined cleanly. I'm not delegating these conclusions to a single church or teacher. I'm verifying primary sources myself.

## Canonical documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) system spec, governance model, the standing trustworthiness gate, and the intentional scope boundaries.
- [docs/SCHEMA_DECISIONS.md](docs/SCHEMA_DECISIONS.md) and [docs/CULTURAL_SCHEMA_DECISIONS.md](docs/CULTURAL_SCHEMA_DECISIONS.md) the graph contracts for the lexical and cultural stores.
- [docs/EVIDENCE_SCHEMA.md](docs/EVIDENCE_SCHEMA.md) and [docs/CULTURAL_SCHEMA.md](docs/CULTURAL_SCHEMA.md) the output schemas (per-question lexical audit trail, per-chunk doctrine tagging).
- [docs/data_inventory_catalog.json](docs/data_inventory_catalog.json) and [docs/cultural_data_inventory_catalog.json](docs/cultural_data_inventory_catalog.json) the authoritative source-count contract.

## Bring-up

```bash
# 1. Start the two air-gapped Docker stacks (separate projects, separate networks)
docker compose -p brethren-lexical  -f docker/lexical/docker-compose.yml  up -d
docker compose -p brethren-cultural -f docker/cultural/docker-compose.yml up -d

# 2. Apply the graph schema to each Neo4j (lexical bolt :7688, cultural bolt :7689)
cypher-shell -a bolt://localhost:7688 -f graph/lexical.cypher
cypher-shell -a bolt://localhost:7689 -f graph/cultural.cypher

# 3. Bootstrap the two Qdrant collections
python embeddings/bootstrap.py --store lexical
python embeddings/bootstrap.py --store cultural

# 4. Ingest the lexical sources into the lexical store
python ingest/lexical/run.py --dataset all

# 5. Reseed the cultural store (deterministic from captured jsonl by default)
python tools/cultural_reseed.py --mode from-jsonl --source all

# 6. Embed both stores with voyage-4-large
python embeddings/embed_lexical.py
python embeddings/embed_cultural.py --sources all
```

`ingest/lexical/run.py --list` prints every wired lexical dataset.
`tools/cultural_reseed.py --mode scrape` re-acquires the cultural sources live (resumable, bounded concurrency) instead of replaying captured jsonl.

## Trust and verification

The standing proof of trustworthiness is the manifest at `docs/RESEED_MANIFEST_<ts>.json`, re-executed independently against the live stores:

```bash
python tools/verify_manifest.py --manifest docs/RESEED_MANIFEST_20260519T192150Z.json
python tools/generate_trust_report.py        # writes reports/TRUST_REPORT_latest.pdf
```

`verify_manifest.py` recomputes every claim and only then compares it to the manifest. `generate_trust_report.py` turns that verdict into a plain-language PDF. A GREEN report means the live data reproduces the certified contract. Re-run both after any restore.

## Backup and restore

`backups/` (gitignored) holds consistent physical backups of both stores, taken with the containers stopped for filesystem consistency. The backup procedure is its own inverse, so a restore is reliable. The runbook is [backups/RESTORE.md](backups/RESTORE.md). After restoring, re-run the trust verification above.
