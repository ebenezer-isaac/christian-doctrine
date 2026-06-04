"""Pipeline 1 historical procurement adapters (Pipeline 4 inputs).

Each adapter parses LOCAL source files under ``data/private/historical/`` into
``HistoricalChunk`` records (pipeline4/historical_schema.py). Adapters are pure
(h6_adapter_purity): no network, no subprocess, no non-data/private path
literals. Fetch is a separate procurement step run by the orchestrator. The
loader in ``ingest/historical/run.py`` writes the parsed chunks to the cultural
Docker stack under the disjoint labels HistoricalSource, HistoricalWork,
HistoricalChunk and the HAS_CHUNK / CONTAINS edges.
"""
