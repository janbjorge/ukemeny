# TODO

Every request from jb, with status. Newest first. An item is ticked only when it is done and verified; finished items move to docs/done.md.

## Open

- [ ] Ask Jev the 21 new labels for all 1 148 ingredients (`uv run python -m pipeline.datasets`; about 1 150 calls, roughly $0.16 by the probe), commit datasets/, and only then push: until the labels are in, every new Kosthold and Allergier chip leaves every dinner out. Then tune Lavkarbo's 20 g (METHOD.md §1).
- [ ] Rebuild `datasets/` every week so the offers stay current: by hand (`uv run python -m pipeline.datasets`, commit, push), or a scheduled GitHub Action with a `TYPESAFE_API_KEY` secret (Jev would still run offline, not in the site).
- [ ] Open question: a minimum rating or a maximum prep time in profile.yaml, since a discount can put a three-star, hour-long dish in the week (METHOD.md §5).

## Ideas not yet requested

- Fix the known wrong Jev answers (FACTS.md §6) with a small list of overrides.
- Logfire tracing as in statsbudsjett, once the site is live.
- Keep one Fly machine running (`min_machines_running = 1`) so the first visit after a quiet spell does not wait for a start; it costs a running machine around the clock.
- A shopping list for the week, from `check --json` ingredient lists.

## Done

Moved to docs/done.md.
