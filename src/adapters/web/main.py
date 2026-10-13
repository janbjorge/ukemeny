"""FastAPI + Jinja + HTMX. Every fragment is also reachable as a full page via the same query string."""

import hashlib
import os
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from adapters import profile
from adapters.datasets import JsonDatasets
from adapters.web import api, fmt
from adapters.web.params import KNOWN_PROTEINS, DinnerQuery
from app.queries import Queries

HERE = Path(__file__).parent
# The one public address (matris.app). Set on Fly once the certificate and DNS are live; every other
# host name, such as matris.fly.dev or www., then redirects here. Unset locally and in tests.
CANONICAL_HOST = os.environ.get("CANONICAL_HOST", "")
# On every page, for agents: the llms.txt guide and the API schema (service-desc, RFC 8631)
LINK = '</llms.txt>; rel="alternate"; type="text/markdown", </api/openapi.json>; rel="service-desc"; type="application/json"'
# The pages a crawler should index; the query-string variants and fragments stay out (see robots_txt)
PAGES = ("", "om")

type Q = Annotated[str | None, Query()]


class HeadAsGet:
    """Answer HEAD like GET without the body. Routes only take GET; link checkers and preview bots send HEAD."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "HEAD":
            return await self.app(scope, receive, send)

        async def headers_only(message: Message) -> None:
            await send({**message, "body": b""} if message["type"] == "http.response.body" else message)

        await self.app({**scope, "method": "GET"}, receive, headers_only)


# Content hash per static file, read once at start-up: the image is rebuilt for every change
STATIC_HASHES = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:10] for p in (HERE / "static").iterdir() if p.is_file()}


def static_url(name: str) -> str:
    return f"/static/{name}?v={STATIC_HASHES[name]}"


def create_app(queries: Queries) -> FastAPI:
    app = FastAPI(title="matris.app", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.middleware("http")
    async def headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if CANONICAL_HOST and request.url.hostname != CANONICAL_HOST and request.url.path != "/helse":
            # /helse stays: Fly's health check reaches the machine under another host name
            return RedirectResponse(str(request.url.replace(scheme="https", netloc=CANONICAL_HOST)), status_code=301)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:"
        )
        path = request.url.path
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Link"] = LINK
        if path.startswith("/static/") and "v" in request.query_params:
            # static_url() puts the content hash in ?v=, so a changed file gets a new URL and this one never goes stale
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=3600"
        else:
            # One URL answers a full page or a redirect without HTMX and a fragment with it; a cache must keep them apart
            response.headers["Vary"] = ", ".join(filter(None, (response.headers.get("Vary"), "HX-Request")))
            if "hx-request" not in request.headers:
                response.headers["Cache-Control"] = "public, max-age=300"
        return response

    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.mount("/api", api.build(queries))

    def context(request: Request) -> dict[str, object]:
        """Names every template can use."""
        return {
            "static_url": static_url,
            "canonical": f"https://{CANONICAL_HOST}{request.url.path}" if CANONICAL_HOST else "",
            "household": queries.household_lines(),
            "built": queries.snapshot.built,
            "offers_until": queries.offers_until(),
            "stale": queries.stale(date.today()),
            "fish": queries.week.fish,
        }

    templates = Jinja2Templates(directory=HERE / "templates", context_processors=[context])
    templates.env.filters |= {name: getattr(fmt, name) for name in fmt.__all__}

    def dinner_context(choice: DinnerQuery) -> dict[str, object]:
        counts = dict(queries.proteins())
        week = {d.dish.url for d in queries.plan().dinners}  # shown above the list already
        found = queries.dinners(choice.protein, choice.tilbud, limit=choice.antall + len(week))
        return {
            "choice": choice,
            "dinners": [d for d in found if d.dish.url not in week][: choice.antall],
            "proteins": [(p, counts[p]) for p in KNOWN_PROTEINS if p in counts],
        }

    def _choice(protein: str | None, tilbud: str | None, antall: str | None) -> DinnerQuery:
        return DinnerQuery.model_validate({k: v for k, v in {"protein": protein, "tilbud": tilbud, "antall": antall}.items() if v})

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, protein: Q = None, tilbud: Q = None, antall: Q = None) -> HTMLResponse:
        week = queries.plan()
        return templates.TemplateResponse(request, "index.html", {"week": week, **dinner_context(_choice(protein, tilbud, antall))})

    @app.get("/middager", response_class=HTMLResponse)
    def dinners_fragment(request: Request, protein: Q = None, tilbud: Q = None, antall: Q = None) -> Response:
        """The list of ideas under the week. Without HTMX it is the front page with the same choices."""
        choice = _choice(protein, tilbud, antall)
        if "hx-request" not in request.headers:
            query = choice.query()
            return RedirectResponse(f"/?{query}#forslag" if query else "/#forslag", status_code=303)
        response = templates.TemplateResponse(request, "_dinners.html", dinner_context(choice))
        response.headers["HX-Replace-Url"] = f"/?{choice.query()}#forslag" if choice.query() else "/#forslag"
        return response

    @app.get("/om", response_class=HTMLResponse)
    def about(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "om.html", {"plan": queries.plan()})

    @app.get("/llms.txt", response_class=PlainTextResponse)
    def llms_txt(request: Request) -> Response:
        """Entry point for AI agents (llmstxt.org): what the site is and the JSON API."""
        return templates.TemplateResponse(
            request, "llms.txt", {"base": str(request.base_url), "proteins": ", ".join(KNOWN_PROTEINS)}, media_type="text/plain"
        )

    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots_txt(request: Request) -> str:
        return (
            "User-agent: *\n"
            "Allow: /api/\n"
            "Disallow: /*?\n"
            "Disallow: /middager\n"
            f"# For AI agents: read {request.base_url}llms.txt, then use the JSON API\n"
            f"Sitemap: {request.base_url}sitemap.xml\n"
        )

    @app.get("/sitemap.xml")
    def sitemap_xml(request: Request) -> Response:
        urls = "".join(f"<url><loc>{request.base_url}{page}</loc></url>" for page in PAGES)
        return Response(
            f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n',
            media_type="application/xml",
        )

    @app.get("/favicon.ico")
    @app.get("/favicon.svg")
    def favicon() -> FileResponse:
        return FileResponse(HERE / "static" / "icon.svg", media_type="image/svg+xml")

    @app.get("/helse", response_class=PlainTextResponse)
    def health() -> str:
        return "ok"

    return app


def _default() -> FastAPI:
    p = profile.load()
    return create_app(Queries(JsonDatasets(), p.household, p.week))


app = HeadAsGet(_default())
