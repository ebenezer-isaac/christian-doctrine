"""Pipeline 4: historical attestation sidecar engine.

Reads the historical store (air-gapped from the lexical store, co-resident in
the cultural Docker stack under disjoint labels) plus the locked lexical
verdict as read-only context, and produces per-question
``historical/<id>.json`` sidecar files conforming to the v1.0 schema at
``docs/HISTORICAL_SCHEMA.md``. Diagnostic only: never overrides the verdict.
"""
