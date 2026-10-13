"""Search dinners in plain bokmål: «rask kylling uten sopp», «laks eller torsk på tilbud», «glutenfri pasta».

`parse` turns the words into clauses: categories (`Tag`), main proteins, and words to find or leave out.
`Index` finds the dinners that meet every clause. The household's rules apply first: the index holds
the dinners from core.ranking.dinners, in their order. æ, ø and å may be typed as ae, o and a, and a
word that matches nothing is swapped for the closest known word (METHOD.md §6).
"""

import difflib
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from core.matching import PROTEINS, VEGETARIAN
from core.models import Dinner, Gluten, Household, Kids, Onion, Part, Traits


class Tag(StrEnum):
    """A category a dinner is in. The value is how a search writes it, and it parses back."""

    QUICK = "under 20 min"
    UNDER_40 = "under 40 min"
    UNDER_60 = "under en time"
    ON_SALE = "på tilbud"
    LIKED = "godt likt"
    MILD = "barnevennlig"
    AS_IS = "ingen bytter"
    GLUTEN_FREE = "glutenfri"
    ONION_FREE = "uten løk"
    LOW_LACTOSE = "lite laktose"
    GARLIC_FREE = "uten hvitløk"


TIME_TAGS = (Tag.QUICK, Tag.UNDER_40, Tag.UNDER_60)
MINUTES: Mapping[str, int] = {"Under": 20, "20": 40, "40": 60}
"""Most minutes by the start of matprat's prep time bucket; "Over 60 min" and none are slower."""
LIKED_RATING = 4.5
LIKED_COUNT = 20
"""Godt likt: at least this rating from at least this many ratings."""
LACTOSE_G = 3.0
"""Lite laktose when the household sets no limit: grams per portion."""
NOT_MILD = ("chili", "spicy", "sterk")
"""In a dish name, these make it not barnevennlig whatever the ingredients say."""


class Kind(StrEnum):
    TAG = "tag"
    PROTEIN = "protein"
    """The main protein is one of `values`."""
    NOT_PROTEIN = "not_protein"
    """No ingredient (and not the main protein) from these protein groups."""
    WITH = "with"
    """One of `values` is in the name or an ingredient."""
    WITHOUT = "without"
    """`values[0]` is in no ingredient and not in the name."""


@dataclass(frozen=True, slots=True)
class Clause:
    kind: Kind
    values: tuple[str, ...]
    text: str
    """How a search writes it; `parse(text)` gives this clause back."""
    label: str
    """For people: "Uten sopp", "Kylling eller fisk"."""


@dataclass(frozen=True, slots=True)
class Search:
    clauses: tuple[Clause, ...] = ()
    corrected: tuple[tuple[str, str], ...] = ()
    """(typed, used) for words that matched nothing and were swapped for a known word."""

    @property
    def text(self) -> str:
        return " ".join(c.text for c in self.clauses)

    @property
    def words(self) -> tuple[str, ...]:
        """Every word searched for, to mark in dish names."""
        return tuple(w for c in self.clauses if c.kind is Kind.WITH for w in c.values)

    def has(self, clause: Clause) -> bool:
        return clause in self.clauses

    def drop(self, clause: Clause) -> Search:
        return Search(tuple(c for c in self.clauses if c != clause))

    def toggle(self, clause: Clause) -> Search:
        """Without the clause if it is there; otherwise with it, in place of a clause it rules out
        (another prep time, another main protein)."""
        if self.has(clause):
            return self.drop(clause)
        return Search((*(c for c in self.clauses if not _replaces(clause, c)), clause))


def _replaces(new: Clause, old: Clause) -> bool:
    if new.kind is Kind.PROTEIN:
        return old.kind is Kind.PROTEIN
    return new.kind is Kind.TAG and old.kind is Kind.TAG and new.values[0] in TIME_TAGS and old.values[0] in TIME_TAGS


def tag_clause(tag: Tag) -> Clause:
    return Clause(Kind.TAG, (tag.value,), tag.value, tag.value.capitalize())


