# Kroner off per person

jb, 2026-10-23: "Next, i would like an option to calcuate the per person savings. Im unsure if we can do this cleanly, so
lets make sure we do reserach, and make a rock solid plan here. There are loads of unit floating around, so we need to
make sure we use the right units, i think we should just do all our calculations in grams or kilograms something like
that. Same with volumn, liter or milli liter. I think kg and l are good starting points, but you do the reserach"

That turns 2026-10-22 ("I dont think we should get into per portion, its a rabbit hole"; METHOD.md §4) around, on the
research below. A checklist like docs/plan-model.md: tick an item when done and verified; finished items go to
docs/done.md.

## What the data holds (2026-10-23: the build 62134ab with the fixes of 2e7bcb1, every store, no rules)

**The recipes.** 3 401 dinners, 45 116 ingredient lines, 21 808 of them in the categories the offers are looked up in
(core.matching.WEIGHTS). Portions: 4 in 2 418 dinners, 2 in 333, 6 in 225, 8 in 170, 1 in 146 (74 godt.no, 72 matprat;
25 of those are a batch with 300 g of meat or more per «portion»: pølser, kraft). The units of the 21 808 lines:

| unit                                                                                         | lines | what it is                          |
|----------------------------------------------------------------------------------------------|------:|-------------------------------------|
| stk                                                                                          | 8 681 | a piece                             |
| g                                                                                            | 4 965 | mass                                |
| ss                                                                                           | 1 619 | volume                              |
| båt                                                                                          | 1 595 | a piece (a clove)                   |
| none                                                                                         | 1 562 | no amount                           |
| kg                                                                                           |   534 | mass                                |
| dl                                                                                           |   513 | volume                              |
| bunt, ts, stilk, pk, potte, skive, håndfull, kvist, kvast, pose, boks, blad, pakke, bit, l … | 2 339 | pieces, a few volumes, some nothing |

Meat is weighed: g 1 492, kg 329, stk 574 («4 kyllingfileter», «2 biffer»), skive 82. Fish: g 345, stk 76, kg 30. Eggs:
stk 559, every one. Vegetables: stk 5 722, båt 1 587, g 1 398, ss 1 264. Cheese: g 670, dl 120 (revet). Pasta and rice:
g 415, dl 120. Both sources give an amount and a unit on nearly every line that carries money; the 1 562 lines with no
unit are godt.no's herbs and garnish (koriander, friske urter, persille, parmesan, lime: 1 549 of them), and only 54 of
the 8 681 stk lines carry a weight in the name («kylling (ca. 1500 g)»).

dishes.json keeps one number per line, `grams` per portion rounded to 5 g, from core.diet.GRAMS_PER_UNIT, a rough table
made for the lactose and carbohydrate rules: a stk is 100 g whatever it is, a boks 400 g, a ss 15 g. So «2 stk biff av
ytrefilet» for two is 100 g a head in the file (a ytrefilet steak is nearer 180 g), and «4 stk soltørkede tomater» for
two is 200 g a head (a sun-dried tomato is about 5 g). Fine for a lactose rule, useless for kroner.

**The offers.** 3 596 offers, 1 266 discounted, 284 of them on a card (108 matched by name, 176 served per dinner).
offers.json keeps the price, the before-price, `per_kg` and the catalog text. Tjek's `quantity` (the printed unit, its SI
unit and factor, the size from–to) is read for `per_kg` only, and `pieces`, if Tjek fills it, is not read at all. The
price's basis differs by offer, and `saving` (before-price minus price) follows it: per kilo for weighed goods («Biff,
pr. kg 269,40, førpris 449,00»: 179,60 kr), per 100 g where the catalog prices so («Grillet ribbe 29,90, pr kg 299,00»:
4 kr), per pack for packs («Bacon 130 g, 29,90, førpris 33,90»: 4 kr), per two packs for a multi-buy («Gårdsegg 12 stk,
2 for 80, 1 pk 58,50»: 37 kr). Of the 284 on a card, 222 name a pack size in the text and have a per-kilo price, 33 name a
size range («250–500 g») and no single per-kilo price, 19 are weighed goods with no size, 2 are per piece with no size.

