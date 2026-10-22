"""Read-only JSON API for agents and scripts, mounted at /api. The schema is at /api/openapi.json.

The same queries and the same shape as `matris --json` (src/adapters/schema.py).
"""

from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from adapters import schema
from adapters.web import telemetry
from adapters.web.params import KNOWN_PROTEINS, DinnerQuery
from app.queries import Queries
from core.search import Diet

DIETS = ", ".join(f"`{d}`" for d in Diet)
"""Every diet rule and allergy a search can name."""

DESCRIPTION = f"""\
Dinner ideas from matprat.no and godt.no, ranked by this week's grocery offers from mattilbud.no, searchable
in plain bokmål (`q`). No diet rule applies unless `q` names one: {DIETS}. A rule that leaves something out
(vegetar, melkefri, uten egg, ...) also leaves out dinners with an ingredient that may hold it, such as a stock cube.
The offers are from stores all over Norway until `sted` names a place (`sted=bergen`); then from the stores near it.
`place` says which, and `links.places` gives the same answer in each place.
Not an official source; recipes belong to matprat.no and godt.no, and offers to the stores.

Keys are English; advice is bokmål. Prices are kroner. `protein` is the main protein group,
worked out from the heaviest meat or fish in the recipe. A dinner is `on_sale` when that protein
(or, without meat or fish, a main vegetable) has a before-price this week.
"""


SEARCH = f"""A search in plain bokmål, such as `rask kylling uten sopp`, `laks eller torsk på tilbud` or `glutenfri pasta`.
Understood: diet rules and allergies ({DIETS}: which dinners fit and what to swap), categories
(`under 20 min`, `under 40 min`, `under en time`, `på tilbud`, `godt likt`, `barnevennlig`), main proteins (`kylling`,
`fisk`, `kjøtt`, `sjømat`, ...), `uten`/`ikke` before a word to leave it out, and `eller` between words for either.
The place is not a word in `q`: it is `sted`.
Any other word must be in the dish name or an ingredient; a word that matches nothing is swapped for the closest known
one (see `search.corrected`). æøå may be written as ae/o/a."""


def build(queries: Queries) -> FastAPI:
    api = FastAPI(title="matris.app", description=DESCRIPTION, version="1", docs_url=None, redoc_url=None, openapi_url=None)
    # Public, read-only data: any site or agent may call it
    api.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])
    near = Query(
        description=f"Where the offers are from: the stores near one of {', '.join(sorted(queries.snapshot.places))} (any case). "
        "Left out: every store."
    )

    @api.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/api/openapi.json", status_code=302)

    @api.get("/openapi.json", include_in_schema=False)
    def openapi(request: Request) -> dict[str, object]:
        """The schema with an absolute server URL: ChatGPT actions refuse a relative one."""
        base = request.url.replace(path=request.url.path.removesuffix("/openapi.json"), query="")
        return {**api.openapi(), "servers": [{"url": str(base)}]}

    def base(request: Request) -> str:
        """This API's address, ending in "/", for the links in an answer."""
        return str(request.url.replace(path=request.url.path.rsplit("/", 1)[0] + "/", query=""))

    @api.get("/plan", response_model=schema.PlanOut, summary="This week's dinners")
    def plan(
        request: Request,
        q: Annotated[str | None, Query(description=f"Diet rules and allergies: {DIETS}")] = None,
        sted: Annotated[str | None, near] = None,
    ) -> schema.PlanOut:
        """A varied week: one dinner per main protein (fish up to twice, never the same fish twice), drawn anew on
        each call from the dinners on sale with the most kroner off, the more off the likelier. `links` adds or takes
        away a diet rule, or picks a place."""
        search, place = queries.parse(q or ""), queries.place(sted)
        telemetry.counted(search, place, request.url.path)
        return schema.plan(queries, queries.plan(*queries.rules(search, place)), search, base(request))

    @api.get("/middager", response_model=schema.DinnersOut, summary="Search the dinners that fit, best first")
    def dinners(
        request: Request,
        q: Annotated[str | None, Query(description=SEARCH)] = None,
        protein: Annotated[str | None, Query(description=f"One of: {', '.join(KNOWN_PROTEINS)}. Same as the word in `q`.")] = None,
        tilbud: Annotated[
            str | None, Query(description="1: only dinners whose main protein is on sale. Same as `på tilbud` in `q`.")
        ] = None,
        antall: Annotated[str | None, Query(description="How many, 1-100 (default 30)")] = None,
        sted: Annotated[str | None, near] = None,
    ) -> schema.DinnersOut:
        """Dinners whose name has a searched word first, then fewest swaps, the most kroner off (every discounted
        ingredient summed, `discounts`), rating and prep time. Without a protein or a word to find, the best 3 of each
        main protein come first. `search` says how `q` was understood, and `links` adds or takes away a diet rule, or picks a place."""
        choice = DinnerQuery.of(q=q, protein=protein, tilbud=tilbud, antall=antall, sted=sted)
        place = queries.place(choice.sted)
        found = telemetry.search(queries, choice.text(), place, request.url.path, limit=choice.antall)
        return schema.dinners(queries, found, base(request))

    @api.get("/oppskrift", response_model=schema.CheckOut, summary="Whether one recipe fits, and what to swap")
    def recipe(
        url: Annotated[str, Query(description="A matprat.no or godt.no recipe URL from `dinners[].url`")],
        q: Annotated[str | None, Query(description=f"Diet rules and allergies to check against: {DIETS}")] = None,
    ) -> schema.CheckOut:
        found = queries.check(url, queries.household(q or ""))
        if found is None:
            raise HTTPException(404, f"No dinner at {url}")
        return schema.check(found)

    return api