MEAT = (*dict.fromkeys(g for g in PROTEINS.values() if g not in ("fisk", "skalldyr")), "kjøtt")
PROTEIN_WORDS: Mapping[str, tuple[str, ...]] = {
    **{group: (group,) for group in (*dict.fromkeys(PROTEINS.values()), VEGETARIAN)},
    "annet kjøtt": ("kjøtt",),
    "kjøtt": MEAT,
    "sjømat": ("fisk", "skalldyr"),
}
"""What a search can say about the main protein: a group from core.matching, or several."""
PROTEIN_ALIASES: Mapping[str, str] = {
    "høns": "kylling",
    "høne": "kylling",
    "fiskemiddag": "fisk",
    "karbonadedeig": "kjøttdeig",
    "svinekjøtt": "svin",
    "gris": "svin",
    "pølse": "pølser",
    "storfekjøtt": "storfe",
    "okse": "storfe",
    "oksekjøtt": "storfe",
    "lammekjøtt": "lam",
    "får": "lam",
    "fårekjøtt": "lam",
    "sau": "lam",
    "elg": "vilt",
    "hjort": "vilt",
    "rein": "vilt",
    "reinsdyr": "vilt",
    "rådyr": "vilt",
    "vegetarisk": "vegetar",
    "vegetariske": "vegetar",
    "vegetarmiddag": "vegetar",
    "veggis": "vegetar",
    "kjøttfri": "vegetar",
    "kjøttfritt": "vegetar",
}


def protein_clause(word: str, negated: bool = False) -> Clause:
    """`word` is a key of PROTEIN_WORDS."""
    if negated:
        return Clause(Kind.NOT_PROTEIN, PROTEIN_WORDS[word], f"uten {word}", f"Uten {word}")
    return Clause(Kind.PROTEIN, PROTEIN_WORDS[word], word, word.capitalize())


def protein_word(group: str) -> str:
    """How a search names one protein group: "annet kjøtt" for the group of other meat."""
    return "annet kjøtt" if group == "kjøtt" else group


def with_clause(words: Sequence[str]) -> Clause:
    text = " eller ".join(words)
    return Clause(Kind.WITH, tuple(words), text, f"Med {text}")


def without_clause(word: str) -> Clause:
    return Clause(Kind.WITHOUT, (word,), f"uten {word}", f"Uten {word}")


# The words, as people write them. Keys are matched folded (see `fold`), so "lok" is "løk".
TAG_WORDS: Mapping[str, Tag] = {
    **dict.fromkeys(
        ("rask", "raske", "raskt", "kjapp", "kjappe", "kjapt", "fort", "kvikk", "lynrask", "lettvint", "enkel", "enkle", "enkelt"),
        Tag.QUICK,
    ),
    **dict.fromkeys(("hverdag", "hverdags", "hverdagsmiddag", "hverdagsmat"), Tag.QUICK),
    **dict.fromkeys(
        ("tilbud", "tilbudet", "tilbudene", "billig", "billige", "billigst", "rabatt", "salg", "kampanje", "nedsatt"), Tag.ON_SALE
    ),
    **dict.fromkeys(("likt", "populær", "populære", "favoritt", "favoritter", "best", "beste", "stjerner", "toppkarakter"), Tag.LIKED),
    **dict.fromkeys(("barnevennlig", "barnevennlige", "barn", "barna", "unger", "ungene", "småbarn", "mild", "milde", "mildt"), Tag.MILD),
    **dict.fromkeys(("glutenfri", "glutenfritt", "glutenfrie"), Tag.GLUTEN_FREE),
    **dict.fromkeys(("løkfri", "løkfritt", "løkfrie"), Tag.ONION_FREE),
    **dict.fromkeys(("laktosefri", "laktosefritt", "laktosefrie"), Tag.LOW_LACTOSE),
    **dict.fromkeys(("hvitløkfri", "hvitløksfri", "hvitløkfritt"), Tag.GARLIC_FREE),
}
PHRASES: Mapping[str, Tag | str] = {
    "på tilbud": Tag.ON_SALE,
    "godt likt": Tag.LIKED,
    "mest likt": Tag.LIKED,
    "lite laktose": Tag.LOW_LACTOSE,
    "lav laktose": Tag.LOW_LACTOSE,
    "som den er": Tag.AS_IS,
    "annet kjøtt": "annet kjøtt",
}
"""Several words that mean one thing: a category, or a key of PROTEIN_WORDS."""
NEGATED: Mapping[str, Tag] = {
    "løk": Tag.ONION_FREE,
    "hvitløk": Tag.GARLIC_FREE,
    "gluten": Tag.GLUTEN_FREE,
    "laktose": Tag.LOW_LACTOSE,
    "chili": Tag.MILD,
    "sterk": Tag.MILD,
    "sterkt": Tag.MILD,
    "bytte": Tag.AS_IS,
    "bytter": Tag.AS_IS,
    "endringer": Tag.AS_IS,
}
"""After «uten», «ikke» or «ingen»: «uten løk» is the category, not every word with løk in it."""
NEGATIONS = frozenset({"uten", "ikke", "ingen", "unntatt", "utenom", "minus"})
JOINERS = frozenset({"og", "eller", ",", "samt", "pluss"})
STOP = frozenset(
    """a av da dag de den deilig det digg du en enn er et ei familie familien for forslag fra gi gjerne god gode godt
    ha har hele hva i ide idag ideer ikveld jeg kan kveld lage lager litt lyst mat meg middag middagen middager
    middagstips mye na noe noen oppskrift oppskrifter oss pa passer personer porsjon porsjoner rett retter sa skal
    som spise til tips under veldig vi vil ville""".split()  # noqa: SIM905
)
"""Words that say nothing about the dinner. Folded: "pa" is «på», "a" is «å»."""
SYNONYMS: Mapping[str, tuple[str, ...]] = {
    "pasta": ("spagetti", "spaghetti", "tagliatelle", "makaroni", "penne", "lasagne", "linguine", "fusilli", "gnocchi", "tortellini"),
    "nudler": ("udon", "soba", "ramen"),
    "sopp": ("sjampinjong", "champignon", "kantarell", "shiitake", "portobello"),
    "spagetti": ("spaghetti",),
    "spaghetti": ("spagetti",),
    "ovn": ("ovnsbakt", "ovnsbakte", "langpanne", "form"),
    "ovnen": ("ovnsbakt", "ovnsbakte", "langpanne", "form"),
    "grill": ("grillet", "grillspyd"),
}
"""A word also finds these."""
NAME_ONLY = frozenset(
    """burger curry form grateng gratin grill gryte lapskaus lasagne omelett ovn ovnen pai pizza risotto salat spyd
    stek suppe taco tacos wok wrap""".split()  # noqa: SIM905
)
"""Kinds of dish: found in the dish name only, so «salat» is not every burger with a lettuce leaf."""
DEPARTMENT_WORDS = frozenset({"sopp", "ost", "nøtter", "egg", "bær", "skalldyr"})
"""matprat departments a search word also finds: «uten ost» leaves out parmesan, «uten nøtter» cashew."""

