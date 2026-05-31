"""Tests for pipeline2.run CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline2.run import main


def test_validate_existing_empty_dir_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "evidence").mkdir()
    code = main(["--validate-existing"])
    assert code == 0


def test_validate_existing_invalid_file_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "doc-bogus.json").write_text(
        json.dumps({"$schema_version": "3.1"}), encoding="utf-8"
    )
    code = main(["--validate-existing"])
    assert code == 1


def test_mock_dispatch_single_question(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(tmp_path)
    (tmp_path / "evidence").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "phase_prompts").mkdir()
    (tmp_path / "docs" / "phase_prompts" / "pipeline2_verdict.md").write_text(
        (repo_root / "docs" / "phase_prompts" / "pipeline2_verdict.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    code = main(["--question-id", "doc-trinity", "--mock"])
    assert code == 0
    assert (tmp_path / "evidence" / "doc-trinity.json").exists()
    raw = json.loads((tmp_path / "evidence" / "doc-trinity.json").read_text(encoding="utf-8"))
    assert raw["$schema_version"] == "3.1"
    assert raw["verdict"]["lexical_breadth"] in {"canon_wide", "broad", "partial", "thin"}
    assert raw["verdict"]["lexical_directness"] in {
        "direct",
        "inferred",
        "analogical",
        "silent",
    }
    assert raw["verdict"]["variant_stability"] in {"stable", "sensitive", "not_in_scope"}


def test_triangle_mode_single_question(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(tmp_path)
    (tmp_path / "evidence").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "phase_prompts").mkdir()
    (tmp_path / "docs" / "phase_prompts" / "pipeline2_verdict.md").write_text(
        (repo_root / "docs" / "phase_prompts" / "pipeline2_verdict.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    code = main(["--question-id", "doc-trinity", "--mock", "--triangle"])
    assert code == 0


def test_missing_args_errors() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_non_mock_dispatch_returns_2() -> None:
    code = main(["--question-id", "doc-trinity"])
    assert code == 2
