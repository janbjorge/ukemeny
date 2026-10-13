# FACTS

Read this first on a cold start. Facts were checked on 2026-10-13 unless a section says otherwise. If this file and the code disagree, the code wins.

## 1. What this is

matris.app: dinner ideas from matprat.no that fit one household's diet, with the week picked from dinners whose main protein is on sale in Stavanger (mattilbud.no). jb's project, built on 2026-10-13, hosted on Fly.io at https://matris.app. The code is at https://github.com/janbjorge/ukemeny (jb 2026-10-13: `janbjorge/matris` is an older project); the app, the CLI and the Fly app are called matris.

- `/` is "Ukens middager": the week (five dinners, one per main protein, fish up to twice but never the same fish), the household's rules as chips, then "Flere forslag" with protein chips and an on-sale toggle. The chips and toggle load `/middager` as an HTMX fragment; without the `HX-Request` header it 303s to `/?protein=…&tilbud=1#forslag`, and with it the answer carries `HX-Replace-Url`, so the address bar is always a shareable link.
- `/om` ("Slik virker det") explains the rules, the offers and how ingredients were judged.
- For agents: `/llms.txt`, a read-only JSON API under `/api` (`/api/plan`, `/api/middager`, `/api/oppskrift?url=`) with its schema at `/api/openapi.json` (absolute server URL, built from the request), CORS open. Every HTML page links both in `<head>` and a `Link:` header. `/robots.txt` allows `/api/` and keeps crawlers off query strings and `/middager`; `/sitemap.xml` lists `/` and `/om`.
- The `matris` CLI (src/adapters/cli.py) reads the same snapshot: `plan`, `candidates`, `check URL`, each with `--json` (one document on stdout, errors as `{"error": {"kind", "message"}}`, exit 1); `build [--refresh]` runs the offline build; `profile` edits profile.yaml.
- Stack (as statsbudsjett): Python 3.14, FastAPI + uvicorn + Jinja + HTMX, no other JavaScript. pydantic v2 in the adapters, orjson for JSON.

## 2. Layout

- `src/core/`: the pure domain. models.py (types; `Dish` and `Part` are what the site keeps, `Snapshot` holds them), dishes.py (full recipe → `Dish`), diet.py (`judge`: does a dish fit a `Household`), matching.py (offer word filter, weights, `main_protein`), ranking.py (`dinners`, `plan`, `pick`, `varied`), ports.py, errors.py. Standard library only; tests/test_boundary.py enforces it.
- `src/app/queries.py`: read-only queries over the snapshot for the site, the API and the CLI. The ranking is worked out once at start-up.
- `src/app/build.py`: the offline use cases: `refresh` (recipes), `classify` (ingredients), `match` (offers), `snapshot`.
- `src/adapters/`: datasets.py (reads and writes `datasets/`, implements `core.ports.Datasets`), profile.py (profile.yaml with pydantic; also the list of grocery chains), schema.py (the JSON shape for API and CLI), cli.py, and `web/` (main.py, api.py, params.py for query strings, fmt.py for Norwegian numbers, templates, static).
- `src/pipeline/`: offline only, not in the Docker image. matprat.py, tjek.py, jev.py, store.py (SQLite caches), datasets.py (the composition root: `uv run python -m pipeline.datasets`).
- `profile.yaml`: the household (§5). `src/adapters/profile.example.yaml` is the template, identical today (tests/test_profile.py).

## 3. Sources

| What | Where | Read by |
|---|---|---|
| Recipes | https://www.matprat.no/sitemap.xml (4 479 recipe pages with `lastmod`), each page's `__NEXT_DATA__` | src/pipeline/matprat.py |
| Offers | Tjek's public API `https://squid-api.tjek.com/v2` (`/catalogs`, `/offers?catalog_ids=`), the service behind mattilbud.no. No key. | src/pipeline/tjek.py |

Site quirks:
- matprat's `__NEXT_DATA__` holds each ingredient's name, amount, unit and grocery department (`/kjøtt/kylling/høns`, `/melk/melkeprodukter`, `/glutenfritt`, `/melkefritt`), and `gtmDimensions.dimension8` = `Middagsrett` marks dinners (1 943 of 4 479). matprat's own main ingredient (`dimension1`) misfiles some dishes ("Kyllingfilet med spekeskinke" is Svin), so it is not used (METHOD.md §3).
- matprat's robots.txt disallows `/Services/` (its search API) and allows `/oppskrifter/`, so pages are read one by one: 3 at a time, half a second apart. The first full read took about 40 minutes.
- Tjek: one location search stops at 1 000 offers, so offers are read per catalog. A catalog's listed `offer_count` can differ from what `/offers` serves (KIWI listed 109, served 105), so the cache compares listing to listing.
- Tjek also lists furniture, hardware and electronics catalogs; "Spar Kjøp" is building supplies. Only the chains in `GROCERS` (src/adapters/profile.py) are read.
- Before-prices: Tjek's `pre_price` field, or "Førpris 34,90" / "Før 48,9" in the catalog text (mostly Joker). On 2026-10-13, discounted/all offers per chain: Bunnpris 0/161, Matkroken 0/10, Europris 36/152, Coop Mega 47/119, KIWI 27/105, Extra 28/103, REMA 1000 27/89, Joker 39/68, Obs 9/50, Coop Prix 10/45, MENY 11/35, Coop Marked 4/32, SPAR 14/28.
- Coop Mega prices some weighed goods per 100 g against a before-price per kg ("29,90 … Pr kg 299,00. Førpris 339,00 pr kg"), which read as 91 % off instead of 12 % (METHOD.md §4).