_FOLD = str.maketrans({"æ": "ae", "ø": "o", "å": "a", "ä": "a", "ö": "o", "ü": "u"} | dict.fromkeys("éèê", "e") | dict.fromkeys("óòô", "o"))
_TOKEN = re.compile(r"§\d+|[^\W\d_]+|\d+|,")
_TIME = re.compile(
    r"\b(?:(?:under|innen|maks|max|høyst|hoyst|på|pa|mindre enn)\s+)?"
    r"(?:(\d+)\s*(minutter|minutt|min|m|timer|time|t)\b|(?:(?:en|ei|ett|1)\s+)?(halvtime|kvarter|time)\b)"
)
_DASH = re.compile(r"(^|\s)-(?=\w)")


def fold(word: str) -> str:
    """Lower case without æøå and accents, for keyboards without them: "kjøttdeig" -> "kjottdeig"."""
    return word.lower().translate(_FOLD)


TAG_KEYS = {fold(k): v for k, v in TAG_WORDS.items()}
PHRASE_KEYS = {tuple(fold(k).split()): v for k, v in PHRASES.items()}
NEGATED_KEYS = {fold(k): v for k, v in NEGATED.items()}
PROTEIN_KEYS = {fold(k): k for k in PROTEIN_WORDS} | {fold(k): v for k, v in PROTEIN_ALIASES.items()}
SYNONYM_KEYS = {fold(k): v for k, v in SYNONYMS.items()}
NAME_ONLY_KEYS = frozenset(fold(w) for w in NAME_ONLY)


def _minutes(match: re.Match[str]) -> int:
    number, unit, word = match.groups()
    if word:
        return {"halvtime": 30, "kvarter": 15}.get(word, 60)
    return int(number) * (60 if unit.startswith("t") else 1)


def time_tag(minutes: int) -> Tag | None:
    """The strictest of matprat's buckets that keeps within the time: «under 30 min» is under 20."""
    if minutes < 40:
        return Tag.QUICK
    if minutes < 60:
        return Tag.UNDER_40
    return Tag.UNDER_60 if minutes <= 90 else None


