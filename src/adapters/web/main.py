"""FastAPI + Jinja + HTMX. Every fragment is also reachable as a full page via the same query string."""

import hashlib
import os
import threading
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qs, urlsplit

import logfire
from fastapi import FastAPI, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from adapters.datasets import JsonDatasets
from adapters.web import api, fmt, telemetry
from adapters.web.params import KNOWN_PROTEINS, DinnerQuery, link, new_seed, offset, seed
from app.queries import Found, Queries
from core.matching import VEGETARIAN
from core.search import (
    ORDER_LABELS,
    Diet,
    Kind,
    Order,
    Tag,
    diet_clause,
    marked,
    protein_clause,
    protein_word,
    tag_clause,
)

HERE = Path(__file__).parent
# The one public address (matris.app). Set on Fly once the certificate and DNS are live; every other
# host name, such as matris.fly.dev or www., then redirects here. Unset locally and in tests.
CANONICAL_HOST = os.environ.get("CANONICAL_HOST", "")
# On every page, for agents: the llms.txt guide and the API schema (service-desc, RFC 8631)
LINK = '</llms.txt>; rel="alternate"; type="text/markdown", </api/openapi.json>; rel="service-desc"; type="application/json"'
# The pages a crawler should index; the query-string variants and fragments stay out (see robots_txt)
PAGES = ("", "om")

# The chips above the ideas: the diet rules and allergies a visitor picks (none to start with), then what a dinner is like
DIET_CHIPS = (
    Diet.VEGETARIAN,
    Diet.VEGAN,
    Diet.PESCETARIAN,
    Diet.GLUTEN,
    Diet.MILK,
    Diet.LACTOSE,
    Diet.ONION,
    Diet.GARLIC,
    Diet.FODMAP,
    Diet.LOW_CARB,
    Diet.PORK,
    Diet.ALCOHOL,
    Diet.PREGNANT,
)
ALLERGY_CHIPS = (
    Diet.EGG,
    Diet.FISH,
    Diet.CRUSTACEAN,
    Diet.MOLLUSC,
    Diet.TREE_NUT,
    Diet.PEANUT,
    Diet.SOY,
    Diet.SESAME,
    Diet.CELERY,
    Diet.MUSTARD,
    Diet.SULPHITE,
    Diet.LUPIN,
    Diet.LEGUME,
)
KIND_CHIPS = (Tag.QUICK, Tag.UNDER_40, Tag.ON_SALE, Tag.LIKED, Tag.MILD)
# The elements whose own answer must not replace the search box: the box and its form send what was typed, and «Sted»
# and «Nye middager» (#ny-uke) leave the text as it is
KEEP_BOX = {"q", "sok", "sted", "ny-uke"}
# Ideas per page and per "Vis flere": a phone screen holds one or two cards
PAGE = 12
# Rendered fragments kept, newest last: the snapshot does not change while the process runs, so a search someone
# already made (a chip, a combination) is answered without rendering again
FRAGMENTS = 512
# Pages may be cached this long. Not stale-while-revalidate: a browser then showed the page from before a deploy
PAGE_CACHE = "public, max-age=300"
# Not the front page: its week is drawn anew on every visit (jb 2026-10-14)
FRONT_CACHE = "no-cache"

type Q = Annotated[str | None, Query()]


@dataclass(frozen=True, slots=True)
class Chip:
    label: str
    text: str
    """The search after a click: the chip toggled."""
    on: bool
    count: int | None
    """Dinners after a click, for a chip that is off."""
    order: Order | None
    """The sort after a click: the one now, but for a sort chip, which toggles it."""
    protein: str = ""


