# The pipeline, rebuilt around a kept vocabulary

jb, 2026-10-22: "we have two type of crawlers: 1. recipes (matprat.no, godt.no, we might add more later) 2. discounts
(mattilbud.no, other later). What Jev does is to connect these, as the data is not always 1 to 1." "We need be
independent of what they do." "i want to keep the site as is, ie. code is the source of truth for the frontend part."
"ideally, this should be 90% plus pipeline."

Checklist. Delete item when done + verified.

## What does not change

Site: src/adapters/web, src/core, src/app/queries.py, templates, CLI search commands. Three files it reads keep
shape: dishes.json (dinners w/ parts: name, category, grams, unit), traits.json (facts per name), offers.json (offers,
matches per name, served per dinner, places). Cards, chips, «Hovedråvare», filters, order by kroner off: as today. Site
already lists every fitting dinner w/ any discounted ingredient, most kroner off first = what jb wants; main ingredient
only labels card + feeds its chip.

## What changes: the pipeline

**Today** every build asks Jev 25 questions about all 1 741 ingredient names, invents shelf for 596 godt.no-only names
by showing Jev one arbitrary dinner, checks guess against labels, throws all away next build. Jev answers wobble → 3
to 5 % of dinners flip diet verdict build to build; wrong answer (peas hold egg, lettuce holds pork) re-rolled, not
fixed.

**After** pipeline = three steps; Jev connects unseen things once.

```
recipes (matprat, godt.no) ──> dinners + lines (name, grams, unit, form)
                                     │ look every name up in traits.json, the vocabulary we keep
                                     │ a name without a row gets one, once: category, facts, product (Jev)
                                     ▼
offers (mattilbud) ──> Jev: offer ↔ product, per dinner for meat and fish with the form ──> offers.json
```

**The vocabulary** = datasets/traits.json, kept between builds, sorted + indented JSON, hand-fixed when wrong. Row
per ingredient name: `category` (our kinds list; same strings site reads today, = matprat's 35 shelves until renamed or
merged), `product` (which product name is; name itself until set), facts as now, `source` (`hand`, or Jev model that
drafted row) replacing `model`.

**A name without a row** (none appeared between 2026-10-14 and 2026-10-22 builds) gets one, once: category from recipe
line when source has one (matprat), else from matprat name w/ same words after fillers dropped («erter» is
«frosne erter»), else Jev picks from our categories, each shown w/ names filed there, no hint dinner; facts from Jev w/ that
category as context; `product` = name. Row appended + printed; `git diff datasets/traits.json` = review.

**dishes.json** takes each part's category from vocabulary, never from build-time guess. **Form:** one word from line
(røkt, hermetisk, tørket, grillet, kokt, speket, frossen) stored per part → weekly run tells tin from loin w/o recipe
wording. **offers.json:** matches asked per product, written per name → site lookup unchanged.

## 0. Decided (jb, 2026-10-22)