def _tokens(text: str) -> list[str]:
    text = _DASH.sub(r"\1uten ", text.lower())
    text = _TIME.sub(lambda m: f" §{_minutes(m)} ", text)
    return _TOKEN.findall(text)


def _known(key: str) -> bool:
    return key in TAG_KEYS or key in PROTEIN_KEYS or key in NEGATED_KEYS


def parse(text: str, fix: Callable[[str], str] | None = None) -> Search:
    """The clauses in a search, in the order written. `fix` swaps a word that is neither a category nor a
    protein for a known word (Index.fix); without it every other word is searched for as written."""
    tokens = _tokens(text)
    keys = [fold(t) for t in tokens]
    clauses: list[Clause] = []
    corrected: list[tuple[str, str]] = []
    negate = chained = alternative = False

    def add(clause: Clause) -> None:
        nonlocal negate, chained, alternative
        protein = next((c for c in clauses if c.kind is Kind.PROTEIN), None)
        if clause.kind is Kind.PROTEIN and protein is not None:
            # A dinner has one main protein, so «kylling fisk» can only mean either
            if clause.text not in protein.text.split(" eller "):
                text = f"{protein.text} eller {clause.text}"
                values = tuple(dict.fromkeys(protein.values + clause.values))
                clauses[clauses.index(protein)] = Clause(Kind.PROTEIN, values, text, text.capitalize())
        elif clause.kind is Kind.WITH and alternative and clauses and clauses[-1].kind is Kind.WITH:
            clauses[-1] = with_clause((*clauses[-1].values, *clause.values))
        elif clause not in clauses:
            if clause.kind is Kind.TAG and clause.values[0] in TIME_TAGS:
                clauses[:] = [c for c in clauses if not _replaces(clause, c)]
            clauses.append(clause)
        chained = clause.kind in (Kind.WITHOUT, Kind.NOT_PROTEIN) or (clause.kind is Kind.TAG and negate)
        negate = alternative = False

    def word_clause(word: str, key: str) -> Clause | None:
        if negate and key in NEGATED_KEYS:
            return tag_clause(NEGATED_KEYS[key])
        if key in TAG_KEYS:
            return tag_clause(TAG_KEYS[key])
        if key in PROTEIN_KEYS:
            return protein_clause(PROTEIN_KEYS[key], negated=negate)
        return None

    i = 0
    while i < len(tokens):
        word, key = tokens[i], keys[i]
        if key.startswith("§"):
            if tag := time_tag(int(key[1:])):
                add(tag_clause(tag))
            i += 1
            continue
        phrase = next((n for n in (3, 2) if tuple(keys[i : i + n]) in PHRASE_KEYS), 0)
        if phrase:
            meaning = PHRASE_KEYS[tuple(keys[i : i + phrase])]
            add(tag_clause(meaning) if isinstance(meaning, Tag) else protein_clause(meaning, negated=negate))
            i += phrase
            continue
        i += 1
        if key in NEGATIONS:
            negate = True
        elif key in JOINERS:
            negate = chained
            alternative = key == "eller" and not chained
        elif key == "med":
            negate = chained = False
        elif key in STOP or key.isdigit() or len(key) < 2:
            continue
        elif clause := word_clause(word, key):
            add(clause)
        else:
            used = fix(word) if fix else word
            if used != word:
                corrected.append((word, used))
            clause = word_clause(used, fold(used))
            add(clause or (without_clause(used) if negate else with_clause((used,))))
    return Search(tuple(clauses), tuple(corrected))


def tags(dinner: Dinner, traits: Mapping[str, Traits], household: Household) -> frozenset[Tag]:
    """The categories a dinner is in. The diet ones describe the recipe as written, with no swaps: a
    dinner that fits after swapping pasta for gluten-free pasta is not «glutenfri». An ingredient
    that was never judged makes no diet category."""
    dish = dinner.dish
    found: set[Tag] = set()
    limit = next((m for k, m in MINUTES.items() if dish.prep_time.startswith(k)), None)
    if limit is not None:
        found |= {tag for tag, most in zip(TIME_TAGS, (20, 40, 60), strict=True) if limit <= most}
    if dinner.on_sale:
        found.add(Tag.ON_SALE)
    if (dish.rating or 0.0) >= LIKED_RATING and dish.rating_count >= LIKED_COUNT:
        found.add(Tag.LIKED)
    if not dinner.verdict.swaps:
        found.add(Tag.AS_IS)
    known = [(p, traits[p.name]) for p in dish.parts if p.name in traits]
    if len(known) < len(dish.parts):
        return frozenset(found)
    substitute = (household.onion_substitute or "").lower()
    lactose = household.lactose_g_per_portion
    if dinner.verdict.lactose_g <= (LACTOSE_G if lactose is None else lactose):
        found.add(Tag.LOW_LACTOSE)
    if not any(t.gluten is Gluten.YES for _, t in known):
        found.add(Tag.GLUTEN_FREE)
    if not any(t.onion is Onion.ONION and not (substitute and substitute in p.name) for p, t in known):
        found.add(Tag.ONION_FREE)
    if not any(t.onion is Onion.GARLIC for _, t in known):
        found.add(Tag.GARLIC_FREE)
    if not any(t.kids is Kids.SPICY for _, t in known) and not any(w in dish.name.lower() for w in NOT_MILD):
        found.add(Tag.MILD)
    return frozenset(found)


