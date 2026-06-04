"""License guard: pure redistribution checks per docs/LICENSE_TAGGING.md."""

from typing import Literal, TypedDict

Mode = Literal["bulk", "snippet"]

SNIPPET_WORD_CAP = 100
SNIPPET_SOURCE_FRACTION_CAP = 0.01

_COMPOSITE_MAP: dict[str, str] = {
    "macula-hebrew": "CC-BY-NC-4.0",
    "macula-greek": "CC-BY-NC-4.0",
}

# "pd" and "cc0" are the historical-layer slugs (docs/HISTORICAL_SCHEMA.md
# "license fields"): PD is public-domain-by-age (Whiston, Yonge, Charles,
# Melmoth, Torat Emet), CC0 is the Sefaria Community Translation dedication.
# Both are unconditionally redistributable, like the other permissive slugs.
_ALWAYS_ALLOWED = frozenset(
    {"public_domain", "pd", "cc0", "cc-by", "cc-by-4.0", "cc-by-sa-4.0"}
)
_SNIPPET_ONLY_CAPPED = frozenset({"cc-by-nc-4.0", "parsed-sanitized"})
_PROPRIETARY_PREFIXES = ("©", "(c)", "copyright", "proprietary", "fair-use")


class RedistributeResult(TypedDict):
    allowed: bool
    reason: str


def resolve_composite_license(slug: str) -> str:
    """Resolve a composite-source slug to its effective (most restrictive) license."""
    if not isinstance(slug, str) or not slug:
        return slug
    return _COMPOSITE_MAP.get(slug.lower(), slug)


def check_redistribute(
    license_str: str,
    mode: Mode,
    snippet_word_count: int = 0,
    source_work_word_count: int = 0,
) -> RedistributeResult:
    """Pure check whether the given license permits redistribution under the given mode."""
    if mode not in ("bulk", "snippet"):
        return {"allowed": False, "reason": f"invalid mode: {mode!r}"}
    if not isinstance(license_str, str) or not license_str.strip():
        return {"allowed": False, "reason": "empty license"}

    effective = resolve_composite_license(license_str)
    composite_note = ""
    if effective.lower() != license_str.lower():
        composite_note = f" (composite {license_str!r} resolved to {effective})"
    key = effective.lower()

    if key in _ALWAYS_ALLOWED:
        return {"allowed": True, "reason": f"{effective} always allowed{composite_note}"}

    if key == "cc-by-nc-4.0":
        if mode == "bulk":
            return {"allowed": False, "reason": f"CC-BY-NC-4.0 denies bulk{composite_note}"}
        return _snippet_check(effective, snippet_word_count, source_work_word_count, composite_note)

    if key == "sblgnt-eula":
        if mode == "bulk":
            return {"allowed": False, "reason": f"SBLGNT-EULA denies bulk{composite_note}"}
        return {
            "allowed": True,
            "reason": f"SBLGNT-EULA allows snippet (caller tracks 500-verses cap){composite_note}",
        }

    if key == "parsed-sanitized" or _matches_proprietary(key):
        if mode == "bulk":
            return {"allowed": False, "reason": f"{effective} denies bulk{composite_note}"}
        return _snippet_check(effective, snippet_word_count, source_work_word_count, composite_note)

    return {"allowed": False, "reason": f"unrecognized license: {license_str!r}"}


def _matches_proprietary(key: str) -> bool:
    return any(key.startswith(p) for p in _PROPRIETARY_PREFIXES)


def _snippet_check(
    effective: str, word_count: int, source_word_count: int, note: str
) -> RedistributeResult:
    if word_count <= 0:
        return {
            "allowed": False,
            "reason": f"{effective} snippet requires positive word count{note}",
        }
    if word_count > SNIPPET_WORD_CAP:
        return {
            "allowed": False,
            "reason": f"{effective} snippet exceeds {SNIPPET_WORD_CAP} word cap{note}",
        }
    if source_word_count <= 0:
        return {
            "allowed": False,
            "reason": f"{effective} snippet requires positive source word count{note}",
        }
    if word_count > SNIPPET_SOURCE_FRACTION_CAP * source_word_count:
        return {"allowed": False, "reason": f"{effective} snippet exceeds 1% of source{note}"}
    return {"allowed": True, "reason": f"{effective} snippet within caps{note}"}
