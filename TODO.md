# TODO

Every request from jb, with status. Newest first. An item is ticked only when it is done and verified; finished items move to docs/done.md.

## Open

- [ ] **Only the offers, weekly** ("For the most part i think matprat and godt.no wont really change that mutch. So i want sometihng that fetches the updated tilbud and does the matching"): `--offers` (FACTS.md §4). The code is in. Left: a run, then a look at the cards.
- [ ] **godt.no without its sitemap** ("it seems godt.no has changed there agent polecy, so we need to find relay on the urls we have in dishes.json"): `--known` (FACTS.md §4). The code is in. Left: check godt.no's robots.txt still lets matris read recipe pages, then a run.
- [ ] **Offers matched for the dinner, not the name** ("I think we have a bug in our classifier"; "im pretty sure that the cheep tuna, is canned, not really something you want to use with sussu?"; "Tracking a new 'canned' attribute seems to narrow to me"; "lets start the re-deisn. We should also make sure that we do not waaste effort on dishes that do not have any discounts"): meat, fish and shellfish are asked about per dinner, with the recipe's line, so a tin, smoked salmon or grilled ribbe only counts where the dinner can use it; only discounted offers are asked about (METHOD.md §2). The code is in. Left: a rebuild of `datasets/` (godt.no's dinners come from `/oppskrifter/middag`; the sitemap is 404, FACTS.md §3), then a look at the cards.
- [ ] Offers per place, picked in «Sted» (jb 2026-10-13: "At the moment the pipeline assumes one location (stavanger), we need to extend this not assume location, and push that up to the search input in the 'finn en middag' part"). The code and the first build with places are committed (FACTS.md §1, §4); the place moved from the search to a select on 2026-10-14 (docs/done.md). Left: a push, then a look at the live site.
- [ ] Logfire, every insight the app can see (jb 2026-10-13: "I wanto add logfire, go full tilt on all options. Make sure to understand the runtime in terms of being on fly.io and make sure we get every insight metric we can into logfire"). The code is in (FACTS.md §7) and checked in the Docker image. Left: a `matris` project in Logfire with a write token, `fly secrets set LOGFIRE_TOKEN=… -a matris`, a push, then check that the data arrives.
- [ ] Tune Lavkarbo's 20 g per portion (METHOD.md §1): it leaves 378 of 1 943 dinners (727 of 3 399 with godt.no, 2026-10-14).
- [ ] Rebuild `datasets/` every week so the offers stay current: by hand (`uv run python -m pipeline.datasets`, commit, push), or a scheduled GitHub Action with a `TYPESAFE_API_KEY` secret (Jev would still run offline, not in the site).
- [ ] Open question: a minimum rating or a maximum prep time in profile.yaml, since a discount can put a three-star, hour-long dish in the week (METHOD.md §5).

## Ideas not yet requested

- Fix the known wrong Jev answers (FACTS.md §6) with a small list of overrides.
- Keep one Fly machine running (`min_machines_running = 1`) so the first visit after a quiet spell does not wait for a start; it costs a running machine around the clock.
- A shopping list for the week, from `check --json` ingredient lists.

## Done

Moved to docs/done.md.
