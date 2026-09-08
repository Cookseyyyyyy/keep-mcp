"""Thin gkeepapi wrapper with a lock, state cache, and shopping-list helpers."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import gkeepapi
from gkeepapi.node import List as KeepList

from .errors import KeepMcpError
from .matching import match_items


def is_keep_list(note: Any) -> bool:
    return isinstance(note, KeepList) or (
        hasattr(note, "items") and callable(getattr(note, "add", None))
    )


def data_dir() -> Path:
    raw = os.environ.get("KEEP_DATA_DIR", "").strip()
    path = Path(raw).expanduser() if raw else Path.home() / ".keep-mcp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_list_title() -> str:
    return os.environ.get("KEEP_DEFAULT_LIST", "").strip()


def write_titles() -> set[str]:
    raw = os.environ.get("KEEP_WRITE_TITLES", "").strip()
    if not raw:
        return set()
    return {part.strip().casefold() for part in raw.split(",") if part.strip()}


def _serialize_item(item: Any) -> dict[str, Any]:
    return {"id": item.id, "text": item.text, "checked": bool(item.checked)}


def serialize_note(note: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": note.id,
        "title": note.title or "",
        "type": "list" if is_keep_list(note) else "note",
        "pinned": bool(note.pinned),
        "archived": bool(note.archived),
    }
    if is_keep_list(note):
        payload["items"] = [_serialize_item(item) for item in note.items]
        payload["unchecked"] = [item.text for item in note.items if not item.checked]
        payload["checked"] = [item.text for item in note.items if item.checked]
    else:
        payload["text"] = getattr(note, "text", "") or ""
    return payload


class KeepClient:
    """One authenticated Keep session, reused across MCP requests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._keep: gkeepapi.Keep | None = None

    def _state_path(self) -> Path:
        return data_dir() / "state.json"

    def _load_state(self) -> dict[str, Any] | None:
        path = self._state_path()
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _save_state(self) -> None:
        if self._keep is None:
            return
        self._state_path().write_text(json.dumps(self._keep.dump()), encoding="utf-8")

    def _connect(self) -> gkeepapi.Keep:
        email = os.environ.get("GOOGLE_EMAIL", "").strip()
        token = os.environ.get("GOOGLE_MASTER_TOKEN", "").strip()
        if not email or not token:
            raise KeepMcpError(
                "GOOGLE_EMAIL and GOOGLE_MASTER_TOKEN must be set. "
                "Run `uv run keep-mcp-token` to mint a master token."
            )
        keep = gkeepapi.Keep()
        keep.authenticate(email, token, state=self._load_state())
        self._keep = keep
        self._save_state()
        return keep

    def _session(self) -> gkeepapi.Keep:
        if self._keep is None:
            self._keep = self._connect()
        return self._keep

    def _sync(self) -> None:
        keep = self._session()
        keep.sync()
        self._save_state()

    def _visible_notes(self) -> list[Any]:
        keep = self._session()
        return [
            note
            for note in keep.all()
            if not getattr(note, "trashed", False) and not getattr(note, "archived", False)
        ]

    def _resolve_note(self, *, note_id: str | None, title: str | None) -> Any:
        notes = self._visible_notes()
        if note_id:
            for note in notes:
                if note.id == note_id:
                    return note
            raise KeepMcpError(f"No Keep note found with id {note_id!r}.")

        wanted = (title or default_list_title()).strip()
        if not wanted:
            raise KeepMcpError(
                "Pass list_title or set KEEP_DEFAULT_LIST (e.g. Shopping)."
            )
        matches = [note for note in notes if (note.title or "").casefold() == wanted.casefold()]
        if not matches:
            raise KeepMcpError(f"No Keep note titled {wanted!r}.")
        matches.sort(key=lambda note: (not note.pinned, note.title or ""))
        return matches[0]

    def _require_list(self, note: Any) -> Any:
        if not is_keep_list(note):
            raise KeepMcpError(
                f"{note.title!r} is a plain note, not a checklist. "
                "Use keep_create_list for a tickable shopping list."
            )
        return note

    def _assert_writable(self, note: Any) -> None:
        allowed = write_titles()
        if not allowed:
            return
        title = (note.title or "").casefold()
        if title not in allowed:
            raise KeepMcpError(
                f"Writes to {note.title!r} are blocked. "
                f"KEEP_WRITE_TITLES currently allows: {sorted(allowed)}."
            )

    def find(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            self._sync()
            needle = query.strip().casefold()
            notes = self._visible_notes()
            if needle:
                notes = [
                    note
                    for note in notes
                    if needle in (note.title or "").casefold()
                    or needle in (getattr(note, "text", "") or "").casefold()
                ]
            notes.sort(key=lambda note: (not note.pinned, (note.title or "").casefold()))
            return [serialize_note(note) for note in notes[: max(1, min(limit, 50))]]

    def get(self, *, note_id: str | None = None, title: str | None = None) -> dict[str, Any]:
        with self._lock:
            self._sync()
            return serialize_note(self._resolve_note(note_id=note_id, title=title))

    def add_items(
        self,
        texts: list[str],
        *,
        note_id: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        cleaned = [text.strip() for text in texts if text.strip()]
        if not cleaned:
            raise KeepMcpError("Pass at least one non-empty item.")
        with self._lock:
            self._sync()
            keep_list = self._require_list(self._resolve_note(note_id=note_id, title=title))
            self._assert_writable(keep_list)
            added = [keep_list.add(text, False).text for text in cleaned]
            self._sync()
            payload = serialize_note(keep_list)
            payload["added"] = added
            return payload

    def set_checked(
        self,
        queries: list[str],
        *,
        checked: bool,
        note_id: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        if not queries:
            raise KeepMcpError("Pass at least one item name to check or uncheck.")
        with self._lock:
            self._sync()
            keep_list = self._require_list(self._resolve_note(note_id=note_id, title=title))
            self._assert_writable(keep_list)
            snapshot = [(item.id, item.text, bool(item.checked)) for item in keep_list.items]
            matches = match_items(snapshot, queries)
            if matches.unmatched or matches.ambiguous:
                raise KeepMcpError(
                    "Could not uniquely match every item. "
                    f"unmatched={matches.unmatched} ambiguous={matches.ambiguous}."
                )
            by_id = {item.id: item for item in keep_list.items}
            updated: list[str] = []
            for match in matches.matched:
                item = by_id[match.item_id]
                item.checked = checked
                updated.append(item.text)
            self._sync()
            payload = serialize_note(keep_list)
            payload["updated"] = updated
            payload["checked_set_to"] = checked
            return payload

    def remove_items(
        self,
        queries: list[str],
        *,
        note_id: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        if not queries:
            raise KeepMcpError("Pass at least one item name to remove.")
        with self._lock:
            self._sync()
            keep_list = self._require_list(self._resolve_note(note_id=note_id, title=title))
            self._assert_writable(keep_list)
            snapshot = [(item.id, item.text, bool(item.checked)) for item in keep_list.items]
            matches = match_items(snapshot, queries)
            if matches.unmatched or matches.ambiguous:
                raise KeepMcpError(
                    "Could not uniquely match every item. "
                    f"unmatched={matches.unmatched} ambiguous={matches.ambiguous}."
                )
            by_id = {item.id: item for item in keep_list.items}
            removed: list[str] = []
            for match in matches.matched:
                item = by_id[match.item_id]
                removed.append(item.text)
                item.delete()
            self._sync()
            payload = serialize_note(keep_list)
            payload["removed"] = removed
            return payload

    def create_list(self, title: str, items: list[str] | None = None) -> dict[str, Any]:
        title = title.strip()
        if not title:
            raise KeepMcpError("A list title is required.")
        cleaned = [text.strip() for text in (items or []) if text.strip()]
        with self._lock:
            self._sync()
            existing = [
                note
                for note in self._visible_notes()
                if (note.title or "").casefold() == title.casefold()
            ]
            if existing:
                raise KeepMcpError(f"A Keep note titled {title!r} already exists.")
            keep = self._session()
            keep_list = keep.createList(title, [(text, False) for text in cleaned])
            self._assert_writable(keep_list)
            self._sync()
            return serialize_note(keep_list)


_CLIENT: KeepClient | None = None
_CLIENT_LOCK = threading.Lock()


def get_client() -> KeepClient:
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = KeepClient()
        return _CLIENT
