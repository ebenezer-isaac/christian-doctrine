"""Live-store retrieval injectors for the Pipeline 3 MCP tools.

The tool handlers in ``cd_mcp/tools/`` are pure: they transform injected data and
never open a store connection themselves. The modules in this package build the
injectors that bind those handlers to the running Neo4j + Qdrant stores. The
query-time air-gap holds here: ``lexical`` touches only the lexical store, and
``cultural`` touches only the cultural store.
"""
