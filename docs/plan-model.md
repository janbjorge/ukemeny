# The pipeline, rebuilt around a kept vocabulary

jb, 2026-10-22: "we have two type of crawlers: 1. recipes (matprat.no, godt.no, we might add more later) 2. discounts
(mattilbud.no, other later). What Jev does is to connect these, as the data is not always 1 to 1." "We need be
independent of what they do." "i want to keep the site as is, ie. code is the source of truth for the frontend part."
"ideally, this should be 90% plus pipeline."

A checklist. Tick an item when done and verified; delete it when pruned. Finished items go to docs/done.md.

## What does not change

The site: src/adapters/web, src/core, src/app/queries.py, the templates, the CLI's search commands. The three files it
reads keep their shape: dishes.json (dinners with parts: name, category, grams, unit), traits.json (facts per name),
offers.json (offers, matches per name, served per dinner, places). The cards, the chips, «Hovedråvare», the filters,
the order by kroner off: all as today. The site already lists every fitting dinner with any discounted ingredient,
most kroner off first, which is what jb wants; the main ingredient only labels the card and feeds its chip.

## What changes: the pipeline

**Today** every build asks Jev 25 questions about all 1 741 ingredient names, invents a shelf for the 596 names only
godt.no uses by showing Jev one arbitrary dinner, checks that guess against the labels, and throws everything away for
the next build. Jev's answers wobble, so 3 to 5 % of dinners change their diet verdict from one build to the next, and
a wrong answer (peas hold egg, lettuce holds pork) is re-rolled rather than fixed.

**After** the pipeline is three steps, and Jev connects things it has not seen before, once.

```
recipes (matprat, godt.no) ──> dinners + lines (name, grams, unit, form)
                                     │ look every name up in traits.json, the vocabulary we keep
                                     │ a name without a row gets one, once: category, facts, product (Jev)
                                     ▼
offers (mattilbud) ──> Jev: offer ↔ product, per dinner for meat and fish with the form ──> offers.json
```

