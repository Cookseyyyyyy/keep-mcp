"""MCP tools for Google Keep lists — read, add, check off."""

from __future__ import annotations

import asyncio
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .client import get_client
from .errors import KeepMcpError

_INSTRUCTIONS = """\
Tools for the user's personal Google Keep, especially the household shopping list.
Typical Tesco shop: keep_get the shopping list, search Tesco and add to the basket
with tesco-mcp, then keep_check_items for everything that went in the basket.
Prefer KEEP_DEFAULT_LIST when no title is given. Matching is by item text
(case-insensitive); unique substrings are accepted, ambiguous names are rejected.
"""


def _ok(payload: dict[str, Any]) -> dict[str, Any]:
    return payload


def _fail(exc: KeepMcpError) -> dict[str, Any]:
    return {"error": str(exc)}


def build_server() -> FastMCP:
    mcp = FastMCP(name="keep-mcp", instructions=_INSTRUCTIONS)

    @mcp.tool(
        description=(
            "Search Keep notes and checklists by title or body text. "
            "Returns id, title, type (list/note), pinned, and for lists the items. "
            "Use this to find the shopping list if you do not know its exact title."
        )
    )
    async def keep_find(query: str = "", limit: int = 20) -> dict[str, Any]:
        try:
            notes = await asyncio.to_thread(get_client().find, query, limit=limit)
            return _ok({"notes": notes})
        except KeepMcpError as exc:
            return _fail(exc)

    @mcp.tool(
        description=(
            "Get one Keep note or checklist. Pass list_title (e.g. 'Shopping') or "
            "note_id from keep_find. If both are omitted, uses KEEP_DEFAULT_LIST. "
            "Lists include each item's text and checked state."
        )
    )
    async def keep_get(
        list_title: str | None = None,
        note_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            return _ok(
                await asyncio.to_thread(get_client().get, note_id=note_id, title=list_title)
            )
        except KeepMcpError as exc:
            return _fail(exc)

    @mcp.tool(
        description=(
            "Add one or more unchecked items to a Keep checklist (the shopping list). "
            "Does not create duplicates automatically — check keep_get first."
        )
    )
    async def keep_add_items(
        items: list[str],
        list_title: str | None = None,
        note_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            return _ok(
                await asyncio.to_thread(
                    get_client().add_items, items, note_id=note_id, title=list_title
                )
            )
        except KeepMcpError as exc:
            return _fail(exc)

    @mcp.tool(
        description=(
            "Tick off Keep checklist items after they have been added to the Tesco "
            "basket (or bought). Match by item name; unique substrings are ok."
        )
    )
    async def keep_check_items(
        items: list[str],
        list_title: str | None = None,
        note_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            return _ok(
                await asyncio.to_thread(
                    get_client().set_checked,
                    items,
                    checked=True,
                    note_id=note_id,
                    title=list_title,
                )
            )
        except KeepMcpError as exc:
            return _fail(exc)

    @mcp.tool(
        description="Untick Keep checklist items (put them back on the shopping list)."
    )
    async def keep_uncheck_items(
        items: list[str],
        list_title: str | None = None,
        note_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            return _ok(
                await asyncio.to_thread(
                    get_client().set_checked,
                    items,
                    checked=False,
                    note_id=note_id,
                    title=list_title,
                )
            )
        except KeepMcpError as exc:
            return _fail(exc)

    @mcp.tool(description="Delete items from a Keep checklist by name.")
    async def keep_remove_items(
        items: list[str],
        list_title: str | None = None,
        note_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            return _ok(
                await asyncio.to_thread(
                    get_client().remove_items, items, note_id=note_id, title=list_title
                )
            )
        except KeepMcpError as exc:
            return _fail(exc)

    @mcp.tool(
        description=(
            "Create a new Keep checklist. Use this only if the shopping list does not "
            "already exist — prefer keep_add_items on the existing list."
        )
    )
    async def keep_create_list(
        title: str,
        items: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            return _ok(await asyncio.to_thread(get_client().create_list, title, items))
        except KeepMcpError as exc:
            return _fail(exc)

    return mcp


def main() -> None:
    load_dotenv()
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
