"""Precompute voyage-4-large embeddings for the question catalog.

Embeds every question ``statement`` in ``questions.json`` and writes a compact
npz cache (``embeddings/question_index.npz``) that ``cd_mcp.question_match``
loads at query time for semantic proposition matching. Re-run whenever
questions.json changes:

    python -m embeddings.embed_questions

Fail-closed: if the voyage key is missing or the API is unreachable the script
exits non-zero and writes nothing, leaving any prior cache intact. The MCP tool
degrades to keyword matching when no cache is present, so this step is an
accuracy upgrade, not a hard dependency.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from embeddings.bootstrap import VOYAGE_MODEL, VOYAGE_OUTPUT_DIMENSION

QUESTIONS_PATH = Path("questions.json")
INDEX_PATH = Path("embeddings/question_index.npz")
BATCH = 100  # voyage accepts batches; the catalog is small so two calls suffice


def _voyage_key() -> str:
    from retrieval.hybrid import RetrievalSettings

    return getattr(RetrievalSettings(), "voyage_api_key", "") or ""


def build(questions_path: Path = QUESTIONS_PATH, index_path: Path = INDEX_PATH) -> int:
    import numpy as np
    import voyageai

    questions = json.loads(questions_path.read_text(encoding="utf-8")).get("questions", [])
    if not questions:
        print("no questions found", file=sys.stderr)
        return 1

    key = _voyage_key()
    if not key:
        print("voyage_api_key not set; cannot build index", file=sys.stderr)
        return 1

    ids = [q["id"] for q in questions]
    statements = [q.get("statement", "") for q in questions]
    client = voyageai.Client(api_key=key)

    vectors: list[list[float]] = []
    for start in range(0, len(statements), BATCH):
        batch = statements[start : start + BATCH]
        embed = client.embed(
            texts=batch,
            model=VOYAGE_MODEL,
            input_type="document",
            output_dimension=VOYAGE_OUTPUT_DIMENSION,
        )
        vectors.extend([float(x) for x in v] for v in embed.embeddings)

    index_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        index_path,
        ids=np.array(ids, dtype=object),
        statements=np.array(statements, dtype=object),
        vectors=np.asarray(vectors, dtype="float32"),
        model=VOYAGE_MODEL,
        dimension=VOYAGE_OUTPUT_DIMENSION,
    )
    print(f"wrote {len(ids)} question vectors ({VOYAGE_MODEL}, {VOYAGE_OUTPUT_DIMENSION}d) -> {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
