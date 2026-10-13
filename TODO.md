# TODO

Every request from jb, with status. Newest first. An item is ticked only when it is done and verified; finished items move to docs/done.md.

## Open

- [ ] Offers per place, picked in the search (jb 2026-10-13: "At the moment the pipeline assumes one location (stavanger), we need to extend this not assume location, and push that up to the search input in the 'finn en middag' part"). The code and the first build with places are committed (FACTS.md §1, §4). Left: a push, then a look at the live site.
- [ ] Logfire, every insight the app can see (jb 2026-10-13: "I wanto add logfire, go full tilt on all options. Make sure to understand the runtime in terms of being on fly.io and make sure we get every insight metric we can into logfire"). The code is in (FACTS.md §7) and checked in the Docker image. Left: a `matris` project in Logfire with a write token, `fly secrets set LOGFIRE_TOKEN=… -a matris`, a push, then check that the data arrives.
- [ ] Tune Lavkarbo's 20 g per portion (METHOD.md §1): it leaves 378 of 1 943 dinners.
- [ ] Rebuild `datasets/` every week so the offers stay current: by hand (`uv run python -m pipeline.datasets`, commit, push), or a scheduled GitHub Action with a `TYPESAFE_API_KEY` secret (Jev would still run offline, not in the site).
- [ ] Open question: a minimum rating or a maximum prep time in profile.yaml, since a discount can put a three-star, hour-long dish in the week (METHOD.md §5).

## Ideas not yet requested

- Fix the known wrong Jev answers (FACTS.md §6) with a small list of overrides.
- Keep one Fly machine running (`min_machines_running = 1`) so the first visit after a quiet spell does not wait for a start; it costs a running machine around the clock.
- A shopping list for the week, from `check --json` ingredient lists.

## Done

Moved to docs/done.md.