**The cards.** 1 226 dinners shown, 2 103 discount lines. By what both sides say:

| lines | share | what                                                                                                                                                                                              |
|------:|------:|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|   790 |  38 % | mass on both sides (g or kg against a pack in g, a price per kilo or per 100 g): the figure needs nothing more                                                                                     |
|   434 |  21 % | one offer without an amount in the text: Obs's eggs («12 store egg … 2 for 80»), on 454 cards                                                                                                     |
|   397 |  19 % | the recipe counts pieces, the offer sells by weight (brokkoli 46 lines, mango 33, kyllingfilet 32, potet 30, kotelett 21, laksefilet 15 …; 69 names this week, 371 in all the dinners): a piece weight per name is needed |
|   282 |  13 % | the offer's size is a range («250–500 g», «100–250 g»), so its price per kilo is a range too                                                                                                     |
|   137 |   7 % | the recipe line has no amount (friske urter, a pose of salad)                                                                                                                                     |
|    25 |   1 % | the recipe measures a solid by volume (1 dl revet gulost, 2 ss rosiner), the offer sells by weight: a density is needed (8 names)                                                                 |
|    28 |   1 % | volume against a piece (ss of urter against a pot)                                                                                                                                                |
|    10 |       | pieces on both sides (grillet kyllinglår pr stk): needs nothing more                                                                                                                              |

In the terms below, once the egg count is read: 1 234 of the 2 103 lines are direct pricing (59 %), 732 indirect (35 %)
and 137 have nothing (7 %).

Two things the per-pack sum does today. It ranks a per-kilo saving against per-pack ones: 49 of the top 50 cards lead
with a weighed good's per-kilo saving, the top 20 all with SPAR's biff at 179,60 kr a kilo, which no one saves on a 400 g
dinner. And the egg offer alone (37 kr for two packs) lifts 320 of the 1 226 cards over the 20 kr floor; per person it is
about 1,50 kr.

What a per-person figure looks like over the 800 lines that need nothing more: the median line is 7,47 kr a head
(quartiles 4,12 and 12,44); 554 dinners save 5 kr or more a head on those lines, 321 10 kr or more, 59 20 kr or more.
«Innbakt biff» is worked through under the model.

## The model

### Units

Three dimensions, one base unit each, and nothing else in the arithmetic: mass in g, volume in ml, pieces in stk. Not kg
and l: the recipes and the packs are whole numbers in g and ml (400 g, 175 g, 25 g a head, 2 dl is 200 ml), dishes.json
already holds grams per portion rounded to 5 g, and in kg that is 0,025 with float noise in a file we diff. Prices per
kilo and per litre stay as the shops print them (`Offer.per_kg`), for the eye and for ranking the offers of one product
(core.matching.cheapest_first). Every other word a source uses is turned into g, ml or stk at the edge, by the pipeline,
or into nothing: the recipe's mass units g 1, kg 1 000; its volumes ml 1, cl 10, dl 100, l and liter 1 000, ss 15, ts 5;
its pieces stk, båt, skive, boks, pk, pakke, beger, bunt, pose, potte, kvist, kvast, blad, bit, stilk, håndfull, plate,
glass, neve, each one piece of what the unit names. No guess from a unit to grams here: GRAMS_PER_UNIT stays what it is,
for the diet rules and `weight` only.

### Layers and flow

```
matprat.no, godt.no ─ amount, unit, portions ─► core.dishes ────► Part: grams (rough), unit, pieces a head ─► dishes.json (full build)
Tjek ─ price, pre_price, quantity, text ──────► pipeline.tjek ──► Offer: saving, size, size_to, unit, pieces ─► offers.json (weekly)
Jev ─ once per name counted in stk ───────────► app.build.draft ► Traits: piece_g ────────────────────────────► traits.json (kept)
                                                                                                                      │
      core.units: per_portion(part), bought(offer), the piece weight ─► price(part, offer, traits) ─► (kroner a head, Pricing)
                                                                                                                      │
      core.ranking.buys ─► Buy.per_person, Buy.pricing ─► Dinner.per_person, Dinner.pricing ─► the card, the API, the CLI
```

