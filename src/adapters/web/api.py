"""Read-only JSON API for agents and scripts, mounted at /api. The schema is at /api/openapi.json.

The same queries and the same shape as `matris --json` (src/adapters/schema.py).
"""

from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from adapters import schema
from adapters.web.params import KNOWN_PROTEINS, DinnerQuery
from app.queries import Queries

DESCRIPTION = """\
Dinner ideas from matprat.no that fit one household's diet (no onion, gluten-free, little lactose,
fit for small kids), ranked by this week's grocery offers in Stavanger from mattilbud.no.
Not an official source; recipes belong to matprat.no and offers to the stores.

Keys are English; advice and notes are bokmål. Prices are kroner. `protein` is the main protein group,
worked out from the heaviest meat or fish in the recipe. A dinner is `on_sale` when that protein
(or, without meat or fish, a main vegetable) has a before-price this week.
"""


def build(queries: Queries) -> FastAPI:
    api = FastAPI(title="matris.app", description=DESCRIPTION, version="1", docs_url=None, redoc_url=None, openapi_url=None)
    # Public, read-only data: any site or agent may call it
    api.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])

    @api.get("/openapi.json", include_in_schema=False)
    def openapi(request: Request) -> dict[str, object]:
        """The schema with an absolute server URL: ChatGPT actions refuse a relative one."""
        base = request.url.replace(path=request.url.path.removesuffix("/openapi.json"), query="")
        return {**api.openapi(), "servers": [{"url": str(base)}]}

    @api.get("/plan", response_model=schema.PlanOut, summary="This week's dinners")
    def plan() -> schema.PlanOut:
        """A varied week: one dinner per main protein (fish up to twice, never the same fish twice),
        picked from dinners whose main protein is on sale."""
        return schema.plan(queries, queries.plan())

    @api.get("/middager", response_model=schema.DinnersOut, summary="Dinners that fit, best first")
    def dinners(
        protein: Annotated[str | None, Query(description=f"One of: {', '.join(KNOWN_PROTEINS)}")] = None,
        tilbud: Annotated[str | None, Query(description="1: only dinners whose main protein is on sale")] = None,
        antall: Annotated[str | None, Query(description="How many, 1-100 (default 30)")] = None,
    ) -> schema.DinnersOut:
        """Fewest swaps first, then the biggest discount, then rating and prep time. At most 3 per
        main protein unless `protein` is given."""
        q = DinnerQuery.model_validate({k: v for k, v in {"protein": protein, "tilbud": tilbud, "antall": antall}.items() if v})
        return schema.dinners(queries, queries.dinners(q.protein, q.tilbud, limit=q.antall))

    @api.get("/oppskrift", response_model=schema.CheckOut, summary="How one recipe fits, with its ingredients")
    def recipe(url: Annotated[str, Query(description="A matprat.no recipe URL from `dinners[].url`")]) -> schema.CheckOut:
        found = queries.check(url)
        if found is None:
            raise HTTPException(404, f"No dinner at {url}")
        return schema.check(found)

    return api
