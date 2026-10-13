# METHOD

Every simplification and judgement call behind what the site suggests. Add to it whenever you make one. Facts about the sources are in FACTS.md.

## 1. Does a dinner fit (src/core/diet.py)

- Each ingredient's traits come from Jev (FACTS.md §6); the rules below are code, worked out at runtime from a dish's facts, so a new rule needs no new data (FACTS.md §4).
- Onion (`avoid`): every onion-family ingredient is a swap. With `onion_substitute` set (vårløk), that onion itself is fine and the swap says "bruk vårløk i stedet" (jb 2026-10-13: "a lot of the time we can replace onion with spring onion"). A dish with an onion ingredient in its name ("Biff med løk", but not "… med hvitløk" or "… med vårløk") is left out, since the onion is the point. Without a substitute, a dish with about three onions for four (75 g per portion) is also left out.
- Gluten (`avoid`): a "yes" ingredient is a swap to the gluten-free version. A "maybe" (stock, sausages, spice mixes) is a note to check the label.
- Garlic: a note by default; `avoid` makes it a swap to garlic oil.
- Lactose: grams per portion from the parts' grams per portion, counting only matprat's dairy departments (`/melk/melkeprodukter`, `/ost`, or no department), at 0 / 0.1 / 3.0 / 4.7 g per 100 g for none / trace / some / high. Jev called akevitt, vineddik and riseddik lactose-rich; matprat's departments are set by hand, so they decide. Above the profile's limit (3 g, a conservative choice; many tolerate far more in one meal), every some/high dairy ingredient gets a lactose-free swap.
- Units to grams are rough (`GRAMS_PER_UNIT`): 1 dl = 100 g, 1 ss = 15 g, 1 stk = 100 g (a medium onion or carrot), 1 beger = 300 g. Grams per portion are rounded to 5 g in dishes.json (src/core/dishes.py), which moves a few small amounts to 0.
- Kids: with `small_kids`, chili heat and choking risks (whole nuts, sausages, cherry tomatoes, grapes) are notes in the CLI's text output. On the site a card only says «Sterk», for a dinner that is not barnevennlig (§6); the notes were too many to read, and as they name ingredient after ingredient, they are not in the API either (jb 2026-10-13). The profile says only that there are small kids, not their ages.
- `swaps: false` leaves out any dinner needing a swap other than lactose-free dairy.

## 2. Asking Jev

- A label is "yes" when its probability is at least 0.5, and "maybe" when yes and maybe together are (src/pipeline/jev.py `_label`). For lactose, some+high ≥ 0.5 picks between some and high, otherwise between none and trace.
- The kids question says "toddlers", not the household's ages: nothing about the household is sent.
- An offer counts as an ingredient from probability 0.5 (src/app/build.py `MATCH_THRESHOLD`).
- Offers are only looked up for ingredients that matter for the shop (§4 weights), via a word filter: the first 5 letters of each word of the ingredient name in the offer heading ("lakse" finds LAKSEFILET), skipping adjectives like grønn, rød, fersk (src/core/matching.py `_FILLER`).
- A heading equal to the ingredient name is a match without asking; a heading with pålegg, chips, burger, nuggets, kjeks, sjokolade, godteri, postei, smårett or snacks is not, unless the ingredient's own name has the word (hamburgerbrød).

## 3. Main protein and variety

- A dinner's main protein is its heaviest meat, fish or shellfish ingredient by grams, grouped by matprat department (fisk, skalldyr, kylling, kalkun, and, kjøttdeig, svin, pølser, storfe, lam, vilt; other meat is "kjøtt"; none is "vegetar"). matprat's own main-ingredient label is not used, since it files "Kyllingfilet med spekeskinke" under pork.
- The week has one dinner per protein, except fish, which may come `week.fish` times but never the same fish ingredient twice (jb 2026-10-13: "load of chicken options"). If too few proteins fit, the rest is filled with repeats.
- The list under the week puts the best 3 of each protein first and the rest after, unless a protein or a word is searched for; with nothing searched it leaves out the week's dinners. It used to stop at 3 per protein, which showed 39 of the 1 908 dinners at most.

## 4. Offers and discounts