The site reads no catalog text and no recipe line. The pipeline writes amounts, the vocabulary holds the one bridge, and
one pure function does the arithmetic at runtime, so a new rule needs no new data (docs/plan-web.md).

### What each layer knows

| object  | field                             | unit                                                 | from                                                                                                      | written                                              |
|---------|-----------------------------------|------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|------------------------------------------------------|
| Dish    | `portions`                        |                                                      | the source (4 when it says none)                                                                          | full build, as today                                 |
| Part    | `grams`                           | g a head, rounded to 5 g                             | amount × the rough table (core.diet.GRAMS_PER_UNIT)                                                       | full build, as today                                 |
| Part    | `unit`                            | the source's word                                    |                                                                                                           | as today                                             |
| Part    | `pieces` (new)                    | stk a head                                           | amount ÷ portions for a piece unit; None for mass and volume                                              | full build; read from `grams` and the table for an older file |
| Offer   | `price`, `pre_price`, `saving`    | kr for what the price buys                           | Tjek, else the text; before_price keeps the before-price on the price's basis                            | weekly, as today                                     |
| Offer   | `size`, `size_to`, `unit` (new)   | g, ml or stk for one pack; `size_to` None unless a range | Tjek's `quantity`, else the text («175 g», «1 l», «12 stk», «12 store egg»); «pr. kg» is 1 000 g, a price per 100 g 100 g, «pr stk» 1 stk | weekly                                               |
| Offer   | `pieces` (new)                    | packs the price buys                                 | Tjek's `quantity`, else 1 («2 for 80» is 2)                                                               | weekly                                               |
| Traits  | `piece_g` (new)                   | g per stk                                            | Jev once per name counted in stk; the name's own «(ca. 1500 g)»; hand                                     | the draft; kept and fixed by hand                    |
| Buy     | `per_person`, `pricing` (new)     | kr a head; direct or indirect                        | core.units                                                                                                | at runtime                                           |
| Dinner  | `per_person`, `pricing` (new)     | kr a head; direct, indirect or none                  | its lines                                                                                                 | at runtime                                           |

### The arithmetic

One pure function, core.units `price(part, offer, traits)`. It takes what the recipe wants a head (g, ml or stk: `grams`
for mass, `grams` as ml for volume, `pieces` for a piece unit), what the offer's price buys (`pieces` × `size`, in the
offer's unit; a range is its midpoint), and the saving, which is on the same basis as the price. Then

    kroner a head = saving ÷ (pieces × size) × the amount a head

and the row of this table says whether that is straight math or a bridge (jb 2026-10-23: "direct is when we can du
stright math, in-direct, we have to had-wave-gesstimate"):

| the recipe says                                   | the offer sells                   | pricing                 | the amount a head becomes                   |
|---------------------------------------------------|-----------------------------------|-------------------------|---------------------------------------------|
| g                                                 | g (a pack, a kilo, 100 g)         | direct                  | g                                           |
| ml                                                | ml                                | direct                  | ml                                          |
| stk                                               | stk («12 stk», «pr stk»)          | direct                  | stk                                         |
| a container: boks, pk, pakke, beger, pose, glass  | a pack (not a kilo or 100 g)      | direct                  | packs; the offer's size is one pack         |
| stk                                               | g                                 | indirect, piece weight  | stk × `piece_g`, in g                       |
| g                                                 | stk                               | indirect, piece weight  | g ÷ `piece_g`, in stk                       |
| ml (a solid: revet ost, rosiner)                  | g                                 | indirect, density 1     | ml as g                                     |
| g                                                 | ml                                | indirect, density 1     | g as ml                                     |
| anything above                                    | a size range                      | indirect, midpoint      | as above, the size (`size` + `size_to`) ÷ 2 |
| nothing; stk against g without a piece weight; ml against stk | | none                    | no figure                                   |

`Pricing` is an enum in core.units: DIRECT, INDIRECT. A line's pricing is direct only when both sides are in the same
unit and the size is exact.

### A dinner

The lines are the card's (Dinner.deals: one per offer, most important first, the offer with the biggest discount per
ingredient, as today). `per_person` is the sum of the lines with a figure. `pricing` is direct when every line with a
figure is direct, indirect as soon as one is, none when no line has a figure, and then the card has no per-person line.
A line with no figure is not a reason to write «ca.»: it counts for nothing (koriander, persille, parmesan, lime, where
the saving is pennies). The card writes «18 kr per person» for direct and «ca. 18 kr per person» for indirect, whole
kroner. Portions are the source's: a batch recipe for «1 portion» shows the batch's figure, as the source has it.

