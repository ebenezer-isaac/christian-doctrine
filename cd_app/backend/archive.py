"""Doctrine PDF archive: a read-only directory of per-question PDFs.

Serves a gated list and per-document download. Document ids are validated
against a strict slug pattern and every resolved path is confirmed to sit inside
the archive root, so a crafted id cannot traverse out of the directory.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")


class Archive:
    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self._titles: dict[str, str] = {}
        titles = self._root / "titles.json"
        if titles.exists():
            try:
                self._titles = json.loads(titles.read_text(encoding="utf-8"))
            except Exception:
                self._titles = {}

    def list(self) -> list[dict[str, Any]]:
        if not self._root.exists():
            return []
        out: list[dict[str, Any]] = []
        for p in sorted(self._root.glob("*.pdf")):
            doc_id = p.stem
            out.append(
                {
                    "id": doc_id,
                    "title": self._titles.get(doc_id, doc_id.replace("-", " ").title()),
                }
            )
        return out

    def path_for(self, doc_id: str) -> Path | None:
        if not _ID.match(doc_id):
            return None
        root = self._root.resolve()
        candidate = (root / f"{doc_id}.pdf").resolve()
        if root != candidate.parent:
            return None
        return candidate if candidate.exists() else None