def chips(found: Found) -> dict[str, list[Chip]]:
    s, order = found.search, found.order

    def tag(t: Tag) -> Chip:
        clause = tag_clause(t)
        on = s.has(clause)
        return Chip(clause.label, s.toggle(clause).text, on, None if on else found.counts.tags[t], order)

    def diet(d: Diet) -> Chip:
        clause = diet_clause(d)
        return Chip(clause.label, s.toggle(clause).text, s.has(clause), None, order)

    chosen = next((c for c in s.clauses if c.kind is Kind.PROTEIN), None)
    every = sum(found.counts.proteins.values())
    proteins = [Chip("Alle", s.drop(chosen).text if chosen else s.text, chosen is None, every if chosen else None, order)]
    for p in KNOWN_PROTEINS:
        if p == VEGETARIAN:
            continue  # «Vegetar» is a rule in Kosthold: no meat or fish in any ingredient, not just the main one
        if n := found.counts.proteins.get(p):
            clause = protein_clause(protein_word(p))
            on = chosen is not None and chosen.values == (p,)
            proteins.append(Chip(protein_word(p).capitalize(), s.toggle(clause).text, on, None if on else n, order, p))

    # On or off, neither on is the ranking (jb 2026-10-14: no «Anbefalt», "makes no sense")
    orders = [Chip(ORDER_LABELS[o], s.text, order is o, None, None if order is o else o) for o in Order]

    def on_first(row: list[Chip]) -> list[Chip]:
        """Chosen chips lead their row, so a phone, which shows a row as one line to swipe, shows them."""
        return sorted(row, key=lambda c: not c.on)

    return {
        "diets": on_first([diet(d) for d in DIET_CHIPS]),
        "allergies": on_first([diet(d) for d in ALLERGY_CHIPS]),
        "kinds": on_first([tag(t) for t in KIND_CHIPS]),
        "proteins": on_first(proteins),
        "orders": orders,
    }


