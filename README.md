# matris

Dinner ideas from [matprat.no](https://www.matprat.no) and [godt.no](https://www.godt.no) with ingredient on sale this week ([mattilbud.no](https://mattilbud.no)), most kroner off first. Diet rules (uten løk, glutenfri, lite laktose) picked in search, place in select beside it. Site at https://matris.app (Norwegian).

Code: https://github.com/janbjorge/ukemeny. `profile.yaml` = household rules + place for CLI; site and build ignore it. FACTS.md: how everything works. METHOD.md: every judgement call. TODO.md: what open.

## Run it

```sh
uv run matris candidates                # the dinners that save most; also --on-sale, --protein fisk, --top 50
uv run matris candidates rask kylling uten sopp   # search in plain bokmål
uv run matris check <recipe-url>        # how one matprat.no or godt.no recipe fits
uv run uvicorn adapters.web.main:app    # the site on http://127.0.0.1:8000
```

Each read command takes `--json` for agents: one JSON doc on stdout, errors as `{"error": {"kind", "message"}}` with exit code 1. Site's `/api` returns same shape; `/llms.txt` and `/api/openapi.json` describe it.

## Rebuild the data (weekly)

```sh
export TYPESAFE_API_KEY=...                   # https://console.typesafe.ai
uv run python -m pipeline.datasets --offers   # this week's offers and their matches (Jev)
uv run python -m pipeline.datasets            # also every recipe again, and a row for each new ingredient name
```

`datasets/traits.json` = vocabulary: row per ingredient name with category + facts, kept between builds, fixed by hand. Build drafts row for unseen name; review in `git diff datasets/traits.json`. Then commit `datasets/` and push; push to main deploys (.github/workflows/deploy.yml).

## Check

```sh
uvx ruff check . && uv run ty check src tests && uv run mypy && uv run pytest -q
```