_WORDS = re.compile(r"[^\W\d_]+")


def words(text: str) -> list[str]:
    return _WORDS.findall(text.lower())


def same(term: str, word: str) -> bool:
    """Does a searched word find a word in a name? Norwegian joins words, so «laks» finds «røkelaks» and
    «ris» «jasminris» (but not «kapris»), and «tacos» finds «taco». Both already lower case; a term
    typed without æøå is compared folded."""
    if term.isascii():
        word = fold(word)
    if word == term:
        return True
    n = len(term)
    if n >= 5 and term in word:
        return True
    if n >= 3 and (word.startswith(term) or (word.endswith(term) and len(word) - n >= 4)):
        return True
    return len(word) >= 4 and term.startswith(word) and n - len(word) <= 2


def group(part: Part) -> str | None:
    """The protein group of a meat or fish ingredient, as in core.matching.main_protein."""
    if not part.category.startswith(("/kjøtt", "/fisk og sjømat", "/skalldyr")):
        return None
    return next((g for prefix, g in PROTEINS.items() if part.category.startswith(prefix)), "kjøtt")


@dataclass(frozen=True, slots=True)
class Counts:
    tags: Mapping[Tag, int]
    """Matches if this category were added."""
    proteins: Mapping[str, int]
    """Matches per main protein, whatever protein is chosen now."""


