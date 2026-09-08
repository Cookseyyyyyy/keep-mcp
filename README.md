# keep-mcp

A small [MCP](https://modelcontextprotocol.io/) server for **your** Google Keep — built to sit next to [`tesco-mcp`](https://github.com/Cookseyyyyyy/tesco-mcp) on the unRAID box.

Claude (or Cursor) can read the household shopping list, add items (including ones that arrived via Google Voice / Assistant), and **tick them off** once they are in the Tesco basket.

Keep has **no personal OAuth API**. This uses the unofficial [`gkeepapi`](https://github.com/kiwiz/gkeepapi) client. Auth is a Google **master token** — it can act as the whole account, so it never goes in git.

```
agent ──MCP HTTP──> keep-mcp ──gkeepapi──> Google Keep
agent ──MCP HTTP──> tesco-mcp ──> Tesco
```

Two separate connectors. Claude uses both in the same chat.

## Tools

| Tool | What it does |
|---|---|
| `keep_find` | Search notes/lists by title or body |
| `keep_get` | Fetch one list (default: `KEEP_DEFAULT_LIST`) |
| `keep_add_items` | Append unchecked items |
| `keep_check_items` | Tick items off by name |
| `keep_uncheck_items` | Untick items |
| `keep_remove_items` | Delete items by name |
| `keep_create_list` | Create a new checklist |

Item matching is case-insensitive. Unique substrings work (`"oat"` → `"Oat milk"`); ambiguous names (`"milk"` when both `Milk` and `Oat milk` exist) are rejected so Claude has to be specific.

Optional `KEEP_WRITE_TITLES=Shopping` restricts writes to that list. Leave it empty for a personal Keep.

## One-time: mint a master token

On this machine (not in the container):

```bash
uv sync
uv run keep-mcp-token
```

It walks you through [Google EmbeddedSetup](https://accounts.google.com/EmbeddedSetup): sign in, copy the `oauth_token` cookie, exchange it. Put `GOOGLE_EMAIL` and `GOOGLE_MASTER_TOKEN` in the container env. Treat the token like a password.

## Run locally

```bash
uv sync
uv run pytest
uv run keep-mcp            # stdio (Cursor / Claude Desktop)
uv run keep-mcp-http       # HTTP on :8788 (Claude custom connector)
```

## Deploy on unRAID (alongside tesco-mcp)

This image is Python-only — no Chrome — so it is a thin container next to the Tesco one, not a second Tesco-sized box.

1. Generate an opaque public hostname (same idea as Tesco):

   ```bash
   node -e "console.log('kpr-' + require('crypto').randomBytes(6).toString('hex'))"
   ```

2. In Cloudflare Zero Trust → your existing tunnel, add a published application: that hostname → `http://<unraid-ip>:8788`.

3. On the unRAID box:

   ```bash
   mkdir -p /mnt/user/appdata/keep-mcp
   MCP_AUTH_TOKEN=$(openssl rand -hex 24)   # save this

   docker run -d --name keep-mcp --restart unless-stopped \
     -p 8788:8788 \
     -e MCP_AUTH_TOKEN=$MCP_AUTH_TOKEN \
     -e MCP_PUBLIC_BASE_URL=https://<opaque-host>.<domain> \
     -e GOOGLE_EMAIL=you@gmail.com \
     -e GOOGLE_MASTER_TOKEN=<master-token> \
     -e KEEP_DEFAULT_LIST=Shopping \
     -e TZ=Europe/London \
     -v /mnt/user/appdata/keep-mcp:/home/app/.keep-mcp \
     ghcr.io/cookseyyyyyy/keep-mcp:latest
   ```

   GHCR is private (same as tesco-mcp) — the host must already be logged in to `ghcr.io`.

4. Health check: `curl https://<opaque-host>.<domain>/healthz` → `ok`.

## Connect Claude (web)

Same OAuth shim as Tesco / the Nice Touch MCP apps: one secret (`MCP_AUTH_TOKEN`), Claude obtains it via a consent page.

1. Claude → Settings → Connectors → Add custom connector.
2. URL only (no token field):

   ```
   https://<opaque-host>.<domain>/mcp
   ```

3. Connect → browser consent page → paste `MCP_AUTH_TOKEN` → Approve.

Cursor / Claude Code can skip OAuth and send `Authorization: Bearer <MCP_AUTH_TOKEN>` to the same `/mcp` URL.

## Typical Tesco shop

1. `keep_get` — unread items on the shopping list.
2. Tesco MCP: search, add to basket, book a slot.
3. `keep_check_items` — tick off what went in the basket.

Voice-added Keep items (Assistant / Google Voice) show up after the next `keep_get` / `keep_find`; Keep is synced on every tool call.