class HeadAsGet:
    """Answer HEAD like GET without the body. Routes only take GET; link checkers and preview bots send HEAD."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "HEAD":
            return await self.app(scope, receive, send)

        async def headers_only(message: Message) -> None:
            await send({**message, "body": b""} if message["type"] == "http.response.body" else message)

        await self.app({**scope, "method": "GET", telemetry.HEAD: True}, receive, headers_only)


# Content hash per static file, read once at start-up: the image is rebuilt for every change
STATIC_HASHES = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:10] for p in (HERE / "static").iterdir() if p.is_file()}


def static_url(name: str) -> str:
    return f"/static/{name}?v={STATIC_HASHES[name]}"


# The stylesheet goes inline in every page: about 3 kB gzipped, and no request blocks the first paint
STYLE = Markup((HERE / "static" / "app.css").read_text())


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
                response.headers["Cache-Control"] = FRONT_CACHE if path == "/" else PAGE_CACHE
        return response

    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    @app.get("/api", include_in_schema=False)
    def api_root() -> RedirectResponse:
        """The API is its schema; /api/ (with the slash) does the same inside the API app."""
        return RedirectResponse("/api/openapi.json", status_code=302)

    app.mount("/api", api.build(queries))

    def context(request: Request) -> dict[str, object]:
        """Names every template can use."""
        return {
            "static_url": static_url,
            "style": STYLE,
            "canonical": f"https://{CANONICAL_HOST}{request.url.path}" if CANONICAL_HOST else "",
            "built": queries.snapshot.built,
            "offers_until": queries.offers_until(),
            "stale": queries.stale(date.today()),
            "link": link,
            "marked": marked,
            "page": PAGE,
        }

    templates = Jinja2Templates(directory=HERE / "templates", context_processors=[context])
    templates.env.filters |= {name: getattr(fmt, name) for name in fmt.__all__}

    def ideas(request: Request, choice: DinnerQuery, count: int, week: int) -> Found:
        """The list under the week the visit drew (`week`, its seed), which it leaves out when only rules are searched for."""
        place = queries.place(choice.sted)
        return telemetry.search(queries, choice.text(), place, choice.sorter, request.url.path, limit=count, skip_week=True, seed=week)

    def drawn(found: Found) -> bool:
        """Does the list depend on the visit's week? Only when it leaves it out: nothing but rules searched for."""
        return all(c.kind is Kind.DIET for c in found.search.clauses)

    def visit(uke: str | None) -> tuple[int, bool]:
        """The visit's draw of the week (`uke`), and whether it is new: none came with the request (a first visit, or
        «Nye middager», which leaves it out)."""
        given = seed(uke)
        return (new_seed(), True) if given is None else (given, False)

    rendered: OrderedDict[tuple[object, ...], bytes] = OrderedDict()

    def fragment(
        request: Request, template: str, key: tuple[object, ...], context: Callable[[], dict[str, object]], keep: bool = True
    ) -> Response:
        """An HTMX fragment, rendered once per key and kept (FRAGMENTS); with `keep` off, rendered every time: it holds
        one visit's draw of the week."""
        key = (template, *key)
        telemetry.fragment(template, kept=keep and key in rendered)
        if keep and key in rendered:
            rendered.move_to_end(key)
            return HTMLResponse(rendered[key])
        body = bytes(templates.TemplateResponse(request, template, context()).body)
        if keep:
            rendered[key] = body
            if len(rendered) > FRAGMENTS:
                rendered.popitem(last=False)
        return HTMLResponse(body)

    def rules_changed(found: Found, current_url: str | None) -> bool:
        """Did this search change the diet rules or the place from the page's? htmx sends the page's address
        (HX-Current-URL)."""
        if not current_url:
            return True
        before = DinnerQuery.of(
            **{k: v[0] for k, v in parse_qs(urlsplit(current_url).query).items() if k in ("q", "protein", "tilbud", "sted")}
        )
        return queries.rules(queries.parse(before.text()), queries.place(before.sted)) != (found.household, found.place)

    def dinner_context(
        found: Found,
        week: int,
        fresh: bool = False,
        fragment: bool = False,
        trigger: str | None = None,
        current_url: str | None = None,
    ) -> dict[str, object]:
        return {
            "found": found,
            # The visit's draw of the week, sent back with every search from the page (#uke)
            "seed": week,
            "chips": chips(found),
            "relax": [(c, n, found.search.drop(c).text) for c, n in found.relax],
            "shown": len(found.dinners),
            "week": queries.plan(found.household, found.place, week),
            # «Sted»: where the offers are from, every store until one is picked (jb 2026-10-14: "I dont want location to
            # be in the seach, make it some kind of select")
            "places": sorted(queries.snapshot.places),
            # A fragment also sends the week when the diet rules changed (the week follows them) or it was drawn anew, with
            # its #uke, and, when a chip or a link changed the search rather than typing, the search box with its new text
            # (all out of band)
            "week_oob": fragment and (fresh or rules_changed(found, current_url)),
            "uke_oob": fragment and fresh,
            "box": fragment and trigger not in KEEP_BOX,
        }

    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        q: Q = None,
        protein: Q = None,
        tilbud: Q = None,
        antall: Q = None,
        sted: Q = None,
        sorter: Q = None,
        uke: Q = None,
    ) -> HTMLResponse:
        choice, (week, _) = DinnerQuery.of(q=q, protein=protein, tilbud=tilbud, antall=antall, sted=sted, sorter=sorter), visit(uke)
        found = ideas(request, choice, choice.antall if antall else PAGE, week)
        return templates.TemplateResponse(request, "index.html", dinner_context(found, week))

    @app.get("/middager", response_class=HTMLResponse)
    def dinners_fragment(
        request: Request,
        q: Q = None,
        protein: Q = None,
        tilbud: Q = None,
        antall: Q = None,
        sted: Q = None,
        sorter: Q = None,
        uke: Q = None,
    ) -> Response:
        """The ideas under the week, for a search. Without HTMX it is the front page with the same search."""
        choice = DinnerQuery.of(q=q, protein=protein, tilbud=tilbud, antall=antall, sted=sted, sorter=sorter)
        if "hx-request" not in request.headers:
            query = link(choice.text(), choice.antall if antall else None, queries.place(choice.sted), choice.sorter)
            return RedirectResponse(f"/?{query}#forslag" if query else "/#forslag", status_code=303)
        drew, fresh = visit(uke)
        found = ideas(request, choice, choice.antall if antall else PAGE, drew)
        trigger, current_url = request.headers.get("hx-trigger"), request.headers.get("hx-current-url")
        week, box = fresh or rules_changed(found, current_url), trigger not in KEEP_BOX
        response = fragment(
            request,
            "_dinners.html",
            (found.search.text, found.place, found.order, len(found.dinners), box),
            lambda: dinner_context(found, drew, fresh, fragment=True, trigger=trigger, current_url=current_url),
            keep=not (week or drawn(found)),
        )
        query = link(found.search.text, place=found.place, order=found.order)
        response.headers["HX-Replace-Url"] = f"/?{query}#forslag" if query else "/#forslag"
        return response

    @app.get("/middager/flere", response_class=HTMLResponse)
    def more_dinners(
        request: Request,
        q: Q = None,
        protein: Q = None,
        tilbud: Q = None,
        sted: Q = None,
        sorter: Q = None,
        uke: Q = None,
        fra: Q = None,
    ) -> Response:
        """The next ideas after the first `fra`, to append to the list. Without HTMX, the front page with them all."""
        choice, start = DinnerQuery.of(q=q, protein=protein, tilbud=tilbud, sted=sted, sorter=sorter), offset(fra)
        if "hx-request" not in request.headers:
            query = link(choice.text(), start + PAGE, queries.place(choice.sted), choice.sorter)
            return RedirectResponse(f"/?{query}#forslag", status_code=303)
        found = ideas(request, choice, start + PAGE, visit(uke)[0])
        return fragment(
            request,
            "_more.html",
            (found.search.text, found.place, found.order, start),
            lambda: {"found": found, "start": start, "shown": len(found.dinners)},
            keep=not drawn(found),
        )

    @app.get("/om", response_class=HTMLResponse)
    def about(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "om.html", {"places": sorted(queries.snapshot.places)})

    @app.get("/llms.txt", response_class=PlainTextResponse)
    def llms_txt(request: Request) -> Response:
        """Entry point for AI agents (llmstxt.org): what the site is and the JSON API."""
        return templates.TemplateResponse(
            request,
            "llms.txt",
            {
                "base": str(request.base_url),
                "proteins": ", ".join(KNOWN_PROTEINS),
                "diets": api.DIETS,
                "rule_links": [(d.value, f"{request.base_url}api/plan?{link(d.value)}") for d in Diet],
                "place_links": [(p, f"{request.base_url}api/plan?{link('', place=p)}") for p in queries.snapshot.places],
            },
            media_type="text/plain",
        )

    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots_txt(request: Request) -> str:
        # Agents that fetch for a person in a chat may open everything, searches included (ChatGPT read llms.txt and
        # never reached the API; `Disallow: /*?` may have stopped it, jb 2026-10-13). Crawlers keep off query strings.
        return (
            "User-agent: ChatGPT-User\n"
            "User-agent: Claude-User\n"
            "User-agent: Perplexity-User\n"
            "Allow: /\n"
            "\n"
            "User-agent: *\n"
            "Allow: /api/\n"
            # Not `/*?`: some parsers (Python's) let that wildcard outrank `Allow: /api/`, closing the API's searches too
            "Disallow: /?\n"
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

    @app.get("/manifest.webmanifest")
    def manifest() -> JSONResponse:
        """For "Legg til på Hjem-skjerm": the site opens like an app, with its own icon."""
        icons = [{"src": static_url(f"icon-{n}.png"), "sizes": f"{n}x{n}", "type": "image/png"} for n in (192, 512)]
        return JSONResponse(
            {
                "name": "matris: ukens middager",
                "short_name": "matris",
                "lang": "nb",
                "start_url": "/",
                "scope": "/",
                "display": "standalone",
                "background_color": "#fffaf3",
                "theme_color": "#ffffff",
                "icons": icons,
            },
            media_type="application/manifest+json",
        )

    @app.get("/apple-touch-icon.png")
    @app.get("/apple-touch-icon-precomposed.png")
    def apple_touch_icon() -> FileResponse:
        """iPhones ask for these at the root, whatever the page links."""
        return FileResponse(HERE / "static" / "apple-touch-icon.png", media_type="image/png")

    @app.get("/favicon.ico")
    @app.get("/favicon.svg")
    def favicon() -> FileResponse:
        return FileResponse(HERE / "static" / "icon.svg", media_type="image/svg+xml")

    @app.get("/helse", response_class=PlainTextResponse)
    def health() -> str:
        return "ok"

    return app


def _default() -> FastAPI:
    telemetry.configure()
    with logfire.span("start-up"):
        # No profile: the site starts with no diet rules, and a visitor picks them in the search
        queries = Queries(JsonDatasets())
        app = create_app(queries)
    telemetry.instrument(app, queries)

    def warm() -> None:
        with logfire.span("warm the diet rules"):
            queries.warm()

    # Each rule's ranking and week, worked out after start-up, so a first tap on a chip finds them ready
    threading.Thread(target=warm, name="warm", daemon=True).start()
    return app


app = HeadAsGet(_default())
