"""Tracing, metrics and logs with Logfire. Sends only when LOGFIRE_TOKEN is set, so local runs and tests stay offline.

Everything the process on Fly can see (jb 2026-10-13: "make sure we get every insight metric we can into logfire"):
every request as a span with its URL, its headers and the response's, and the edge region Fly took it in
(`Fly-Region`); each search, what it understood and what it found; start-up, the first request after a machine
boots, and the stop; CPU (steal too), memory, network, garbage collection and Linux pressure stall time.
Fly's own metrics (edge latency, CPU throttling, OOM kills) need a collector outside the app, which jb left out.

The visitor's address is never recorded: the client attributes are blanked as the span starts, and the headers
that carry it are redacted before they become attributes. Query strings are kept as they are (as in statsbudsjett).
"""

import logging
import os
import sys
import time
from collections.abc import AsyncGenerator, Iterable, Mapping
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import logfire
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.jinja2 import Jinja2Instrumentor
from opentelemetry.metrics import CallbackOptions, Observation
from starlette.types import Scope

from app.queries import Found, Queries
from core.search import Search

ON_FLY = "FLY_APP_NAME" in os.environ
# The commit, passed by the deploy job (Dockerfile): the service version, and links from a span to its code
GIT_SHA = os.environ.get("GIT_SHA", "")
REDACTED = "x"
# OpenTelemetry ASGI attributes that hold the visitor's address, old and new semantic conventions
CLIENT_ATTRS = ("net.peer.ip", "client.address", "client.socket.address", "net.sock.peer.addr", "http.client_ip")
# Headers whose values are redacted before they are attributes: the visitor's address (Fly-Client-IP,
# X-Forwarded-For), the referring page's path (its host is `visit.referrer`) and credentials. Regexes, any case
HIDDEN_HEADERS = ["client-ip", "forwarded-for", "^forwarded$", "real-ip", "connecting-ip", "^referer$", "cookie", "authorization"]
# What Fly tells a machine about itself (https://docs.fly.io/machines/runtime-environment), as resource attributes
FLY_ENV = {
    "FLY_APP_NAME": "fly.app.name",
    "FLY_MACHINE_ID": "fly.machine.id",
    "FLY_MACHINE_VERSION": "fly.machine.version",
    "FLY_REGION": "fly.region",
    "PRIMARY_REGION": "fly.primary_region",
    "FLY_IMAGE_REF": "fly.image.ref",
    "FLY_PROCESS_GROUP": "fly.process_group",
    "FLY_VM_MEMORY_MB": "fly.vm.memory_mb",
}
# Linux pressure stall information: how long tasks waited for CPU, memory or I/O
PRESSURE = Path("/proc/pressure")
# The ASGI scope key HeadAsGet (main.py) sets when it answers a HEAD as a GET
HEAD = "matris.head"

_searches = logfire.metric_counter("matris.searches", unit="{search}", description="Searches by route, and whether any dinner matched")
_rules = logfire.metric_counter("matris.search.rules", unit="{search}", description="Searches naming each diet rule or allergy")
_clauses = logfire.metric_counter("matris.search.clauses", unit="{clause}", description="What searches are made of, by kind")
_results = logfire.metric_histogram("matris.search.results", unit="{dinner}", description="Dinners that match a search")
_fragments = logfire.metric_counter("matris.fragments", unit="{fragment}", description="HTMX fragments, rendered or kept from before")
_served = 0
"""Requests this process has traced."""


def _since_boot() -> tuple[float, float] | None:
    """Seconds since the machine booted: now, and when this process started. On Fly a stopped machine boots again
    for the next visit, so this is how long that visit waited. Linux only."""
    if sys.platform != "linux":
        return None
    stat = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()
    return time.clock_gettime(time.CLOCK_BOOTTIME), int(stat[19]) / os.sysconf("SC_CLK_TCK")


