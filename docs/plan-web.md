# Plan: matris.app on Fly

Status: done. Online at https://matris.app since 2026-10-13 (FACTS.md §7).

## Why

jb 2026-10-13: "Lets make this into a fly.io service, see ex. over at statsbudsjett, we will use the domain; matris.app. The page will provide dinner options based on the constraints we have selected, for now. we leave jev out of the online version. Lets make sure to adop a hex arch here."

## What we measured

- Ranking over 1 943 dinners well under 1 s, done once at start-up; app used 67 MiB in Docker. (Since 2026-10-14 ranking computed when search first needs it, FACTS.md §1.)
- Every build starts from scratch (jb 2026-10-13): matprat crawl + every Jev question, each time.
- Snapshot 4.1 MB JSON (dishes.json 3.6 MB), fine for git + image.

## Decisions

- Jev stays offline: `src/pipeline/` builds `datasets/` on laptop, site reads it. Server has no Jev key, calls neither matprat.no nor Tjek; image lacks pipeline.
- Snapshot holds every dinner + every shoppable ingredient's matches, household-independent → site applies rules itself, other households possible later. Dish = facts only (jb: "there are loads of other constaints that might apply, so we can not have these attched to the dish").
- Repo public (jb, 2026-10-13) → dishes.json keeps no matprat ingredient wording or method: per ingredient only name, department, unit, grams per portion rounded to 5 g (what rules need). `/api/oppskrift` and `matris check --json` give no ingredient lists. profile.yaml says `small_kids`, not ages.
- Site used our profile.yaml "for now"; same day jb rejected ("why would i have a profile for the webpage?") → starts with no rules, visitor picks them in search (AGENTS.md). Shows rules without saying why. profile.yaml comments name no conditions or family details (repo public).
- Layout, docs, Docker, Fly, CI copy statsbudsjett. ty + tests/test_boundary.py replace mypy + import-linter from ezwork-style version.
- User-facing text bokmål; API + CLI JSON keys stay English, same shape as before.
- Project named matris after domain; folder still ~/src/fooood.

## Steps to go online (each needs jb's go-ahead)

1. GitHub repo for code, with FLY_API_TOKEN secret (`fly tokens create deploy`).
2. `fly apps create matris`, then first `fly deploy` (or push to main).
3. `fly certs add matris.app` (+ www.), then A/AAAA (or CNAME) records Fly prints, at registrar.
4. `fly secrets set CANONICAL_HOST=matris.app` once certificate issued.