## 4. Data and the weekly build

- `datasets/` is committed and is all the site reads: dishes.json (1 943 dinners, 3.6 MB), traits.json (1 148 ingredient names, 0.2 MB), offers.json (`built`, 997 offers, and `matches`: per ingredient name the offer ids that are that ingredient; 159 names this week, 0.3 MB).
- A dish in dishes.json is facts, no rules (jb 2026-10-13: "there are loads of other constaints that might apply, so we can not have these attched to the dish"): name, URL, portions, prep time, rating, and per ingredient its name, matprat department, unit and grams per portion rounded to 5 g. No ingredient wording and no method: the repo is public and the recipes stay on matprat.no (docs/plan-web.md). Every rule (lactose, onion, main protein, discount weight) is worked out from these and the traits at runtime.
- `uv run python -m pipeline.datasets` (or `matris build`) rebuilds it; `--refresh` also re-reads matprat pages whose `lastmod` changed. It needs `TYPESAFE_API_KEY`. Commit and push afterwards to deploy.
- `data/` is gitignored: `data/matris.sqlite3` (recipes, Jev's ingredient traits, Jev's offer answers per ingredient and heading) and `data/tjek/<catalog>.json` (raw offers per catalog; a catalog does not change once published; ended catalogs are deleted). With warm caches a rebuild made 1 Tjek request for the catalog list and 29 Jev calls (2026-10-13).
- The site marks the offers as stale when the median offer end date has passed (src/app/queries.py `stale`).

## 5. The household and profile.yaml

- `diet`: onion, gluten, garlic each `avoid`, `note` or `ok`; `onion_substitute` (vårløk: fine for us and stands in for onion); `lactose` (grams per adult portion still fine, 3); `swaps` (false: only dinners needing no swap). `small_kids` (notes for chili and choking risks; no ages, since the repo is public). `shopping` (`lat`, `lng`, `radius_km`, `stores`). `week` (`dinners` 5, `fish` 2, `on_sale_only`).
- The site shows the rules as plain chips ("Uten løk (vårløk går fint)", "Glutenfritt", "Lite laktose (under 3 g per porsjon)", "Barnevennlig"), never why (src/app/queries.py `household_lines`).

## 6. Jev

- TypeSafe's Jev (typesafe_sdk, `jev-latest`, jev-1.13.0 on 2026-10-13), as in ezwork. Only the offline build calls it, at most 8 requests at a time.
- Ingredients: four Choices in one request (gluten yes/maybe/no, onion/garlic/maybe/none, lactose none/trace/some/high, kids ok/spicy/choking), with the ingredient name and its matprat department as state (src/pipeline/jev.py). Each name is asked once and cached.
- Offers: one yes/no question per offer heading, with the offer's text in the question, all in one request per ingredient. Each (ingredient, heading) pair is asked once and cached across weeks; an exact name match or a snack/pålegg heading is answered without asking (src/core/matching.py `obvious`).
- What the probes showed (METHOD.md §2 has the judgement calls): Norwegian examples in the criteria fixed purre, risnudler, tamari and matfløte; the department fixed 28 of 36 wrong answers on rarer words; a single Choice over offers dropped right answers, and questions pointing at `offers[i]` mixed offers up.
- Cost: the first full classification and matching of 1 943 dinners was 1 503 calls, about 1.8 M input tokens, $0.074. A weekly rebuild with warm caches was 29 calls.
- Known wrong answers still in traits.json: hurtigris, malt allehånde and frossen lapskausblanding as gluten; gulbete and strutsevingknopper as onion.

## 7. Hosting

- Dockerfile: python:3.14-slim plus uv, runtime dependencies only, no `src/pipeline/`, runs as `nobody`. The image is 406 MB and the app used 67 MiB of memory locally (2026-10-13). fly.toml: app `matris`, region arn, health check /helse, machines stop when idle, shared-cpu-1x with 256 MB.
- The app adds gzip, security headers and cache headers itself (src/adapters/web/main.py `headers`): hashed static files are immutable, pages 5 minutes. HEAD is answered like GET.
- When `CANONICAL_HOST` is set (to matris.app), every other host name 301s to it, except /helse. Nothing else in the code names the host.
- Pushes to main run ruff, ty and pytest and then `flyctl deploy` (.github/workflows/deploy.yml). The FLY_API_TOKEN secret is a deploy token for `matris` named github-actions-ukemeny (2026-10-13); the first run via Actions released v2. Fly's own GitHub integration is not used, since it would deploy a second time and skip the checks.
- Deployed 2026-10-13 to https://matris.fly.dev (Fly app `matris`, org personal, one machine in arn). IPs: shared IPv4 66.241.124.233, dedicated IPv6 2a09:8280:1::1b4:b71b:0. A certificate for matris.app is requested; it needs `A matris.app → 66.241.124.233` and `AAAA matris.app → 2a09:8280:1::1b4:b71b:0` at the registrar (DNS at ns1/ns2.hyp.net; matris.app pointed at 66.241.125.158 on 2026-10-13). `CANONICAL_HOST` is not set yet.