**The vocabulary** is datasets/traits.json, kept between builds, sorted and indented JSON, fixed by hand when wrong.
A row per ingredient name: `category` (our list of kinds; the same strings the site reads today, which happen to be
matprat's 35 shelves until we rename or merge them), `product` (which product the name is; the name itself until set),
the facts as now, `source` (`hand`, or the Jev model that drafted the row) instead of `model`.

**A name without a row** (none appeared between the 2026-10-14 and 2026-10-22 builds) gets one, once: the category
from the recipe line when the source has one (matprat), else from the matprat name with the same words once fillers
are dropped («erter» is «frosne erter»), else Jev's pick from our categories, each shown with the names filed there,
with no hint dinner; the facts from Jev with that category as context; `product` the name. The row is appended and
printed; `git diff datasets/traits.json` is the review.

**dishes.json** takes each part's category from the vocabulary, never from a guess made during the build. **Form:**
one word from the line (røkt, hermetisk, tørket, grillet, kokt, speket, frossen) stored per part, so the weekly run can
tell a tin from a loin without the recipe's wording. **offers.json:** matches are asked per product and written per
name, so the site's lookup stays as it is.

## 0. Decided (jb, 2026-10-22)

- [x] traits.json is kept and hand-fixed; dishes.json and offers.json are built from the sources every time.
- [x] No names by hand: a missing row is drafted once by Jev; the diff is the review.
- [x] The site, its filters and its cards stay as they are. The code is the truth for the front end.
- [x] Only dinners with kroner off at or above a floor are shown ("no point in showing 100 menues with tuna on sale
      for 8kr"); the week's draw goes.

## 1. The vocabulary (pipeline, data)

- [x] Row shape: `category`, `product`, `source` join the facts; `model` goes. src/core/models.py `Traits.of` and
      `levels`, src/adapters/datasets.py (read and write). The site ignores the new keys. `CATEGORIES`, our list of
      kinds, in src/core/matching.py.
- [x] tests/test_traits.py reviews the file: every name in dishes.json has a row; every part's category is its row's;
      a row is consistent (`animal` no means no meat, fish, shellfish, milk or egg «yes»; pork yes means meat yes;
      /grønnsaker, /frukt, /bær, /poteter, /sopp and /nøtter hold nothing from an animal; /kjøtt holds meat and
      /svinekjøtt pork; /fisk og sjømat holds fish, shellfish or molluscs and no meat; /ost and /melk hold milk; /egg
      holds egg; named exceptions: hvalkjøtt, ferdig potetmos).
- [x] Seeded once from the live traits.json (2026-10-14, jev-1.13.0) with a throwaway script outside the repo:
      category from the matprat line (1 148), else the near-name (54), else the 2026-10-14 pick (542); `product` =
      name; `source`; then 61 rows fixed by hand (the test's flags and the known wrong answers). dishes.json's parts
      took their row's category (347 parts, 20 names). Logged in METHOD.md §2.

## 2. The build (pipeline, code)

- [x] src/app/build.py: `draft` asks Jev only for names without a row (the three-way lookup above for the category,
      then the facts with it as context) and appends rows; `filed` gives every part its row's category. `classify`,
      `fill_departments`, `dishes_of` and the hint dinner are gone. The build prints the new names.
- [x] src/core/matching.py `agrees` and `doubted` are gone, and with them the «maybe» the doubt check wrote; `words`
      is the near-name key.
- [x] src/pipeline/jev.py: the `dish` context is gone from both classifiers; `JevDepartmentClassifier` is
      `JevCategoryClassifier`; `JEV_MODEL` stays.
- [ ] Form: a function in core that both parsers call on the line; `Part.form` with a default of "" so the site's
      reader does not care; written to dishes.json. src/pipeline/matprat.py, godt.py, src/adapters/datasets.py.
- [ ] `match` asks per product with the form and the dinner's name, and writes per name; the `lines` plumbing through
      `snapshot`, `reprice` and `match` goes. src/pipeline/jev.py `_offer_question` says what the dinner wants it as.
- [ ] The vanished lines: «Svinespyd med østerssaus og kokosmelk» (godt.no 17056) and «Ribbesandwich» have no pork
      part. Read the page (jb's OK first); if the main ingredient is a nameless line, src/pipeline/godt.py keeps it.
- [x] Tests: tests/test_build.py's classify and department tests follow the new shape; tests/test_pipeline_jev.py loses
      the hint-dinner tests; tests/fakes.py loses `dish` arguments.
- [x] FACTS.md §4 and §6, METHOD.md §2, AGENTS.md's `datasets/` line and README.md say what the build does now.

## 3. The ten percent that is not pipeline

- [ ] The floor: `Queries.ranked` keeps a dinner only from this many kroner off, one constant in core, 20 kr to start.
      With this week's offers: 2 262 of 3 392 dinners have any kroner off, 1 467 have 20 or more, 1 180 have 30 or
      more, 582 have 50 or more; the median among those on sale is 31 kr. Tuned on the cards.
- [ ] The week's draw deleted: src/core/ranking.py `Week`, `pick`, `plan`, `POOL`; src/app/queries.py `plan`;
      `/api/plan` in src/adapters/web/api.py; `matris plan` in src/adapters/cli.py; `schema.plan`, `PlanOut` and the
      `plan` links; `week:` in profile.example.yaml and src/adapters/profile.py; the links in llms.txt; the tests.
      `Dinner.sale` in src/core/models.py, which nothing reads, goes with it.
- [x] The docs put right where they disagree with the code (an audit on 2026-10-22): FACTS.md §1 says 300 ms where
      the page uses 100; FACTS.md §1 and README.md lead with a week the site does not show; FACTS.md §2 names a
      `build.refresh` that does not exist; FACTS.md §6's wrong-answer list is stale; METHOD.md §3 and §6 mention
      swaps; METHOD.md §4 describes `Dinner.sale`; README.md's check line lacks `uv run mypy`; docs/plan-web.md says
      the site reads profile.yaml and ranks at start-up; src/adapters/cli.py's `candidates` help says "færrest bytter
      først".

## 4. Order of work

Each step its own commit with `uvx ruff check .`, `uv run ty check src tests`, `uv run mypy` and the touched tests
green. jb before every push.

1. The docs put right (§3, last item). Commit.
2. The vocabulary: row shape, the test, the seeded file (§1). Commit.
3. The build on the vocabulary; the hint dinner and the doubt check gone (§2). Commit.
4. Form, products, the matcher's question, no `lines` (§2). Commit.
5. The floor; the week's draw deleted (§3). Commit.
6. The vanished lines (§2). Rebuild dishes.json and offers.json, look at the cards, push with jb's OK.
