"""Minimal OAuth 2.1 authorization server wrapping MCP_AUTH_TOKEN.

Copied in spirit from nt-mcp-central's mcp_common.oauth: Claude's custom
connectors require DCR + PKCE, but there is still only one real secret
(MCP_AUTH_TOKEN). The consent page asks for that token and the access token
handed back *is* that same value.
"""

from __future__ import annotations

import html
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from .client import data_dir

_AUTH_CODE_TTL_SECONDS = 5 * 60
_ACCESS_TOKEN_TTL_SECONDS = 60 * 60
_REFRESH_TOKEN_TTL_SECONDS = 180 * 24 * 60 * 60


@dataclass
class _PendingAuthorization:
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    scopes: list[str]
    code_challenge: str
    state: str | None
    resource: str | None


class KeepOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    def __init__(self, *, shared_token: str, issuer_url: str, label: str) -> None:
        self._shared_token = shared_token
        self._issuer_url = issuer_url.rstrip("/")
        self._label = label
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._pending: dict[str, _PendingAuthorization] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}
        self._clients_path = data_dir() / "oauth-clients.json"
        self._load_clients()

    def _load_clients(self) -> None:
        if not self._clients_path.is_file():
            return
        try:
            raw = json.loads(self._clients_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        for client_id, info in raw.items():
            try:
                self._clients[client_id] = OAuthClientInformationFull.model_validate(info)
            except Exception:
                continue

    def _persist_clients(self) -> None:
        payload = {
            client_id: client.model_dump(mode="json") for client_id, client in self._clients.items()
        }
        path: Path = self._clients_path
        path.write_text(json.dumps(payload), encoding="utf-8")

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        assert client_info.client_id is not None
        self._clients[client_info.client_id] = client_info
        self._persist_clients()

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        assert client.client_id is not None
        transaction_id = secrets.token_urlsafe(24)
        self._pending[transaction_id] = _PendingAuthorization(
            client_id=client.client_id,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            scopes=params.scopes or [],
            code_challenge=params.code_challenge,
            state=params.state,
            resource=params.resource,
        )
        return f"{self._issuer_url}/consent?transaction_id={transaction_id}"

    async def handle_consent(self, request: Request) -> Response:
        if request.method == "GET":
            transaction_id = request.query_params.get("transaction_id", "")
            if transaction_id not in self._pending:
                return _expired_response()
            return HTMLResponse(_render_consent_page(self._label, transaction_id))

        form = await request.form()
        transaction_id = str(form.get("transaction_id", ""))
        pending = self._pending.get(transaction_id)
        if pending is None:
            return _expired_response()

        supplied_token = str(form.get("token", ""))
        if not secrets.compare_digest(supplied_token, self._shared_token):
            page = _render_consent_page(
                self._label, transaction_id, error="Incorrect token — try again."
            )
            return HTMLResponse(page, status_code=401)

        del self._pending[transaction_id]
        code = secrets.token_urlsafe(32)
        self._auth_codes[code] = AuthorizationCode(
            code=code,
            scopes=pending.scopes,
            expires_at=time.time() + _AUTH_CODE_TTL_SECONDS,
            client_id=pending.client_id,
            code_challenge=pending.code_challenge,
            redirect_uri=pending.redirect_uri,  # type: ignore[arg-type]
            redirect_uri_provided_explicitly=pending.redirect_uri_provided_explicitly,
            resource=pending.resource,
        )
        redirect_url = construct_redirect_uri(pending.redirect_uri, code=code, state=pending.state)
        return RedirectResponse(url=redirect_url, status_code=302)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        return self._auth_codes.get(authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        self._auth_codes.pop(authorization_code.code, None)
        refresh_token = self._issue_refresh_token(
            authorization_code.client_id, authorization_code.scopes
        )
        return self._issue_oauth_token(authorization_code.scopes, refresh_token)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        return self._refresh_tokens.get(refresh_token)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        self._refresh_tokens.pop(refresh_token.token, None)
        new_refresh_token = self._issue_refresh_token(refresh_token.client_id, scopes)
        return self._issue_oauth_token(scopes, new_refresh_token)

    async def load_access_token(self, token: str) -> AccessToken | None:
        if secrets.compare_digest(token, self._shared_token):
            return AccessToken(token=token, client_id="shared", scopes=["mcp"], expires_at=None)
        return None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, RefreshToken):
            self._refresh_tokens.pop(token.token, None)

    def _issue_refresh_token(self, client_id: str, scopes: list[str]) -> str:
        token = secrets.token_urlsafe(32)
        self._refresh_tokens[token] = RefreshToken(
            token=token,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(time.time() + _REFRESH_TOKEN_TTL_SECONDS),
        )
        return token

    def _issue_oauth_token(self, scopes: list[str], refresh_token: str) -> OAuthToken:
        return OAuthToken(
            access_token=self._shared_token,
            token_type="Bearer",
            expires_in=_ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(scopes) if scopes else None,
            refresh_token=refresh_token,
        )


def _expired_response() -> HTMLResponse:
    return HTMLResponse(
        _PAGE_TEMPLATE.format(
            title="Link expired",
            body="<p>This authorization link expired or was already used.</p>"
            "<p>Go back to Claude and try connecting again.</p>",
        ),
        status_code=400,
    )


def _render_consent_page(label: str, transaction_id: str, *, error: str | None = None) -> str:
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    body = f"""
    <p>Approve Claude's connection to <strong>{html.escape(label)}</strong> by
    entering its access token below (the same <code>MCP_AUTH_TOKEN</code> used
    for direct/header-based clients).</p>
    {error_html}
    <form method="post" action="">
      <input type="hidden" name="transaction_id" value="{html.escape(transaction_id)}">
      <input type="password" name="token" placeholder="Access token" autofocus required>
      <button type="submit">Approve</button>
    </form>
    """
    return _PAGE_TEMPLATE.format(title=f"Connect to {html.escape(label)}", body=body)


_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{
    font-family: system-ui, sans-serif; max-width: 32rem; margin: 4rem auto;
    padding: 0 1rem; color: #1a1a1a;
  }}
  h1 {{ font-size: 1.25rem; }}
  input, button {{
    font-size: 1rem; padding: 0.5rem; width: 100%;
    box-sizing: border-box; margin-top: 0.75rem;
  }}
  button {{ cursor: pointer; background: #1a1a1a; color: #fff; border: none; border-radius: 4px; }}
  code {{ background: #f0f0f0; padding: 0.1rem 0.3rem; border-radius: 3px; }}
  .error {{ color: #b00020; }}
</style>
</head>
<body>
<h1>{title}</h1>
{body}
</body>
</html>
"""
