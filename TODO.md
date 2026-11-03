# TODO

Open work only. Done → delete; code is record (jb 2026-11-03: "No need to track done, done is in the code").

## Now

Numbers must hold (jb 2026-11-02: "The resulsts does not feel real or correct").

- [ ] Card's kroner off from one chain: `Dinner.saving` sums cheapest offer per ingredient across chains. Pick rule, METHOD.md §3.
- [ ] Floor on main ingredient: sides alone pass FLOOR_KR (kålrot + potet = 20 kr). Pick rule, count dinners, METHOD.md §3, §8.
- [ ] Wrong Jev matches (Smøremyk → smøreost, Ristorante → carnaroli-ris, ALI HELE BØNNER → grønne bønner): probe or override list, jb's OK.
- [ ] Shopping list from `/menu`, per chain, shareable by seed, printable. ASCII mockup first.
- [ ] «Bytt» one dinner on menu, keeps rest. ASCII mockup first.

## Later

- [ ] Menu: tune «Balansert»'s 80 kr.
- [ ] `--offers` run, then check kjøttdeig cards; rebuild `datasets/` weekly (by hand or GitHub Action).
- [ ] `--known`: check godt.no robots.txt, then run.
- [ ] «Svinespyd med østerssaus og kokosmelk» has no pork part.
- [ ] Logfire: project + `fly secrets set LOGFIRE_TOKEN=… -a matris`, check data arrives.
- [ ] Link discount line to shop's own ad, not Tjek. Outside reads need jb's OK.
- [ ] Tune Lavkarbo's 20 g per portion (METHOD.md §1).
- [ ] Min rating or max prep time? (METHOD.md §5)