- An offer is on sale when it has a before-price above today's price: Tjek's field, or "Førpris"/"Før" in the text, using the lower end of a range. Catalog items without one count for nothing, even though they are in the weekly catalog (jb 2026-10-13: "dinners we pick are based of discounts").
- When the price is a tenth of the per-kg price (priced per 100 g) and the before-price is per kg, the before-price is divided by 10. Discounts above 75 % are dropped as unit mix-ups.
- A dinner is on sale when its main protein is discounted; without meat or fish, a vegetable from 100 g per portion. Discounted bacon on the side does not make lutefisk a dinner on sale.
- How much is on sale: weight times discount, summed. Weight is 3 for meat, fish and shellfish, 1 for eggs, vegetables, potatoes and mushrooms, 0.5 for fruit, cheese and rice/pasta, scaled by amount up to 100 g per portion; liquids (dl, ss) count at most 0.5, since matprat files stock under meat. Moving from 400 g per recipe to 100 g per portion changed recipes for 2 or 6 portions: 639 dinners on sale instead of 626 (2026-10-13).
- No prices per dinner: jb asked for candidates that fit, not cost estimates (2026-10-13).

## 5. Ranking

- Fewest swaps first (diet fit matters most), then the most on sale (§4), then rating (rating − 4, from 5 ratings on) and prep time (under 20 min +1, 20–40 +0.5, 40–60 0, over 60 −1).
- The week (`on_sale_only`) is picked from dinners on sale; others only fill in when there are too few.
- Because discounts come before rating, a three-star dish over an hour can make the week when its meat is heavily discounted (open question in TODO.md).
- "De fleste til" on the site is the median end date of the offers, since a few catalogs run for months.

## 6. Search (src/core/search.py)

jb 2026-10-13: "more categories like; uten løk, glutenfree etc… an epic search… highly fit to our need, but it needs to be human friendly".

- The household's rules apply first; a search only narrows the dinners that already fit profile.yaml. No search word changes the rules (AGENTS.md).
- The diet categories describe the recipe as written, with no swaps (of 1 908 dinners on 2026-10-13: glutenfri 994, uten løk 845, lite laktose 1 735, uten hvitløk 1 027, ingen bytter 405): «glutenfri» has no ingredient Jev calls gluten, «uten løk» no onion except the household's substitute (vårløk), «uten hvitløk» no garlic, «lite laktose» at most the profile's limit (3 g per portion when it has none), «ingen bytter» needs no swap at all. Every dinner on the site fits the diet, some only after a swap, so these say "nothing to buy specially". An ingredient Jev never judged makes no diet promise.
- Prep time uses matprat's buckets: «rask», «kjapp», «enkel» and «hverdag» are under 20 min; «under N min» is the strictest bucket that keeps within N (under 30 → under 20, under 45 → under 40, under en time → up to 60); over 90 min is ignored.
- «Godt likt» is a rating of 4.5 or more from at least 20 ratings (508 of 1 908 dinners). «Barnevennlig» has no ingredient Jev calls spicy and no chili, spicy or sterk in the name (1 368 dinners). «På tilbud» is `on_sale` (§4).
- Protein words (kylling, fisk, svin, gris, elg, vegetarisk, …) pick the main protein (§3); several mean either. «kjøtt» is any meat, «sjømat» fish or shellfish, «annet kjøtt» the group of other meat. «uten svin» leaves out any pork ingredient, so torsk med bacon goes too; «uten kjøtt» leaves fish and vegetarian.
- Other words must be in the dish name or an ingredient name: «laks» finds røkelaks and laksefilet (Norwegian compounds: a word of 5+ letters anywhere, 3–4 letters at the start, or at the end of a word at least 4 letters longer, so «ris» finds jasminris but not kapris), and «tacos» finds taco. Dish kinds (suppe, gryte, salat, taco, pizza, wok, …) look at the name only, so «salat» is not every burger with lettuce. «sopp», «ost», «nøtter», «egg», «bær» and «skalldyr» also find matprat's department of that name (sjampinjong is /sopp). «pasta» also finds spagetti, tagliatelle, penne and the like.
- «uten X», «ikke X», «ingen X» and «-X» leave X out, and «og»/«eller» carry it on («uten sopp og paprika»). «uten løk», «uten gluten», «ikke sterk» and «ingen bytter» are the categories, not words. «X eller Y» is either; other words all have to match.
- Words that say nothing (jeg, vil, ha, middag, til, med, …) are skipped. æ, ø and å may be typed as ae, o and a; a word typed with them is matched as written («kål» does not find kalkun).
- A word that matches nothing is swapped for the closest known word (difflib, at least 75 % alike) and the page says so: «kyllign» becomes kylling.
- Dinners with a searched word in the name come before those with it only among the ingredients, then the ranking (§5) decides.
- When nothing matches, the page offers to drop each part of the search, with how many dinners that would give, most first.
