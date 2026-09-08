from keep_mcp.matching import match_items, normalize


def test_normalize_collapses_whitespace_and_case() -> None:
    assert normalize("  Oat   Milk ") == "oat milk"


def test_exact_match_is_preferred() -> None:
    items = [
        ("1", "Milk", False),
        ("2", "Oat milk", False),
        ("3", "Almond milk", True),
    ]
    result = match_items(items, ["oat milk"])
    assert [m.item_id for m in result.matched] == ["2"]
    assert result.unmatched == []
    assert result.ambiguous == {}


def test_unique_substring_matches() -> None:
    items = [("1", "Tesco Finest Butter", False), ("2", "Eggs", False)]
    result = match_items(items, ["butter"])
    assert result.matched[0].item_id == "1"


def test_ambiguous_substring_is_rejected() -> None:
    items = [("1", "Oat milk", False), ("2", "Almond milk", False)]
    result = match_items(items, ["milk"])
    assert result.matched == []
    assert result.ambiguous["milk"] == ["Oat milk", "Almond milk"]


def test_unmatched_query() -> None:
    result = match_items([("1", "Eggs", False)], ["bananas"])
    assert result.unmatched == ["bananas"]


def test_each_item_used_once() -> None:
    items = [("1", "Milk", False)]
    result = match_items(items, ["milk", "milk"])
    assert len(result.matched) == 1
    assert result.unmatched == ["milk"]
