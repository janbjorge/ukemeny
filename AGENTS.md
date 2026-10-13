# Rules for agents

- Read FACTS.md first and keep it true. If it and the code disagree, the code wins; fix the file.
- Check TODO.md before and after work. Move finished items to docs/done.md with the date and the quoted request.
- Log every simplification or judgement call about diet, matching and ranking in METHOD.md.
- Each fact lives in one file; the others link to it. Do not copy sections between files.

## The household

- The site has no profile (jb 2026-10-13: "why would i have a profile for the webpage? that makes no sense"): it starts with no diet rules, and a visitor picks «uten løk», «glutenfri» or «lite laktose» in the search. `profile.yaml` is for the CLI only: its base household, which the same words add to, and its place, which a place in the search replaces.
- Build only what jb asked for. Every element on the page needs a request behind it (jb 2026-10-13: "half of the fucking feature ive not asked for. This clutter hell").
- The site and the repo say what the rules are ("Uten løk", "Glutenfritt"), never why. No health conditions, ages or names in user-facing text, data, docs or commits.
- User-facing text is plain bokmål. JSON keys for agents are English.

## Code

- Python 3.14 with uv: deferred annotations, `type` aliases, frozen slotted dataclasses, StrEnum. Plain `python3` is a rye shim; use `uv run python`.
- Hexagonal layout (FACTS.md §2): `src/core/` stays pure, enforced by tests/test_boundary.py. Pages are rendered on the server with Jinja + HTMX.
- pydantic v2 lives in the adapters only (profile.yaml, query strings, the JSON shape). `src/core/` keeps its dataclasses.
- JSON goes through orjson. JSON in the repo is formatted like `jq .` (src/adapters/datasets.py `write`).
- Jev runs offline only, in `src/pipeline/`. The site reads `datasets/` and needs no key; the Docker image does not even contain `src/pipeline/`.
- Tests never reach the network or Jev (tests/conftest.py). Use the fakes in tests/fakes.py or httpx2.MockTransport.
- mypy in strict mode, and `Any` is banned (jb 2026-10-13: "our application is mypy in strict mode and any is banned!"): name the type, a TypedDict for JSON or `object` for anything. mypy (`disallow_any_explicit`) and ruff (TID251) both refuse it.
- Before commit: `uvx ruff check .`, `uv run ty check src tests`, `uv run mypy`, `uv run pytest tests/<files you touched>`. Then run the app and look at it.

## Git and hosting

- Commit to `main`. No force-push.
- `datasets/` is committed; rebuild it weekly with `uv run python -m pipeline.datasets` (FACTS.md §4).
- Every push to `main` is checked and deployed to Fly by .github/workflows/deploy.yml, which makes it public. Ask jb before every push.
