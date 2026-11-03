# Rules for agents

- Read FACTS.md first, keep true. Code and file disagree → code wins; fix file.
- Check TODO.md before + after work. Delete done items; code is record.
- Log every simplification/judgement call on diet, matching, ranking in METHOD.md.
- Each fact in one file; others link. No copying sections between files.

## The household

- Site has no profile (jb 2026-10-13: "why would i have a profile for the webpage? that makes no sense"): starts with no diet rules; visitor picks «uten løk», «glutenfri» or «lite laktose» in search. `profile.yaml` CLI only: base household (same words add to it) and place (`candidates --sted` replaces).
- Build only what jb asked. Every page element needs request behind it (jb 2026-10-13: "half of the fucking feature ive not asked for. This clutter hell").
- Site + repo say what rules are ("Uten løk", "Glutenfritt"), never why. No health conditions, ages, names in user-facing text, data, docs, commits.
- User-facing text plain bokmål. JSON keys for agents English.

## Code

- Python 3.14 with uv: deferred annotations, `type` aliases, frozen slotted dataclasses, StrEnum. Plain `python3` = rye shim; use `uv run python`.
- Hexagonal layout (FACTS.md §2): `src/core/` pure, enforced by tests/test_boundary.py. Pages server-rendered, Jinja + HTMX.
- pydantic v2 in adapters only (profile.yaml, query strings, JSON shape). `src/core/` keeps dataclasses.
- JSON via orjson. Repo JSON formatted like `jq .` (src/adapters/datasets.py `write`).
- Jev offline only, in `src/pipeline/`. Site reads `datasets/`, needs no key; Docker image lacks `src/pipeline/`.
- Tests never hit network or Jev (tests/conftest.py). Use fakes in tests/fakes.py or httpx2.MockTransport.
- mypy strict, `Any` banned (jb 2026-10-13: "our application is mypy in strict mode and any is banned!"): name type, TypedDict for JSON, `object` for anything. mypy (`disallow_any_explicit`) + ruff (TID251) both refuse it.
- Before commit: `uvx ruff check .`, `uv run ty check src tests`, `uv run mypy`, `uv run pytest tests/<files you touched>`. Then run app, look at it.

## Git and hosting

- Commit to `main`. No force-push.
- `datasets/` committed. traits.json = vocabulary: kept between builds, hand-fixed (`source` «hand»), reviewed by tests/test_traits.py, never rebuilt. dishes.json + offers.json built from sources, offers weekly (FACTS.md §4).
- Every push to `main` checked + deployed to Fly by .github/workflows/deploy.yml → public. Ask jb before every push.

## Docs

- Repo md files compressed caveman-style (jb 2026-11-02: "We have loads of md files, we need to compress them, ideally i would like to apply the caveman skill to all of them"). Write new text the same way: no articles or filler, fragments fine. Keep quotes from jb, «…» words, code spans, paths, numbers and headings exact.