def _visit(scope: Scope) -> dict[str, str]:
    """Where a visit came from: the referring site's host (never its path), how the browser got here, and the
    campaign tags and click id name in the link."""
    headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
    query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    visit: dict[str, str] = {}
    referrer = urlsplit(headers.get("referer", "")).hostname
    if referrer and referrer != urlsplit(f"//{headers.get('host', '')}").hostname:
        visit["visit.referrer"] = referrer
    # "none" means typed, bookmarked or opened from an app such as a mail client; "cross-site" means a link elsewhere
    if site := headers.get("sec-fetch-site"):
        visit["visit.fetch_site"] = site
    for key, values in query.items():
        if key.startswith("utm_"):
            visit[f"visit.{key}"] = values[0]
    # Ad and social platforms append a click id parameter ending in "clid"; its name says which one, its value nothing
    if click := next((key for key in query if key.endswith("clid")), None):
        visit["visit.click_id"] = click
    return visit


def _on_request(span: trace.Span, scope: Scope) -> None:
    """Runs when the request span starts, before anything is exported."""
    global _served
    if not span.is_recording():
        return
    attributes = getattr(span, "attributes", None)
    if isinstance(attributes, Mapping):
        span.set_attributes({key: REDACTED for key in CLIENT_ATTRS if key in attributes})
    span.set_attributes(_visit(scope))
    if scope.get(HEAD):
        span.set_attribute("http.request.method_original", "HEAD")
    # 0 is the first request since start-up: on Fly, most likely the visit that woke the machine
    span.set_attribute("process.served", _served)
    if boot := _since_boot():
        now, started = boot
        span.set_attribute("process.uptime", round(now - started, 3))
        if _served == 0:
            span.set_attribute("startup.boot_to_first_request", round(now, 3))
    _served += 1


def _pressure(options: CallbackOptions) -> Iterable[Observation]:
    """Seconds tasks stalled for each resource, since boot: "some" when at least one task waited, "full" when all did."""
    for resource in ("cpu", "memory", "io"):
        for line in (PRESSURE / resource).read_text().splitlines():
            level, *fields = line.split()
            total = next(f for f in fields if f.startswith("total="))
            yield Observation(int(total.removeprefix("total=")) / 1e6, {"resource": resource, "level": level})


def configure() -> None:
    """Before anything else at start-up, so start-up itself is traced."""
    fly = {attr: os.environ[env] for env, attr in FLY_ENV.items() if env in os.environ}
    if ON_FLY:
        fly |= {"cloud.provider": "fly_io", "cloud.region": fly.get("fly.region", ""), "host.id": fly.get("fly.machine.id", "")}
    logfire.configure(
        send_to_logfire="if-token-present",
        service_name="matris",
        service_version=GIT_SHA or "dev",
        environment="production" if ON_FLY else "local",
        resource_attributes=fly,
        console=False,
        # Public site with no upstream services: ignore trace headers that visitors send
        distributed_tracing=False,
        code_source=logfire.CodeSource(repository="https://github.com/janbjorge/ukemeny", revision=GIT_SHA or "main"),
        # Counters and histograms recorded during a span are added up on it too
        metrics=logfire.MetricsOptions(collect_in_spans=True),
        # A log at start-up with the installed package versions, and the process's command and owner on every span
        advanced=logfire.AdvancedOptions(emit_configuration_span=True, resource_detectors=["process"]),
    )
    # uvicorn's own logs (start, stop, errors) and Python warnings; uvicorn's logger does not pass records on to the root
    handler = logfire.LogfireLoggingHandler()
    for name in ("", "uvicorn"):
        logging.getLogger(name).addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    logging.captureWarnings(True)
    # A warning when something holds the event loop for 100 ms; the routes run in threads, so this should stay quiet
    logfire.log_slow_async_callbacks(slow_duration=0.1)
    # A span per template rendered
    Jinja2Instrumentor().instrument()
    if ON_FLY:
        # The machine is a Firecracker VM, so these are its own: CPU per state (steal is time the host gave to others),
        # memory, swap, disk, network, and the process's CPU, memory, threads, file descriptors and garbage collection
        logfire.instrument_system_metrics(base="full")
    if PRESSURE.is_dir():
        logfire.metric_counter_callback(
            "system.linux.pressure.stall_time", callbacks=[_pressure], unit="s", description="Time tasks waited for CPU, memory or I/O"
        )