### «Innbakt biff», 2 portions, 238,40 kr per pack on the card today

| line                     | a head         | the price buys            | saving | pricing                   | kr a head                |
|--------------------------|----------------|---------------------------|-------:|---------------------------|-------------------------:|
| biff av ytrefilet storfe | 1 stk          | 1 000 g (SPAR, pr. kg)    | 179,60 | indirect, 180 g a piece   | 32,33                    |
| soltørkede tomater       | 2 stk          | 190 g (MENY)              |   8,90 | indirect, 5 g a piece     | 0,47                     |
| smøreost                 | 1 ss = 15 ml   | 175 g (SPAR)              |  12,90 | indirect, 1 g a ml        | 1,11                     |
| egg                      | 0,5 stk        | 2 × 12 stk (Obs)          |  37,00 | direct                    | 0,77                     |
| the dinner               |                |                           |        | indirect                  | «ca. 35 kr per person»   |

Two more. Coop's grilled ribbe, 29,90 per 100 g, before 33,90: 4 kr saved on 100 g, 100 g a head, 4 kr, direct. A 700 g
pack of kyllingfilet 30 kr off, «2 stk» for four at 150 g a piece: 0,5 stk × 150 g = 75 g a head, 30 ÷ 700 × 75 = 3,21
kr, indirect.

### Piece weights

A fact per ingredient name in the vocabulary, `piece_g`: grams per stk (egg 60, kyllingfilet 150, brokkoli 350, mango
300, potet 100), drafted once by Jev for a name that any recipe counts in stk (371 names), fixed by hand, bounded by
tests/test_traits.py (5 g to 3 000 g). It is one question per name, once, not one per recipe line: the 8 681 lines in
stk would be thousands of calls per build, the answers would wobble between builds, and dishes.json is rebuilt from the
sources, so a wrong one could not be fixed by hand; a row in traits.json can. A name that carries its weight («kylling
(ca. 1500 g)», 54 lines) is read by the build itself. Eggs need no weight where both sides count pieces («12 store egg»);
against a price per kilo, 60 g an egg bridges. skive and båt stay on the rough table (a slice 20 g, a clove 5 g): few
lines carry money there. It feeds the per-person figure only; the diet rules keep the rough table.

**The question** (jb 2026-10-23: "what question do we ask jev?"). Jev answers three kinds of question, a yes/no (Noul), a
choice between labels (Choice) and a score over an ordered rubric (Score), each with probabilities; none returns a free
number (src/pipeline/jev.py; the typesafe_sdk question types). So the weight is a Score over eleven bands, each twice
the one before, with Norwegian examples as the other questions have (the module docstring: examples moved Jev from
guessing to right). The state is the name and its category, as for the facts, and nothing else: no recipe line, so the
recipes' own implied weight stays an independent check.

    How much does one piece («1 stk») of the Norwegian grocery ingredient `ingredient`, sold in the `category`
    department, weigh: the whole item as a recipe means by one piece (an onion, a chicken fillet, an egg), not a
    serving and not a pack?

