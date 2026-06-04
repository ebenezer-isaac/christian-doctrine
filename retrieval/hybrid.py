"""Hybrid retrieval: dense (Voyage) + sparse (BM25) fused via RRF, optional graph expansion.

BM25 backend choice: Qdrant's native sparse-vector support via the BM25 modifier
(https://qdrant.tech/documentation/concepts/sparse-vectors/). The query encoder is
the BAAI/bge-m3 sparse output. Sparse vectors live in the same Qdrant collection
as the dense vectors under named-vector slots: "dense" and "sparse". This avoids
running a separate sparse search backend.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Store = Literal["lexical", "cultural"]

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
RRF_K = 60


class RetrievalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    qdrant_lexical_url: str = ""
    qdrant_cultural_url: str = ""
    neo4j_lexical_uri: str = ""
    neo4j_lexical_user: str = ""
    neo4j_lexical_password: str = ""
    neo4j_cultural_uri: str = ""
    neo4j_cultural_user: str = ""
    neo4j_cultural_password: str = ""
    voyage_api_key: str = ""


class RetrievedChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    score: float
    source_store: Store
    license: str
    redistribute: bool
    payload: dict[str, Any] = Field(default_factory=dict)


def rrf_fuse(
    dense: list[tuple[str, float]],
    sparse: list[tuple[str, float]],
    k: int = RRF_K,
) -> list[tuple[str, float]]:
    """Reciprocal rank fusion.

    Each input is a list of (id, raw_score) ordered by rank. RRF score for an id is
    sum over present rankings of 1 / (k + rank), where rank is 1-indexed.
    """
    scores: dict[str, float] = {}
    for rank, (pid, _raw) in enumerate(dense, start=1):
        scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank)
    for rank, (pid, _raw) in enumerate(sparse, start=1):
        scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


class HybridRetriever:
    """Hybrid retriever bound to one store.

    The retriever holds two backend handles: a Qdrant client (for dense + sparse)
    and a Neo4j driver (for graph expansion). Both are injected so tests can mock.
    """

    def __init__(
        self,
        store: Store,
        settings: RetrievalSettings,
        qdrant_client: Any | None = None,
        neo4j_driver: Any | None = None,
        voyage_client: Any | None = None,
    ) -> None:
        self.store: Store = store
        self.settings = settings
        self._qdrant = qdrant_client
        self._neo4j = neo4j_driver
        self._voyage = voyage_client
        self._collection = "lex_col" if store == "lexical" else "cult_col"

    def _embed_dense(self, query: str) -> list[float]:
        if self._voyage is None:
            return []
        from embeddings.bootstrap import VOYAGE_MODEL, VOYAGE_OUTPUT_DIMENSION

        result = self._voyage.embed(
            texts=[query],
            model=VOYAGE_MODEL,
            input_type="query",
            output_dimension=VOYAGE_OUTPUT_DIMENSION,
        )
        return [float(x) for x in result.embeddings[0]]

    def _query_dense(
        self, vector: list[float], k: int, filters: dict[str, Any] | None
    ) -> list[Any]:
        if self._qdrant is None or not vector:
            return []
        return self._qdrant.query_points(  # type: ignore[no-any-return]
            collection_name=self._collection,
            query=vector,
            using=DENSE_VECTOR_NAME,
            limit=k,
            query_filter=filters,
            with_payload=True,
        ).points

    def _query_sparse(self, query: str, k: int, filters: dict[str, Any] | None) -> list[Any]:
        if self._qdrant is None:
            return []
        return self._qdrant.query_points(  # type: ignore[no-any-return]
            collection_name=self._collection,
            query=query,
            using=SPARSE_VECTOR_NAME,
            limit=k,
            query_filter=filters,
            with_payload=True,
        ).points

    def _expand_graph(self, ids: list[str], hops: int = 1) -> list[str]:
        if self._neo4j is None or not ids:
            return []
        cypher = (
            "UNWIND $ids AS id "
            f"MATCH (n {{id: id}})-[*1..{int(hops)}]-(m) "
            "WHERE m.id IS NOT NULL AND NOT m.id IN $ids "
            "RETURN DISTINCT m.id AS id LIMIT 50"
        )
        with self._neo4j.session() as session:
            return [rec["id"] for rec in session.run(cypher, ids=ids)]

    def _point_to_chunk(self, point: Any, score: float) -> RetrievedChunk:
        payload = dict(point.payload or {})
        text = payload.pop("text", "")
        license_ = payload.pop("license", "<unknown>")
        redistribute = bool(payload.pop("redistribute", False))
        return RetrievedChunk(
            id=str(point.id),
            text=text,
            score=float(score),
            source_store=self.store,
            license=license_,
            redistribute=redistribute,
            payload=payload,
        )

    def retrieve(
        self,
        query: str,
        k: int = 10,
        filters: dict[str, Any] | None = None,
        expand_graph: bool = False,
    ) -> list[RetrievedChunk]:
        vector = self._embed_dense(query)
        dense_points = self._query_dense(vector, k * 2, filters)
        sparse_points = self._query_sparse(query, k * 2, filters)

        dense_ranked = [(str(p.id), float(p.score)) for p in dense_points]
        sparse_ranked = [(str(p.id), float(p.score)) for p in sparse_points]
        fused = rrf_fuse(dense_ranked, sparse_ranked)[:k]

        by_id: dict[str, Any] = {}
        for p in dense_points:
            by_id[str(p.id)] = p
        for p in sparse_points:
            by_id.setdefault(str(p.id), p)

        out: list[RetrievedChunk] = []
        for pid, score in fused:
            point = by_id.get(pid)
            if point is None:
                continue
            out.append(self._point_to_chunk(point, score))

        if expand_graph:
            expanded_ids = self._expand_graph([c.id for c in out])
            for eid in expanded_ids[: k // 2]:
                point = by_id.get(eid)
                if point is None:
                    continue
                out.append(self._point_to_chunk(point, 0.0))

        return out
