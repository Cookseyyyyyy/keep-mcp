"""Match shopping-list items by name without requiring Keep IDs."""

from __future__ import annotations

from dataclasses import dataclass


def normalize(text: str) -> str:
    return " ".join(text.casefold().split())


@dataclass(frozen=True)
class ItemMatch:
    query: str
    item_id: str
    text: str
    checked: bool


@dataclass
class MatchResult:
    matched: list[ItemMatch]
    unmatched: list[str]
    ambiguous: dict[str, list[str]]


def match_items(
    items: list[tuple[str, str, bool]],
    queries: list[str],
) -> MatchResult:
    """Match queries against ``(id, text, checked)`` items.

    Preference order per query: exact normalized title, then a unique
    substring match. Multiple substring hits are reported as ambiguous
    instead of guessing.
    """
    result = MatchResult(matched=[], unmatched=[], ambiguous={})
    remaining = list(items)
    used_ids: set[str] = set()

    for query in queries:
        needle = normalize(query)
        if not needle:
            result.unmatched.append(query)
            continue

        exact = [
            (item_id, text, checked)
            for item_id, text, checked in remaining
            if item_id not in used_ids and normalize(text) == needle
        ]
        if len(exact) == 1:
            item_id, text, checked = exact[0]
            used_ids.add(item_id)
            result.matched.append(ItemMatch(query, item_id, text, checked))
            continue
        if len(exact) > 1:
            result.ambiguous[query] = [text for _, text, _ in exact]
            continue

        contains = [
            (item_id, text, checked)
            for item_id, text, checked in remaining
            if item_id not in used_ids and needle in normalize(text)
        ]
        if len(contains) == 1:
            item_id, text, checked = contains[0]
            used_ids.add(item_id)
            result.matched.append(ItemMatch(query, item_id, text, checked))
            continue
        if len(contains) > 1:
            result.ambiguous[query] = [text for _, text, _ in contains]
            continue

        result.unmatched.append(query)

    return result