| band | grams         | examples                                                                                              |
|-----:|---------------|-------------------------------------------------------------------------------------------------------|
|    0 | under 5       | hvitløksfedd, oliven, kapers, basilikumblad                                                           |
|    1 | 5–10          | daddel, valnøtt, ansjosfilet, liten cherrytomat                                                       |
|    2 | 10–20         | cherrytomat, sjampinjong, rød chili, reddik, eggeplomme, sitrongress                                  |
|    3 | 20–40         | stor sjampinjong, kjøttbolle, fiskebolle, scampi, kyllingvinge, skive loff                            |
|    4 | 40–80         | egg, lime, sjalottløk, wienerpølse, liten potet, plomme, kiwi                                         |
|    5 | 80–160        | løk, potet, tomat, gulrot, sitron, banan, eple, kjøttpølse, laksefilet (porsjon), hamburger           |
|    6 | 160–320       | kyllingfilet, svinekotelett, paprika, avokado, mango, søtpotet, appelsin, purre, kyllinglår med bein   |
|    7 | 320–640       | brokkoli, fennikel, agurk, squash, aubergine, granateple, liten sellerirot, hel ørret                 |
|    8 | 640–1 300     | blomkål, sellerirot, kålrot, ananas, liten hodekål, liten hel kylling, butternut                       |
|    9 | 1 300–2 600   | hel kylling, lammelår, hodekål, honningmelon, ribbe                                                   |
|   10 | over 2 600    | kalkun, vannmelon, hel skinke, hel laks                                                               |

The answer is read as the geometric mean of the bands' midpoints weighted by the probabilities, so a 50/50 between
80–160 and 160–320 reads 160 g, rounded to two digits. When the likeliest band has less than half the probability the
build logs the name as unsure, for the review. A band is at most ±41 % off at its edges, the same order as the midpoint
of a size range, and a band cannot slip a decimal point: no 1,5 for 1 500. A row that lacks `piece_g` for a name some
recipe counts in stk is asked once, as a label added later is asked only for the rows that lack it (the Labels
docstring); a row with it is never asked again. The port gains `IngredientClassifier.weigh(ingredient)`, beside
`classify`.

### Size ranges

A size range («250–500 g») is kept as `size` and `size_to` and priced at the midpoint, indirect. Of the 333 range lines
on this week's cards, 135 are within ±25 % of it and the rest, one Coop cheese offer at 100–250 g, hel kylling at 1,5–2
kg and a vegetable bundle at 300–600 g, up to ±43 % off on that line, diluted in the dinner's sum. The low end is the
shop's «fra» and overstates; the high end understates.

### Guards against a wrong number (jb 2026-10-23: "how do we protect agenst hallucinations in the inferd prices?")

