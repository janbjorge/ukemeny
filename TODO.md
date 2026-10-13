# TODO

Every request from jb, with status. Newest first. An item is ticked only when it is done and verified; finished items move to docs/done.md.

## Open

- [ ] Put matris.app online on Fly (jb 2026-10-13: "Lets make this into a fly.io service … we will use the domain; matris.app"; approved "Yes, do all of it"). Live at https://matris.fly.dev, certificate for matris.app requested (FACTS.md §7). Left: jb sets the A and AAAA records at the registrar; then `fly certs check matris.app` until issued, and `fly secrets set CANONICAL_HOST=matris.app`. Also a public GitHub repo (jb creates it in the web UI) with the FLY_API_TOKEN secret, so pushes deploy.
- [ ] Rebuild `datasets/` every week so the offers stay current: by hand (`uv run python -m pipeline.datasets`, commit, push), or a scheduled GitHub Action with a `TYPESAFE_API_KEY` secret (Jev would still run offline, not in the site).
- [ ] Open question: a minimum rating or a maximum prep time in profile.yaml, since a discount can put a three-star, hour-long dish in the week (METHOD.md §5).
- [ ] Let visitors pick their own rules on the page ("for now" the site shows ours).

## Ideas not yet requested

- Fix the known wrong Jev answers (FACTS.md §6) with a small list of overrides.
- Logfire tracing as in statsbudsjett, once the site is live.
- PNG icons (favicon.png, apple-touch-icon) next to icon.svg.
- A shopping list for the week, from `check --json` ingredient lists.

## Done

Moved to docs/done.md.
