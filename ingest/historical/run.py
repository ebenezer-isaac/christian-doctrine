"""Pipeline 1 historical loader CLI.

Parses each in-scope historical source (via its pure adapter under
``ingest/historical/``) into HistoricalChunk records, writes them to
``data/historical_chunks/<slug>.jsonl``, and with ``--load`` upserts them to the
cultural Docker stack under the disjoint historical labels.

The adapter registry is resolved lazily so a partially-built tree (some adapters
not yet written) still runs for the adapters that exist. Each adapter module
exposes a module-level ``parse()`` returning an iterator of HistoricalChunk.

Usage:
    python ingest/historical/run.py --list
    python ingest/historical/run.py --source josephus           # parse -> jsonl
    python ingest/historical/run.py --source all --load         # parse + upsert
"""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Iterator

from ingest.historical._common import (
    HistoricalSettings,
    get_historical_driver,
    read_chunks_jsonl,
    write_chunks_jsonl,
)
from pipeline4.historical_schema import HistoricalChunk

# slug -> adapter module under ingest.historical. Each exposes parse().
ADAPTER_MODULES: dict[str, str] = {
    "josephus": "ingest.historical.josephus",
    "philo": "ingest.historical.philo",
    "pseudepigrapha": "ingest.historical.pseudepigrapha",
    "roman_historians": "ingest.historical.roman_historians",
    "pliny_melmoth": "ingest.historical.pliny_melmoth",
    "sefaria_mishnah": "ingest.historical.sefaria_mishnah",
    "etcbc_dss": "ingest.historical.etcbc_dss",
}


def _resolve_parse(slug: str):  # type: ignore[no-untyped-def]
    mod = importlib.import_module(ADAPTER_MODULES[slug])
    parse = getattr(mod, "parse", None)
    if parse is None:
        raise AttributeError(f"adapter {slug} has no parse() function")
    return parse


def _available() -> list[str]:
    out: list[str] = []
    for slug in ADAPTER_MODULES:
        try:
            _resolve_parse(slug)
            out.append(slug)
        except (ImportError, AttributeError):
            continue
    return out


def parse_source(slug: str) -> Iterator[HistoricalChunk]:
    return _resolve_parse(slug)()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", help="adapter slug, or 'all'")
    parser.add_argument("--list", action="store_true", help="list available adapters")
    parser.add_argument("--load", action="store_true", help="upsert parsed chunks to Neo4j")
    parser.add_argument(
        "--from-jsonl",
        action="store_true",
        help="load from existing data/historical_chunks/*.jsonl instead of re-parsing",
    )
    args = parser.parse_args(argv)

    if args.list:
        for slug in ADAPTER_MODULES:
            present = slug in _available()
            print(f"{'[x]' if present else '[ ]'} {slug} -> {ADAPTER_MODULES[slug]}")
        return 0

    if not args.source:
        parser.error("--source is required unless --list is passed")

    slugs = list(_available()) if args.source == "all" else [args.source]

    driver = None
    if args.load:
        from ingest.historical._common import upsert_historical_chunks

        settings = HistoricalSettings()  # type: ignore[call-arg]
        driver = get_historical_driver(settings)

    total = 0
    try:
        for slug in slugs:
            if args.from_jsonl:
                from ingest.historical._common import CHUNKS_OUT_DIR

                path = CHUNKS_OUT_DIR / f"{slug}.jsonl"
                if not path.exists():
                    print(f"skip missing jsonl: {path}", file=sys.stderr)
                    continue
                chunks = list(read_chunks_jsonl(path))
            else:
                chunks = list(parse_source(slug))
                out = write_chunks_jsonl(slug, chunks)
                print(f"{slug}: parsed {len(chunks)} chunks -> {out}")

            if args.load and driver is not None:
                counts = upsert_historical_chunks(driver, chunks)
                print(f"{slug}: upserted {counts}")
            total += len(chunks)
    finally:
        if driver is not None:
            driver.close()

    print(f"TOTAL chunks: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
