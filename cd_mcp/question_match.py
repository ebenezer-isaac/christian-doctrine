"""Match a free-text proposition to a stored question.

Primary path is semantic: each of the catalog questions is embedded once with
voyage-4-large (see ``embeddings/embed_questions.py``) and cached to disk; at
query time the proposition is embedded and cosine-matched against that cache.
When voyage or the cache is unavailable the matcher falls back to an
idf-weighted keyword overlap so the tool still answers offline.

Either way the matcher reports a confidence and a short candidate list. A
low-confidence or ambiguous match is surfaced rather than silently committed,
so a wrong mapping is visible and correctable instead of returning the wrong
question's verdict.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

QUESTIONS_PATH = Path("questions.json")
INDEX_PATH = Path("embeddings/question_index.npz")

# Cosine thresholds (semantic path).
SEM_HIGH_FLOOR = 0.50  # top match must clear this to be "high" on its own
SEM_HIGH_MARGIN = 0.03  # and beat the runner-up by at least this
SEM_NEAR_BAND = 0.04  # candidates within this of the top are "near" (ambiguous)
# Keyword thresholds (fallback path).
KW_HIGH_RATIO = 1.5  # top must beat runner-up by this ratio to be "high"
KW_NEAR_RATIO = 0.85  # candidates scoring >= this fraction of top are "near"

MAX_CANDIDATES = 5

_STOPWORDS = frozenset(
    ["a", "an", "the", "of", "and", "or", "but", "is", "are", "was", "were", "be", "been", "being", "to", "in", "on", "at", "by", "for", "with", "as", "that", "this", "it", "not", "no", "do", "does", "did", "his", "her", "its", "their", "our", "your", "my", "we", "you", "they", "he", "she", "them", "us", "into", "from", "than", "then", "over", "under", "will", "shall", "may", "might", "can", "could", "would", "should", "one", "true"]  # noqa: SIM905
)


# ---------------------------------------------------------------------------
# Catalog + keyword model (cached at module load, catalog is static)
# ---------------------------------------------------------------------------

_catalog_cache: list[dict[str, Any]] | None = None
_idf_cache: dict[str, float] | None = None


def _load_questions(path: Path | None = None) -> list[dict[str, Any]]:
    global _catalog_cache
    if path is None and _catalog_cache is not None:
        return _catalog_cache
    p = path or QUESTIONS_PATH
    if not p.exists():
        return []
    questions = json.loads(p.read_text(encoding="utf-8")).get("questions", [])
    if path is None:
        _catalog_cache = questions
    return questions


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in _STOPWORDS and len(t) > 2]


def _doc_words(q: dict[str, Any]) -> set[str]:
    return set(_tokens(q.get("statement", "")) + _tokens((q.get("id", "") or "").replace("-", " ")))


def _idf(questions: list[dict[str, Any]]) -> dict[str, float]:
    global _idf_cache
    if _idf_cache is not None and questions is _catalog_cache:
        return _idf_cache
    docfreq: dict[str, int] = {}
    for q in questions:
        for w in _doc_words(q):
            docfreq[w] = docfreq.get(w, 0) + 1
    n = len(questions)
    idf = {w: math.log((n + 1) / (df + 1)) + 1 for w, df in docfreq.items()}
    if questions is _catalog_cache:
        _idf_cache = idf
    return idf


def _keyword_rank(proposition: str, questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    idf = _idf(questions)
    pw = set(_tokens(proposition))
    scored: list[dict[str, Any]] = []
    for q in questions:
        overlap = pw & _doc_words(q)
        score = sum(idf.get(w, 1.0) for w in overlap)
        scored.append(
            {"question_id": q["id"], "statement": q.get("statement", ""), "score": round(score, 4)}
        )
    scored.sort(key=lambda c: c["score"], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Semantic index (precomputed voyage embeddings)
# ---------------------------------------------------------------------------

_index_cache: dict[str, Any] | None = None
_index_loaded = False


def load_question_index(index_path: Path | None = None) -> dict[str, Any] | None:
    """Load the cached question embeddings, or None when absent/unreadable."""
    global _index_cache, _index_loaded
    if index_path is None and _index_loaded:
        return _index_cache
    p = index_path or INDEX_PATH
    result: dict[str, Any] | None = None
    if p.exists():
        try:
            import numpy as np

            data = np.load(p, allow_pickle=True)
            vectors = data["vectors"].astype("float32")
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            result = {
                "ids": [str(x) for x in data["ids"].tolist()],
                "statements": [str(x) for x in data["statements"].tolist()],
                "unit_vectors": vectors / norms,
            }
        except Exception:
            result = None
    if index_path is None:
        _index_cache = result
        _index_loaded = True
    return result


def embed_query(text: str, voyage_client: Any) -> list[float] | None:
    """Embed a query string with voyage; None on any failure."""
    if voyage_client is None or not text:
        return None
    try:
        from embeddings.bootstrap import VOYAGE_MODEL, VOYAGE_OUTPUT_DIMENSION

        embed = voyage_client.embed(
            texts=[text],
            model=VOYAGE_MODEL,
            input_type="query",
            output_dimension=VOYAGE_OUTPUT_DIMENSION,
        )
        return [float(x) for x in embed.embeddings[0]]
    except Exception:
        return None


def _semantic_rank(query_vec: list[float], index: dict[str, Any]) -> list[dict[str, Any]]:
    import numpy as np

    q = np.asarray(query_vec, dtype="float32")
    norm = float(np.linalg.norm(q)) or 1.0
    sims = index["unit_vectors"] @ (q / norm)
    order = np.argsort(-sims)
    ids, statements = index["ids"], index["statements"]
    return [
        {"question_id": ids[i], "statement": statements[i], "score": round(float(sims[i]), 4)}
        for i in order
    ]


# ---------------------------------------------------------------------------
# Confidence + disambiguation
# ---------------------------------------------------------------------------


def _prefer_doctrine(candidates: list[dict[str, Any]], near_predicate: Any) -> dict[str, Any]:
    """Within the near-band, prefer a core ``doc-`` question over cult-/het-/prc-.

    The lexical baseline lives in the ``doc-`` questions; the others are contrast
    or practice cases. On a near-tie this nudges toward the canonical home
    without overriding a clear winner.
    """
    top = candidates[0]
    near = [c for c in candidates if near_predicate(top["score"], c["score"])]
    if len(near) <= 1:
        return top
    for c in near:
        if str(c["question_id"]).startswith("doc-"):
            return c
    return top


def _assess(method: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates or candidates[0]["score"] <= 0:
        return {
            "matched_qid": "",
            "matched_statement": "",
            "method": "none",
            "confidence": "none",
            "candidates": [],
        }
    top = candidates[0]
    runner = candidates[1]["score"] if len(candidates) > 1 else 0.0

    if method == "semantic":
        near_pred = lambda t, s: (t - s) <= SEM_NEAR_BAND  # noqa: E731
        is_high = top["score"] >= SEM_HIGH_FLOOR and (top["score"] - runner) >= SEM_HIGH_MARGIN
    else:
        near_pred = lambda t, s: s >= KW_NEAR_RATIO * t  # noqa: E731
        is_high = runner <= 0 or (top["score"] / runner) >= KW_HIGH_RATIO

    chosen = top if is_high else _prefer_doctrine(candidates, near_pred)
    confidence = "high" if is_high else "ambiguous"
    return {
        "matched_qid": chosen["question_id"],
        "matched_statement": chosen["statement"],
        "method": method,
        "confidence": confidence,
        "candidates": candidates[:MAX_CANDIDATES],
    }


def classify(
    proposition: str,
    *,
    voyage_client: Any | None = None,
    index: dict[str, Any] | None = None,
    questions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Match ``proposition`` to a question. Semantic when possible, else keyword.

    Returns ``{matched_qid, matched_statement, method, confidence, candidates}``.
    ``confidence`` is ``high`` for a clear winner, ``ambiguous`` when several
    questions are close (candidates list the alternatives), ``none`` when nothing
    overlaps.
    """
    qs = questions if questions is not None else _load_questions()
    if not qs:
        return {
            "matched_qid": "",
            "matched_statement": "",
            "method": "none",
            "confidence": "none",
            "candidates": [],
        }

    idx = index if index is not None else load_question_index()
    if idx is not None and voyage_client is not None:
        query_vec = embed_query(proposition, voyage_client)
        if query_vec is not None:
            return _assess("semantic", _semantic_rank(query_vec, idx))

    return _assess("keyword", _keyword_rank(proposition, qs))
