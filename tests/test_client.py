from __future__ import annotations

from typing import Any

import pytest

from keep_mcp.client import KeepClient
from keep_mcp.errors import KeepMcpError


class FakeItem:
    def __init__(self, text: str, checked: bool = False) -> None:
        self.id = f"item-{text}"
        self.text = text
        self.checked = checked
        self.deleted = False

    def delete(self) -> None:
        self.deleted = True


class FakeList:
    def __init__(self, title: str, items: list[str] | None = None, *, pinned: bool = True) -> None:
        self.id = f"list-{title}"
        self.title = title
        self.pinned = pinned
        self.archived = False
        self.trashed = False
        self.items = [FakeItem(text) for text in (items or [])]

    def add(self, text: str, checked: bool = False) -> FakeItem:
        item = FakeItem(text, checked)
        self.items.append(item)
        return item


class FakeKeep:
    def __init__(self, notes: list[Any]) -> None:
        self.notes = notes

    def all(self) -> list[Any]:
        return list(self.notes)

    def createList(self, title: str, items: list[tuple[str, bool]] | None = None) -> FakeList:
        keep_list = FakeList(title, [text for text, _checked in (items or [])])
        self.notes.append(keep_list)
        return keep_list

    def dump(self) -> dict[str, Any]:
        return {}


class Harness(KeepClient):
    def __init__(self, keep: FakeKeep) -> None:
        super().__init__()
        self._keep = keep

    def _sync(self) -> None:
        return

    def _save_state(self) -> None:
        return


def test_get_default_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEEP_DEFAULT_LIST", "Shopping")
    shopping = FakeList("Shopping", ["Milk", "Eggs"])
    client = Harness(FakeKeep([shopping]))
    payload = client.get()
    assert payload["title"] == "Shopping"
    assert payload["unchecked"] == ["Milk", "Eggs"]


def test_add_and_check_items() -> None:
    shopping = FakeList("Shopping", ["Milk"])
    client = Harness(FakeKeep([shopping]))
    added = client.add_items(["Butter"], title="Shopping")
    assert "Butter" in added["unchecked"]
    checked = client.set_checked(["milk"], checked=True, title="Shopping")
    assert checked["updated"] == ["Milk"]
    assert checked["checked"] == ["Milk"]
    assert "Milk" not in checked["unchecked"]


def test_ambiguous_check_is_an_error() -> None:
    shopping = FakeList("Shopping", ["Oat milk", "Almond milk"])
    client = Harness(FakeKeep([shopping]))
    with pytest.raises(KeepMcpError, match="ambiguous"):
        client.set_checked(["milk"], checked=True, title="Shopping")


def test_write_titles_blocks_other_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEEP_WRITE_TITLES", "Shopping")
    other = FakeList("Recipes", ["Flour"])
    client = Harness(FakeKeep([shopping := FakeList("Shopping", ["Milk"]), other]))
    client.add_items(["Eggs"], title="Shopping")
    with pytest.raises(KeepMcpError, match="blocked"):
        client.add_items(["Sugar"], title="Recipes")
    assert shopping.items[-1].text == "Eggs"
