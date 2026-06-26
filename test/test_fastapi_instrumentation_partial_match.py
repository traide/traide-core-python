"""Regression: otel FastAPI instrumentation must not 500 on a partial route match.

opentelemetry-instrumentation-fastapi 0.63b1 reads `route.path` unguarded on a
`Match.PARTIAL` hit. FastAPI >=0.137 puts a lazy `_IncludedRouter` (no `.path`)
into `app.routes` for every `include_router()`, so a CORS preflight / method
mismatch against an included route raises AttributeError -> HTTP 500. Core pins
`fastapi~=0.136.3` (TRA-1286) so no `_IncludedRouter` exists. This test fails
loudly if fastapi is ever bumped back to >=0.137 without fixing the otel pin.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import (  # pyright: ignore[reportMissingTypeStubs]
    FastAPIInstrumentor,
)
from starlette.testclient import TestClient


def _instrumented_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://example.com"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    router = APIRouter()

    @router.get("/items")
    def items() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router, prefix="/api")
    FastAPIInstrumentor.instrument_app(app)  # pyright: ignore[reportUnknownMemberType]
    return app


def test_preflight_against_included_route_does_not_500() -> None:
    client = TestClient(_instrumented_app(), raise_server_exceptions=True)

    preflight = client.options(
        "/api/items",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight.status_code != 500

    assert client.post("/api/items").status_code == 405  # method mismatch -> PARTIAL
    assert client.get("/api/items").status_code == 200  # full match still works