def instrument(app: FastAPI, queries: Queries) -> None:
    logfire.instrument_fastapi(
        app,
        # Fly's health check, every 30 s
        excluded_urls="/helse",
        # Spans for reading the arguments and for the route itself, apart from the middleware
        extra_spans=True,
        # Debug spans for the response's start and body
        record_send_receive=True,
        server_request_hook=_on_request,
        http_capture_headers_server_request=[".*"],
        http_capture_headers_server_response=[".*"],
        http_capture_headers_sanitize_fields=HIDDEN_HEADERS,
    )
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Logs when the app is ready and when it stops. Fly stops an idle machine with SIGINT and kills it 5 s later
        (kill_timeout); uvicorn then raises the signal again, so what is queued is sent here, not left to atexit."""
        async with inner(app):
            _ready(queries)
            yield
        logfire.info("stopping after {uptime} s and {served} requests", uptime=_uptime(), served=_served)
        logfire.force_flush(timeout_millis=3000)

    app.router.lifespan_context = lifespan

    def age(options: CallbackOptions) -> Iterable[Observation]:
        yield Observation((date.today() - queries.snapshot.built.date()).days)

    def left(options: CallbackOptions) -> Iterable[Observation]:
        if until := queries.offers_until():
            yield Observation((until - date.today()).days)

    logfire.metric_gauge_callback("matris.dataset.age", callbacks=[age], unit="d", description="Days since datasets/ was built")
    logfire.metric_gauge_callback(
        "matris.offers.left", callbacks=[left], unit="d", description="Days until most of the week's offers end; below 0 they are old"
    )


def _uptime() -> float | None:
    boot = _since_boot()
    return round(boot[0] - boot[1], 3) if boot else None


def _ready(queries: Queries) -> None:
    s = queries.snapshot
    attributes: dict[str, object] = {
        "dataset.built": s.built.isoformat(),
        "dataset.dishes": len(s.dishes),
        "dataset.offers": len(s.offers),
        "offers.until": str(queries.offers_until()),
        "offers.stale": queries.stale(date.today()),
    }
    if boot := _since_boot():
        now, started = boot
        attributes |= {"startup.boot_to_ready": round(now, 3), "startup.process_to_ready": round(now - started, 3)}
    logfire.log("info", "ready", attributes)


def search(queries: Queries, text: str, route: str, limit: int, skip_week: bool = False) -> Found:
    """queries.search in a span that says what it understood and found, and counted."""
    with logfire.span("search {text}", text=text, route=route, limit=limit) as span:
        found = queries.search(text, limit=limit, skip_week=skip_week)
        s = found.search
        span.set_attributes(
            {
                "search.understood": s.text,
                "search.clauses": [c.label for c in s.clauses],
                "search.rules": sorted(d.value for d in s.diets),
                "search.corrected": [f"{typed} → {used}" for typed, used in s.corrected],
                "search.total": found.total,
                "search.shown": len(found.dinners),
                "search.relax": [c.label for c, _ in found.relax],
            }
        )
    counted(s, route, found.total)
    return found


def counted(search: Search, route: str, total: int | None = None) -> None:
    """Counts a search per route, diet rule and kind of clause. Not its words: each would be a series of its own."""
    _searches.add(1, {"route": route, "found": total != 0})
    for diet in search.diets:
        _rules.add(1, {"rule": diet.value, "route": route})
    for clause in search.clauses:
        _clauses.add(1, {"kind": clause.kind.value, "route": route})
    if total is not None:
        _results.record(total, {"route": route})


def fragment(template: str, kept: bool) -> None:
    """An HTMX fragment answered: rendered now, or kept from an earlier request (main.FRAGMENTS)."""
    trace.get_current_span().set_attribute("fragment.kept", kept)
    _fragments.add(1, {"template": template, "kept": kept})
