from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from keep_mcp.http import BearerAuthMiddleware


def _app(token: str) -> TestClient:
    async def ping(_request):  # type: ignore[no-untyped-def]
        return PlainTextResponse("pong")

    inner = Starlette(routes=[Route("/mcp", ping, methods=["POST"])])
    return TestClient(BearerAuthMiddleware(inner, token=token))


def test_healthz_is_open() -> None:
    client = _app("secret")
    # healthz is handled before the inner app, even if the inner app has no such route
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"


def test_mcp_requires_bearer_token() -> None:
    client = _app("secret")
    denied = client.post("/mcp")
    assert denied.status_code == 401
    allowed = client.post("/mcp", headers={"Authorization": "Bearer secret"})
    assert allowed.status_code == 200
    assert allowed.text == "pong"