- [x] traits.json kept + hand-fixed; dishes.json + offers.json built from sources every time.
- [x] No names by hand: missing row drafted once by Jev; diff = review.
- [x] Site, filters, cards stay. Code = truth for front end.
- [x] Only dinners w/ kroner off at or above floor shown ("no point in showing 100 menues with tuna on sale
      for 8kr"); the week's draw goes.

## 1. The vocabulary (pipeline, data)

- [x] Row shape: `category`, `product`, `source` join facts; `model` goes. src/core/models.py `Traits.of` and
      `levels`, src/adapters/datasets.py (read and write). The site ignores the new keys. `CATEGORIES`, our list of
      kinds, in src/core/matching.py.
- [x] tests/test_traits.py reviews file: every name in dishes.json has row; every part's category = its row's;
      a row is consistent (`animal` no means no meat, fish, shellfish, milk or egg «yes»; pork yes means meat yes;
      /grønnsaker, /frukt, /bær, /poteter, /sopp and /nøtter hold nothing from an animal; /kjøtt holds meat and
      /svinekjøtt pork; /fisk og sjømat holds fish, shellfish or molluscs and no meat; /ost and /melk hold milk; /egg
      holds egg; named exceptions: hvalkjøtt, ferdig potetmos).
- [x] Seeded once from live traits.json (2026-10-14, jev-1.13.0) w/ throwaway script outside repo:
      category from the matprat line (1 148), else the near-name (54), else the 2026-10-14 pick (542); `product` =
      name; `source`; then 61 rows fixed by hand (the test's flags and the known wrong answers). dishes.json's parts
      took their row's category (347 parts, 20 names). Logged in METHOD.md §2.

## 2. The build (pipeline, code)

- [x] src/app/build.py: `draft` asks Jev only for names w/o row (three-way lookup above for category,
      then the facts with it as context) and appends rows; `filed` gives every part its row's category. `classify`,
      `fill_departments`, `dishes_of` and the hint dinner are gone. The build prints the new names.
- [x] src/core/matching.py `agrees` + `doubted` gone, and w/ them «maybe» doubt check wrote; `words`
      is the near-name key.
- [x] src/pipeline/jev.py: `dish` context gone from both classifiers; `JevDepartmentClassifier` is
      `JevCategoryClassifier`; `JEV_MODEL` stays.
- [x] Form: core.dishes `form` reads line when Dish made (parsers untouched); `Part.form` w/ a
      default of "" so the site's reader does not care; written to dishes.json and read back when there.
- [x] `match` asks per product w/ form + dinner name, writes per name; `lines` plumbing through
      `snapshot`, `reprice` and `match` is gone. src/pipeline/jev.py `_offer_question` says what the dinner wants it
      as (`form`, or AS_NAMED when the line says none).
- [ ] Vanished lines: «Ribbesandwich» has pork since «ribberester» filed under /kjøtt/svinekjøtt by hand.
      «Svinespyd med østerssaus og kokosmelk» (godt.no 17056) still has none in the build of 2026-10-23. Read the
      page (jb's OK first); if the main ingredient is a nameless line, src/pipeline/godt.py (which drops a line
      without a name) keeps it.
- [x] Tests: tests/test_build.py classify + department tests follow new shape; tests/test_pipeline_jev.py loses
      the hint-dinner tests; tests/fakes.py loses `dish` arguments.
- [x] FACTS.md §4 + §6, METHOD.md §2, AGENTS.md `datasets/` line, README.md say what build does now.

## 3. The ten percent that is not pipeline

- [x] Floor: `Queries.ranked` keeps dinner only from `core.ranking.FLOOR_KR` off, 20 kr to start. With this
      week's offers: 2 262 of 3 392 dinners have any kroner off, 1 467 have 20 or more, 1 180 have 30 or more, 582
      have 50 or more; the median among those on sale is 31 kr. To tune on the cards. /om and llms.txt say it.
- [x] Week's draw deleted: `Week`, `pick`, `plan`, `POOL`, `kroner` in src/core/ranking.py; `Queries.plan` (the
      counts live on as `Queries.tally`, core.models `Tally`); `/api/plan`; `matris plan`; `schema.plan`, `PlanOut` and
      the `plan` links; `week:` in profile.yaml, the template and src/adapters/profile.py; the links in llms.txt; the
      tests. `Dinner.sale`, which nothing read, went with it.
- [x] Docs fixed where they disagree w/ code (audit 2026-10-22): FACTS.md §1 says 300 ms where
      the page uses 100; FACTS.md §1 and README.md lead with a week the site does not show; FACTS.md §2 names a
      `build.refresh` that does not exist; FACTS.md §6's wrong-answer list is stale; METHOD.md §3 and §6 mention
      swaps; METHOD.md §4 describes `Dinner.sale`; README.md's check line lacks `uv run mypy`; docs/plan-web.md says
      the site reads profile.yaml and ranks at start-up; src/adapters/cli.py's `candidates` help says "færrest bytter
      først".

## 4. Order of work

Each step own commit w/ `uvx ruff check .`, `uv run ty check src tests`, `uv run mypy` + touched tests green. jb
before every push.

1. Docs fixed (§3, last item). Commit.
2. Vocabulary: row shape, test, seeded file (§1). Commit.
3. Build on vocabulary; hint dinner + doubt check gone (§2). Commit.
4. Form, products, matcher's question, no `lines` (§2). Commit.
5. Floor; week's draw deleted (§3). Commit.
6. Vanished lines (§2). Rebuild dishes.json + offers.json (jb, 2026-10-23, 62134ab), check cards (done: 37
   rows + two snack words hand-fixed, METHOD.md §2), push w/ jb's OK.
