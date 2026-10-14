# matris

Dinner ideas from [matprat.no](https://www.matprat.no), with the week picked from dinners whose main protein is on sale ([mattilbud.no](https://mattilbud.no)). Diet rules (uten løk, glutenfri, lite laktose) are picked in the search, and the place in a select beside it. The site is at https://matris.app (in Norwegian).

Code: https://github.com/janbjorge/ukemeny. `profile.yaml` holds our household's rules and place for the CLI; the site and the build do not use it. FACTS.md says how everything works, METHOD.md every judgement call, TODO.md what is open.

## Run it

```sh
uv run matris plan                      # this week's dinners
uv run matris candidates --on-sale      # more ideas; also --protein fisk, --top 50
uv run matris candidates rask kylling uten sopp   # search in plain bokmål
uv run matris check <matprat-url>       # how one recipe fits
uv run uvicorn adapters.web.main:app    # the site on http://127.0.0.1:8000
```

Each read command takes `--json` for agents: one JSON document on stdout, errors as `{"error": {"kind", "message"}}` with exit code 1. The site's `/api` returns the same shape; `/llms.txt` and `/api/openapi.json` describe it.

## Rebuild the data (weekly)

```sh
export TYPESAFE_API_KEY=...             # https://console.typesafe.ai
uv run python -m pipeline.datasets      # datasets/ from scratch: matprat, offers, Jev
```

Then commit `datasets/` and push; a push to main deploys (.github/workflows/deploy.yml).

## Check

```sh
uvx ruff check . && uv run ty check src tests && uv run pytest -q
```
