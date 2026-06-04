// graph/cultural.cypher

CREATE CONSTRAINT tradition_slug IF NOT EXISTS FOR (t:Tradition) REQUIRE t.slug IS UNIQUE;
CREATE CONSTRAINT work_id IF NOT EXISTS FOR (w:Work) REQUIRE w.work_id IS UNIQUE;
CREATE CONSTRAINT cultural_chunk_id IF NOT EXISTS FOR (c:CulturalChunk) REQUIRE c.chunk_id IS UNIQUE;
CREATE CONSTRAINT doctrine_slug IF NOT EXISTS FOR (d:Doctrine) REQUIRE d.slug IS UNIQUE;
CREATE CONSTRAINT question_id IF NOT EXISTS FOR (q:Question) REQUIRE q.id IS UNIQUE;

CREATE INDEX work_tradition IF NOT EXISTS FOR (w:Work) ON (w.tradition);
CREATE INDEX work_date IF NOT EXISTS FOR (w:Work) ON (w.date_written);
CREATE INDEX cultural_chunk_anchor IF NOT EXISTS FOR (c:CulturalChunk) ON (c.anchor_id);
CREATE INDEX cultural_chunk_license IF NOT EXISTS FOR (c:CulturalChunk) ON (c.license);

CREATE INDEX has_chunk_rel IF NOT EXISTS FOR ()-[r:HAS_CHUNK]-() ON (r.created_at);
CREATE INDEX addresses_rel IF NOT EXISTS FOR ()-[r:ADDRESSES]-() ON (r.confidence);

CREATE FULLTEXT INDEX cultural_chunk_text IF NOT EXISTS FOR (c:CulturalChunk) ON EACH [c.text];

// ---------------------------------------------------------------------------
// Historical attestation layer (Pipeline 4). Co-resident in the cultural
// Docker stack but on disjoint labels (HistoricalSource, HistoricalWork,
// HistoricalChunk, ATTESTS) and a separate Qdrant collection (hist_col).
// The :Doctrine and :Question nodes above are shared anchors: the cultural
// layer reaches them via ADDRESSES, the historical layer via ATTESTS.
// Schema: docs/HISTORICAL_SCHEMA.md "Neo4j historical-attestation store".
// Constraint coverage is required for the H4 trustworthiness gate.
// ---------------------------------------------------------------------------

CREATE CONSTRAINT historical_source_slug IF NOT EXISTS FOR (s:HistoricalSource) REQUIRE s.slug IS UNIQUE;
CREATE CONSTRAINT historical_work_id IF NOT EXISTS FOR (w:HistoricalWork) REQUIRE w.work_id IS UNIQUE;
CREATE CONSTRAINT historical_chunk_id IF NOT EXISTS FOR (c:HistoricalChunk) REQUIRE c.chunk_id IS UNIQUE;

CREATE INDEX historical_source_type IF NOT EXISTS FOR (s:HistoricalSource) ON (s.source_type);
CREATE INDEX historical_work_lang IF NOT EXISTS FOR (w:HistoricalWork) ON (w.language);
CREATE INDEX historical_chunk_anchor IF NOT EXISTS FOR (c:HistoricalChunk) ON (c.anchor_id);
CREATE INDEX historical_chunk_license IF NOT EXISTS FOR (c:HistoricalChunk) ON (c.license);
CREATE INDEX historical_chunk_contested IF NOT EXISTS FOR (c:HistoricalChunk) ON (c.contested_interpolation_type);

CREATE INDEX historical_has_chunk_rel IF NOT EXISTS FOR ()-[r:HAS_CHUNK]-() ON (r.created_at);
CREATE INDEX attests_rel IF NOT EXISTS FOR ()-[r:ATTESTS]-() ON (r.attestation_type);

CREATE FULLTEXT INDEX historical_chunk_text IF NOT EXISTS FOR (c:HistoricalChunk) ON EACH [c.text];