class Index:
    """Dinners to search, in ranking order. Built once; a search after that is a lookup per word and set
    arithmetic."""

    CACHE = 4096

    def __init__(self, ranked: Sequence[Dinner], traits: Mapping[str, Traits], household: Household) -> None:
        self.dinners = tuple(ranked)
        everyone = range(len(self.dinners))
        all_tags = [tags(d, traits, household) for d in self.dinners]
        self._tagged = {tag: frozenset(i for i in everyone if tag in all_tags[i]) for tag in Tag}
        self._at = {d.dish.url: i for i, d in enumerate(self.dinners)}
        self._main: dict[str, set[int]] = {}
        self._present: dict[str, set[int]] = {}
        # Per word, the dinners with it in the name, and with it in an ingredient
        self._in_name: dict[str, set[int]] = {}
        self._in_parts: dict[str, set[int]] = {}
        for i, d in enumerate(self.dinners):
            self._main.setdefault(d.protein, set()).add(i)
            for g in {d.protein, *filter(None, map(group, d.dish.parts))}:
                self._present.setdefault(g, set()).add(i)
            for w in words(d.dish.name):
                self._in_name.setdefault(w, set()).add(i)
            for part in d.dish.parts:
                for w in part_words(part):
                    self._in_parts.setdefault(w, set()).add(i)
        vocabulary: dict[str, str] = {}
        for w in (*TAG_WORDS, *NEGATED, *PROTEIN_WORDS, *PROTEIN_ALIASES, *self._in_name, *self._in_parts):
            if len(w) >= 3 and " " not in w:
                vocabulary.setdefault(fold(w), w)
        self._vocabulary = vocabulary
        self._hits: dict[str, tuple[frozenset[int], frozenset[int]]] = {}

    def has(self, dinner: Dinner, tag: Tag) -> bool:
        """Is the dinner in this category? False for a dinner the index does not hold."""
        i = self._at.get(dinner.dish.url)
        return i is not None and i in self._tagged[tag]

    def hits(self, word: str) -> tuple[frozenset[int], frozenset[int]]:
        """(dinners with the word in the name, dinners with it in the name or an ingredient), with synonyms."""
        term = word.lower()
        if term not in self._hits:
            if len(self._hits) > self.CACHE:
                self._hits.clear()
            found = finds(term)
            named = frozenset().union(*(ids for w, ids in self._in_name.items() if found(w)))
            in_parts = (
                frozenset() if fold(term) in NAME_ONLY_KEYS else frozenset().union(*(ids for w, ids in self._in_parts.items() if found(w)))
            )
            self._hits[term] = (named, named | in_parts)
        return self._hits[term]

    def fix(self, word: str) -> str:
        """The word if any dinner has it, else the closest known word (a category, a protein, a word
        in a dish or ingredient name), else the word."""
        if self.hits(word)[1] or len(word) < 3:
            return word
        close = difflib.get_close_matches(fold(word), self._vocabulary, n=1, cutoff=0.75)
        return self._vocabulary[close[0]] if close else word

    def parse(self, text: str) -> Search:
        return parse(text, self.fix)

    def _keep(self, clauses: Iterable[Clause]) -> tuple[set[int], Counter[int]]:
        keep = set(range(len(self.dinners)))
        named: Counter[int] = Counter()
        for c in clauses:
            match c.kind:
                case Kind.TAG:
                    keep &= self._tagged[Tag(c.values[0])]
                case Kind.PROTEIN:
                    keep &= set().union(*(self._main.get(g, ()) for g in c.values))
                case Kind.NOT_PROTEIN:
                    keep -= set().union(*(self._present.get(g, ()) for g in c.values))
                case Kind.WITH:
                    found = [self.hits(w) for w in c.values]
                    keep &= set().union(*(anywhere for _, anywhere in found))
                    named.update(set().union(*(name for name, _ in found)))
                case Kind.WITHOUT:
                    keep -= self.hits(c.values[0])[1]
        return keep, named

    def find(self, search: Search) -> list[Dinner]:
        """Every dinner that meets all clauses: those with a searched word in the name first, then in
        ranking order."""
        keep, named = self._keep(search.clauses)
        return [self.dinners[i] for i in sorted(keep, key=lambda i: (-named[i], i))]

    def count(self, search: Search) -> Counts:
        keep, _ = self._keep(search.clauses)
        # A prep time and a protein replace the one chosen, so they count from the search without it
        any_time, _ = self._keep(c for c in search.clauses if not _replaces(tag_clause(Tag.QUICK), c))
        any_protein, _ = self._keep(c for c in search.clauses if c.kind is not Kind.PROTEIN)
        return Counts(
            tags={tag: len((any_time if tag in TIME_TAGS else keep) & self._tagged[tag]) for tag in Tag},
            proteins=dict(Counter(self.dinners[i].protein for i in any_protein)),
        )

    def relax(self, search: Search) -> list[tuple[Clause, int]]:
        """When nothing matches: which clause to drop, and how many dinners that gives, most first."""
        found = [(c, len(self._keep(search.drop(c).clauses)[0])) for c in search.clauses]
        return sorted((f for f in found if f[1]), key=lambda f: -f[1])


def finds(term: str) -> Callable[[str], bool]:
    """Does a searched word, or one of its synonyms, find this word?"""
    alternatives = (term.lower(), *SYNONYM_KEYS.get(fold(term), ()))
    return lambda word: any(same(a, word) for a in alternatives)


def part_words(part: Part) -> list[str]:
    """The words a search finds an ingredient by: its name, and some departments (DEPARTMENT_WORDS)."""
    department = part.category.rstrip("/").rsplit("/", 1)[-1]
    return words(part.name) + ([department] if department in DEPARTMENT_WORDS else [])


def via(dinner: Dinner, search: Search) -> tuple[str, ...]:
    """The ingredients that hold a searched word the dish name does not: «sopp» in a kyllinggryte."""
    name = words(dinner.dish.name)
    found: list[str] = []
    for term in search.words:
        match = finds(term)
        if not any(map(match, name)) and fold(term) not in NAME_ONLY_KEYS:
            found.extend(p.name for p in dinner.dish.parts if any(map(match, part_words(p))))
    return tuple(dict.fromkeys(found))


def marked(name: str, search: Search) -> list[tuple[str, bool]]:
    """The dish name in pieces, each with whether it holds a searched word: for <mark> on the page."""
    matchers = [finds(t) for t in search.words]
    pieces = re.split(r"([^\W\d_]+)", name)
    return [(piece, bool(piece) and any(m(piece.lower()) for m in matchers)) for piece in pieces if piece]
