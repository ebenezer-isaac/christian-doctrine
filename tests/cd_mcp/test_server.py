"""Tests for cd_mcp.server (skeleton + tool registration)."""

from __future__ import annotations

import asyncio

from cd_mcp.server import TOOL_NAMES, build_server


def test_tool_names_count_is_12() -> None:
    assert len(TOOL_NAMES) == 12
    assert len(set(TOOL_NAMES)) == 12


def test_build_server_returns_fastmcp() -> None:
    server = build_server()
    assert server is not None
    assert hasattr(server, "tool")


def test_server_lists_all_tools() -> None:
    server = build_server()
    listed = asyncio.run(server.list_tools())
    names = {t.name for t in listed}
    assert names == set(TOOL_NAMES)


def test_no_mcp_directory_at_repo_root() -> None:
    from pathlib import Path

    assert not Path("mcp").is_dir(), "repo must not have a top-level mcp/ directory"
