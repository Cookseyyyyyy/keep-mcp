"""Streamable-HTTP hosting with bearer + OAuth, matching tesco-mcp / nt-mcp-central."""

from __future__ import annotations

import logging
import os
import secrets
import sys
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import uvicorn
from dotenv import load_dotenv
from mcp.server.auth.provider import ProviderTokenVerifier
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp

from .errors import KeepMcpError
from .oauth import KeepOAuthProvider
from .server import build_server

_Scope = MutableMapping[str, Any]
_Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
_Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

_HEALTH_PATH = "/healthz"
_LABEL = "keep-mcp"


class BearerAuthMiddleware:
    def __init__(self, app: ASGIApp, *, token: str) -> None:
        self._app = app
        self._token = token

    async def __call__(self, scope: _Scope, receive: _Receive, send: _Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if path == _HEALTH_PATH or path.rstrip("/") == _HEALTH_PATH:
            health_response = PlainTextResponse("ok")
            await health_response(scope, receive, send)
            return

        if self._token and not self._is_authorized(scope):
            denied_response = JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await denied_response(scope, receive, send)
            return

        await self._app(scope, receive, send)

    def _is_authorized(self, scope: _Scope) -> bool:
        for key, value in scope.get("headers", []):
            if key == b"authorization":
                supplied = value.decode("latin-1")
                return secrets.compare_digest(supplied, f"Bearer {self._token}")
        return False


def _configure_logging() -> None:
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=os.environ.get("MCP_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _apply_hosted_settings(server: FastMCP, *, host: str, port: int) -> None:
    server.settings.host = host
    server.settings.port = port
    server.settings.stateless_http = True
    server.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )

    async def _health(_request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    server.custom_route(_HEALTH_PATH, methods=["GET"])(_health)


def run_http(*, host: str = "0.0.0.0", port: int | None = None) -> None:
    load_dotenv()
    _configure_logging()
    try:
        server = build_server()
    except KeepMcpError as exc:
        print(f"[{_LABEL}] Failed to start: {exc}", file=sys.stderr)
        sys.exit(1)

    resolved_port = port if port is not None else int(os.environ.get("PORT", "8788"))
    _apply_hosted_settings(server, host=host, port=resolved_port)

    token = os.environ.get("MCP_AUTH_TOKEN", "").strip()
    if not token:
        print(
            f"[{_LABEL}] WARNING: MCP_AUTH_TOKEN is not set — serving without "
            "authentication. Do not expose this publicly.",
            file=sys.stderr,
        )

    base = os.environ.get("MCP_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if base and not (
        base.startswith("https://")
        or base.startswith("http://localhost")
        or base.startswith("http://127.0.0.1")
    ):
        print(
            f"[{_LABEL}] WARNING: MCP_PUBLIC_BASE_URL={base!r} must start with "
            "https:// — ignoring it, OAuth will not work.",
            file=sys.stderr,
        )
        base = ""

    app: ASGIApp
    if token and base:
        provider = KeepOAuthProvider(shared_token=token, issuer_url=base, label=_LABEL)
        server._auth_server_provider = provider
        server._token_verifier = ProviderTokenVerifier(provider)
        server.settings.auth = AuthSettings(
            issuer_url=AnyHttpUrl(base),
            resource_server_url=AnyHttpUrl(f"{base}{server.settings.streamable_http_path}"),
            client_registration_options=ClientRegistrationOptions(enabled=True),
        )
        server.custom_route("/consent", methods=["GET", "POST"])(provider.handle_consent)
        app = server.streamable_http_app()
    elif token:
        print(
            f"[{_LABEL}] MCP_PUBLIC_BASE_URL not set — OAuth disabled; only "
            "Authorization: Bearer headers will work.",
            file=sys.stderr,
        )
        app = BearerAuthMiddleware(server.streamable_http_app(), token=token)
    else:
        app = server.streamable_http_app()

    print(f"[{_LABEL}] Serving streamable HTTP on {host}:{resolved_port} (endpoint: /mcp)")
    uvicorn.run(app, host=host, port=resolved_port, log_level="info")


def main() -> None:
    run_http()


if __name__ == "__main__":
    main()
