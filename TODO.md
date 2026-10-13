# TODO

Every request from jb, with status. Newest first. An item is ticked only when it is done and verified; finished items move to docs/done.md.

## Open

- [ ] Put matris.app online on Fly (jb 2026-10-13: "Lets make this into a fly.io service … we will use the domain; matris.app"). Built and checked locally, in Docker too (docs/plan-web.md). Waiting for jb to approve the steps that go public: a GitHub repo (public or private) with the FLY_API_TOKEN secret, `fly apps create matris`, the first deploy, `fly certs add matris.app` plus the DNS records at the registrar, then `fly secrets set CANONICAL_HOST=matris.app`.
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
