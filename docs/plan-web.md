# Plan: matris.app on Fly

Status: done. Online at https://matris.app since 2026-10-13 (FACTS.md §7).

## Why

jb 2026-10-13: "Lets make this into a fly.io service, see ex. over at statsbudsjett, we will use the domain; matris.app. The page will provide dinner options based on the constraints we have selected, for now. we leave jev out of the online version. Lets make sure to adop a hex arch here."

## What we measured

- The ranking over 1 943 dinners takes well under a second and is done once at start-up; the app used 67 MiB in Docker. (Since 2026-10-14 a ranking is worked out when a search first needs it, FACTS.md §1.)
- Every build starts from scratch (jb 2026-10-13): the matprat crawl and every Jev question, each time.
- The snapshot is 4.1 MB of JSON (dishes.json 3.6 MB), fine for git and the image.

## Decisions

- Jev stays offline: `src/pipeline/` builds `datasets/` on a laptop and the site reads it. The server has no Jev key and calls neither matprat.no nor Tjek, and the image does not contain the pipeline.
- The snapshot holds every dinner and every shoppable ingredient's matches, independent of the household, so the site applies the rules itself and other households are possible later. A dish is facts only (jb: "there are loads of other constaints that might apply, so we can not have these attched to the dish").
- The repo is public (jb, 2026-10-13), so dishes.json keeps no ingredient wording or method from matprat: per ingredient only name, department, unit and grams per portion rounded to 5 g, which the rules need. `/api/oppskrift` and `matris check --json` give no ingredient lists. profile.yaml says `small_kids`, not ages.
- The site used our profile.yaml "for now"; the same day jb turned that down ("why would i have a profile for the webpage?"), so it starts with no rules and a visitor picks them in the search (AGENTS.md). It shows the rules without saying why. profile.yaml's comments name no conditions or family details, since the repo is public.
- Layout, docs, Docker, Fly and CI copy statsbudsjett. ty and tests/test_boundary.py replace mypy and import-linter from the ezwork-style version.
- User-facing text is bokmål; API and CLI JSON keys stay English, the same shape as before.
- The project is called matris after the domain; the folder is still ~/src/fooood.

## Steps to go online (each needs jb's go-ahead)

1. A GitHub repo for the code, with the FLY_API_TOKEN secret (`fly tokens create deploy`).
2. `fly apps create matris`, then the first `fly deploy` (or a push to main).
3. `fly certs add matris.app` (and www.), then the A/AAAA (or CNAME) records at the registrar that Fly prints.
4. `fly secrets set CANONICAL_HOST=matris.app` once the certificate is issued.