Three doors let a wrong number in: the match (an offer that is not the ingredient; today's wrong yeses, TODO.md), the
piece weight (Jev's one number) and the parse of a catalog text. Nothing else is inferred: the price, the before-price,
the pack size, the recipe's amount and the portions are read, not guessed.

1. **The catalog checks its own parse.** Each offer gives three numbers that must agree: price ≈ per-kilo price × size ÷
   1 000 × pieces. This week every one of the 217 offers on a card with a per-kilo price and a size in the text agrees
   within 10 %. The rule: when they disagree, or when Tjek's `quantity` and the text disagree, the offer gets no amount
   and the build logs it. A size the catalog does not confirm is never used.
2. **The recipes check Jev.** The same ingredient is weighed in one recipe and counted in another: «600 g kyllingfilet»
   for four and «4 kyllingfileter» for four. The median grams a head over a name's g-lines divided by the median pieces
   a head over its stk-lines is a piece weight with no Jev in it: kyllingfilet 150 g, potet 110 g, tomat 100 g,
   kyllinglår 175 g, blomkål 730 g, sjampinjong 25 g. 196 of the 367 names counted in stk have a g-line, 79 have three
   or more lines of each kind, and those 79 carry 3 963 of the 8 670 stk lines. The rule: the build works the implied
   weight out for every name that has one and prints it beside Jev's, and tests/test_traits.py fails when the two differ
   by more than 3× unless the row is `hand`. Where a few lines skew it (løk's ten g-lines are soups: 380 g) the hand
   decides. A name with no g-line at all (sitron, egg, rød chili, lime, paprika, avokado) has only Jev and the band.
3. **Bands per category** in tests/test_traits.py, for the order-of-magnitude slip (1,5 for 1 500): egg 40–80 g, poteter
   20–300 g, sopp 5–100 g, grønnsaker 2–2 000 g, frukt 5–3 000 g, kjøtt 20–5 000 g, fisk 20–3 000 g, skalldyr 5–1 000 g,
   ost 5–500 g. The implied weights run from 6 g (oliven) to 1 000 g (hodekål) among vegetables and 38 g (pølse) to
   3 125 g (lammelår) among meat, so a band cannot do more than that.
4. **The name's own weight** («kylling (ca. 1500 g)», 54 lines) overrides Jev. Before the run over the 371 names, Jev is
   asked those 54 without the hint and compared: the measured error rate of Jev's weights, and whether 3× in 2 is right.
5. **A cap at runtime** in core.units: a line whose amount a head comes out above 1 000 g, 1 000 ml or 20 stk gets no
   figure rather than a number. Batch recipes for «1 portion» lose their line; a hallucinated weight cannot make a card.
6. **Seen, every week.** The build prints the 20 largest per-person lines of the week with their pricing, since a wrong
   number floats to the top of the per-person order; `git diff datasets/traits.json` shows every drafted weight once; the
   card says «ca.» for every indirect figure and the API says which lines are indirect, so a reader can tell a bridge
   from a fact.
7. **The match** stays the bigger lever: a wrong yes puts a right weight on the wrong product. Its guards are the
   existing ones (core.matching.NOT_AN_INGREDIENT, the form per dinner) and the probe of `_offer_question` in TODO.md.
   Per person a wrong match costs less than today: SPAR's biff at 179,60 a kilo becomes 18 kr a head, not 180 on the
   card.

### What stays true (the tests)

- The arithmetic sees g, ml and stk only; every other word is turned into one of them at the edge, or into nothing.
- `pieces` × `size` is what `price` buys, and `saving` is on the same basis.
- A line is direct only when both sides are in the same unit and the size is exact; a dinner is indirect as soon as one
  line is.
- The rough table decides nothing about kroner, except 1 dl = 100 g for a solid by volume, which is indirect.
- The site's three files keep their shape; every new key is optional, and an older file reads as before.

## Decided (jb, 2026-10-23)

- [x] Estimates rather than blanks ("options? i yhink we gesstimate these?"): the midpoint of a size range, the rough
      table for a solid by volume, «ca.» on the card; only a line with no amount on either side gets nothing.
- [x] Jev gives the piece weights ("i think we can lean on jev for these, ex. recepie calls for 4 eggs, but egger i
      kg/kr, or, two filles, but the price is kg/kr"): once per name, kept in the vocabulary, fixed by hand.
- [x] Two kinds of pricing ("I wonder if we should call these two direct, and in-direct pricing, direct is when we can
      du stright math, in-direct, we have to had-wave-gesstimate"): a flag per line and per dinner, «ca.» on the card
      for indirect only.

## Decisions for jb

1. **Where it shows.** Recommended: a line under the sum on every card («18 kr per person», «ca.» when indirect),
   `per_person` and `pricing` on the dinner and on each discount in the API, a column in the CLI; nothing to toggle, the
   site stays as it is. Else: a switch beside «Sted» that turns the sum and the order to per person.
2. **The order.** Unchanged at first. Once the piece weights are in, by per person: that ends the per-kilo against
   per-pack mix at the top of the list. Before them, «4 stk kyllingfilet» would rank under a 25 g line of bacon.
3. **The floor.** 20 kr per pack stays until the order changes. A per-person floor of 5 kr is the same for four at the
   table (554 dinners on this week's direct lines; 321 at 10 kr).
4. **The Tjek probe**, an outside read that needs the OK: one read of this week's offers through the API the build
   already uses, no key, no Jev, to see what `quantity` holds for Norwegian grocers: which unit symbols, how often the
   size is a range, whether `pieces` is filled, what the egg offer says about «12» and «2 for 80». It decides whether the
   offer's amount comes from Tjek's fields with the text as a fallback, or from the text alone, and how a multi-buy is
   read.

## Checklist

### 0. Research

- [x] The numbers above (scripts outside the repo, 2026-10-23).
- [ ] The Tjek probe (decision 4).

### 1. Units (core)

- [x] src/core/units.py: the base units, the recipe's units per dimension, `per_portion(part)` as (amount, unit) or
      None, `bought(offer)`, `Pricing` (DIRECT, INDIRECT; core.models), `price(part, offer, piece_g)` as (kroner,
      Pricing) or None. tests/test_units.py, one test per row of the table.

### 2. The offer's amount (pipeline, data)

- [x] `Offer.size`, `size_to`, `unit`, `pieces`; src/pipeline/tjek.py reads `quantity.pieces` and the size, then the
      text (`amount`, `pieces`); `parse_offer`; OfferJSON read and write; tests/fakes.py `offer(size=, unit=, pieces=)`;
      tests/test_pipeline_tjek.py (the KG fixture, the eggs, a range, «pr stk», a multi-buy), tests/test_datasets.py.
- [x] The self-check (`confirmed`): price ≈ `per_kg` × size ÷ 1 000 × pieces within 10 %; a disagreement gives no amount
      and a log line (217 of 217 offers on a card agree this week; 126 of all 3 596 do not).
- [x] This week's offers.json filled from the text by a script outside the repo (no Jev), so the cards can be looked at
      before the next `--offers` run writes it from Tjek: 1 608 offers in g, 423 in ml, 352 priced per kilo, 267 in
      stk, 273 with a size range, 631 with nothing.

### 3. The recipe's pieces (pipeline, data)

- [x] `Part.pieces`; core.dishes.dish; PartJSON; datasets `_pieces` reads it from `grams` and GRAMS_PER_UNIT when the
      file lacks it; core.units `counted`; tests/test_dishes.py, tests/test_datasets.py, tests/test_units.py. The next
      full build writes it.

### 4. The figure (core)

- [x] `Buy.per_person` (None without a figure) and `Buy.pricing`, `Dinner.per_person` and `Dinner.pricing` (indirect
      as soon as one line is); the ranking untouched; `Traits.piece_g` read and written, so a hand can set one before
      Jev does. tests/test_ranking.py.
- [x] The cap (core.units.CAP): an amount a head above 1 000 g, 1 000 ml, 20 stk or 5 packs gives no figure.

### 5. Shown (web, API, CLI, docs)

- [x] The card line (`.head`, whole kroner, «ca.» when indirect); `DiscountOut.per_person` and `pricing`,
      `DinnerOut.per_person` and `pricing`; the CLI's «spart … kr per person»; /om and llms.txt; FACTS.md §1 and §4,
      METHOD.md §4 and §6. A look at the front page with this week's data (2026-10-24): 84 of the first 100 cards have
      a line, 15 of them «ca.»; «Innbakt biff» says «ca. 2 kr» until the biff's piece weight is in.
- [ ] The push with jb's OK.
- [x] The build prints the 20 largest per-person lines of the week with their pricing (src/pipeline/datasets.py
      `largest_a_head`).

### 6. Piece weights (vocabulary)

- [x] `Traits.piece_g`; tests/test_traits.py bounds; app.build `weighed` (a step of `draft`) asks Jev once for the names
      counted in stk (the Score over eleven bands above, `weigh` in src/pipeline/jev.py and core.ports; a weight in the
      name, «(ca. 1500 g)», is read without Jev: core.units.stated_weight); the bridge in core.units.
- [ ] A run for the 371 names (Jev, the OK first); `git diff datasets/traits.json` is the review.
- [x] The recipes' implied weight per name (median g a head ÷ median stk a head, core.units.implied_weights) logged
      beside Jev's by the build; tests/test_traits.py: within 3× unless a named exception, and the bands per category.
- [ ] Jev asked the 54 names that carry their weight, without the hint, before the run: the measured error rate (the OK
      first; a few calls).
- [ ] A look at the cards, then decisions 2 and 3.

## Order of work

1. The probe (OK). 2. Units and the offer's amount (one commit). 3. Pieces (commit). 4. The figure (commit). 5. Shown
(commit; jb before the push). 6. Piece weights (commit). Each with `uvx ruff check .`, `uv run ty check src tests`,
`uv run mypy` and the touched tests green.
