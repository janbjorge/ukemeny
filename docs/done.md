# Done

Finished requests from jb, newest first. Each quotes the request and says what was built.

## 2026-10-13

- [x] **A dish holds facts, not constraints** ("These food constraints should not be part of a dish? … there are loads of other constaints that might apply"): `Dish` and `Part` are name, link, ratings and per ingredient its name, department, unit and grams per portion; lactose, onion, main protein and discount weight are worked out at runtime (FACTS.md §4).
- [x] **Public repo without the recipes** (jb picked "Public repo, no ingredients"): dishes.json has no ingredient wording or method, the API and CLI give no ingredient lists, and profile.yaml has `small_kids` instead of ages.
- [x] **A Fly service at matris.app, statsbudsjett style, without Jev online** ("Lets make this into a fly.io service … we leave jev out of the online version. Lets make sure to adop a hex arch here"): the code moved to `src/core` (pure, tests/test_boundary.py), `src/app`, `src/adapters` (site, API, CLI, profile, datasets) and `src/pipeline` (offline: matprat, Tjek, Jev, SQLite). The site reads a committed snapshot, `datasets/`. Pages: `/` and `/om` in bokmål, `/middager` as an HTMX fragment, `/api`, `/llms.txt`, robots, sitemap, `/helse`. Dockerfile, fly.toml and the deploy workflow as statsbudsjett. Checked locally and in Docker; deploying waits for jb (TODO.md). The project and CLI are now called matris.
- [x] **CLI for agents** ("can we make some kind of super nice cli api that an llm/agent can use insted?"; "I dont want to host the agent, i want to make tooling for them"): `--json` on `plan`, `candidates` and `check`, one document on stdout, errors as JSON with exit code 1. The site's `/api` returns the same shape (src/adapters/schema.py).
- [x] **Cache Tjek** ("Tjek can be cached as well, i think offers are on a per weeek basis"): raw offers per catalog in `data/tjek/`; a run makes 1 request instead of 23.
- [x] **Variety** ("Lets try to also bring in some diverty checks here, load of chicken options"): main protein from the recipe's heaviest meat or fish; the week has one per protein and never the same fish twice; lists show at most 3 per protein (METHOD.md §3).
- [x] **Constraints only in the profile** ("this option need to go away; constrins are in the profile"): `--garlic`, `--strict`, `--days` and `--fish` removed.
- [x] **Pick dinners by discounts** ("i want to make sure that dinners we pick are based of discounts"): on sale means a before-price; ranking is swaps, then discount, then rating and time; the week is picked from dinners on sale (METHOD.md §4–5). Found and fixed per-100 g prices read as 91 % off.
- [x] **Don't hammer Jev** ("We need to make sure we do not hammer jev"): offer answers cached per ingredient and heading, obvious answers without asking, 8 requests at a time. A rerun went from 371 calls to 0.
- [x] **Spring onion** ("alot of the time, we can replace onion wtth spring onion"; "we need to encode spring onion somehow into our profile"): `diet.onion_substitute: vårløk` in profile.yaml.
- [x] **profile.yaml** ("Lets make a profile yml or somehing, like we have in ezwork"): diet, kids, shopping and week, validated with pydantic, edited with `matris profile`.
- [x] **Diet first, not costs** ("No need todo cost esiamtes yet"; "It looks like you went down the raboit whole of cost optimization"): no price per dinner; diet fit ranks first.
- [x] **Jev for classification, ezwork layout** ("lean on some of the apporch from ezwork … and meybe that we lean on Jev todo some of these classifcations?"): ingredient traits and offer matching with Jev, cached; prompts probed live (FACTS.md §6).
- [x] **The first research and tool** ("we are a small familiy … i want some kind of tool that checks; https://mattilbud.no/ … check matprat.no with price offerings and suggest dinners"): matprat.no recipes and mattilbud.no offers (via Tjek), checked against the household's diet.
