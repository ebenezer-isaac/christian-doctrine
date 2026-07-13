"""Performance baseline recording. Phase 06 Task 06.07.

ADVISORY targets only. Records p50 and p99 into tmp/integration/perf_baseline.json.
The test passes regardless of met_target; it only fails if any measurement is missing.
"""

from __future__ import annotations

import json
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cd_mcp.tools.concordance_walk import ConcordanceWalkInput
from cd_mcp.tools.concordance_walk import handle as concordance_handle
from cd_mcp.tools.cross_ref import CrossRefInput
from cd_mcp.tools.cross_ref import handle as cross_ref_handle
from cd_mcp.tools.cultural_overlay import CulturalOverlayInput
from cd_mcp.tools.cultural_overlay import handle as cultural_handle
from cd_mcp.tools.debate_for_verse import DebateForVerseInput
from cd_mcp.tools.debate_for_verse import handle as debate_handle
from cd_mcp.tools.lexical_lookup import LexicalLookupInput
from cd_mcp.tools.lexical_lookup import handle as lexical_lookup_handle
from cd_mcp.tools.parallel_translation import ParallelTranslationInput
from cd_mcp.tools.parallel_translation import handle as parallel_handle
from cd_mcp.tools.variant_inspect import VariantInspectInput
from cd_mcp.tools.variant_inspect import handle as variant_handle
from cd_mcp.tools.versification_resolve import VersificationResolveInput
from cd_mcp.tools.versification_resolve import handle as versification_handle

BASELINE_PATH = Path("tmp/integration/perf_baseline.json")

TARGETS = {
    "lexical_lookup": 100,
    "concordance_walk": 200,
    "cross_ref": 200,
    "variant_inspect": 100,
    "parallel_translation": 300,
    "versification_resolve": 50,
    "cultural_overlay": 500,
    "debate_for_verse": 800,
    "evidence_inspect": 50,
    "license_audit": 50,
}


def _measure(tool: str, fn: Callable[[], Any], runs: int = 20) -> dict[str, float | bool]:
    latencies: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        latencies.append((time.perf_counter() - t0) * 1000)
    latencies.sort()
    p50 = statistics.median(latencies)
    p99_index = max(0, int(round(0.99 * (len(latencies) - 1))))
    p99 = latencies[p99_index]
    target = TARGETS.get(tool, 1000)
    return {
        "tool": tool,
        "p50": round(p50, 3),
        "p99": round(p99, 3),
        "target_p50": target,
        "met_target": p50 <= target,
    }


def test_performance_baselines_recorded() -> None:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    measurements: list[dict[str, float | bool]] = []
    measurements.append(
        _measure(
            "lexical_lookup",
            lambda: lexical_lookup_handle(LexicalLookupInput(query="G2316", lang="gk")),
        )
    )
    measurements.append(
        _measure(
            "concordance_walk",
            lambda: concordance_handle(ConcordanceWalkInput(strong="G2316")),
        )
    )
    measurements.append(
        _measure("cross_ref", lambda: cross_ref_handle(CrossRefInput(ref="John.3.16")))
    )
    measurements.append(
        _measure("variant_inspect", lambda: variant_handle(VariantInspectInput(ref="John.1.1")))
    )
    measurements.append(
        _measure(
            "parallel_translation",
            lambda: parallel_handle(
                ParallelTranslationInput(
                    ref="John.1.1", translations=["ESV"], include_original=False
                )
            ),
        )
    )
    measurements.append(
        _measure(
            "versification_resolve",
            lambda: versification_handle(
                VersificationResolveInput(
                    ref="Psa.51.1", from_scheme="english", to_scheme="english"
                )
            ),
        )
    )
    measurements.append(
        _measure(
            "cultural_overlay",
            lambda: cultural_handle(CulturalOverlayInput(doctrine="x")),
        )
    )
    measurements.append(
        _measure(
            "debate_for_verse",
            lambda: debate_handle(DebateForVerseInput(ref="John.6.53")),
        )
    )

    BASELINE_PATH.write_text(json.dumps({"measurements": measurements}, indent=2), encoding="utf-8")
    for m in measurements:
        assert "p50" in m
        assert "p99" in m
        assert "tool" in m
