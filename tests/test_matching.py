from core.dishes import dish
from core.matching import (
    candidates,
    cheapest_first,
    heading_key,
    main_protein,
    not_an_ingredient,
    per_dinner,
    stems,
    weight,
    words,
)
from core.models import Part
from tests.fakes import ingredient, offer, recipe


def test_weight_by_category_and_amount_per_portion() -> None:
    assert weight(Part("kyllingfilet", "/kjøtt/kylling/høns", 150, "g")) == 3.0
    assert weight(Part("laks", "/fisk og sjømat", 100, "g")) == 3.0
    assert weight(Part("bacon", "/kjøtt/svinekjøtt", 25, "g")) == 0.75
    assert weight(Part("poteter", "/poteter", 100, "stk")) == 1.0
    assert weight(Part("kjøttbuljong", "/kjøtt/storfekjøtt", 250, "l")) == 0.5
    assert weight(Part("kylling", "/kjøtt/kylling/høns", None, "")) == 1.5
    assert weight(Part("pepper", "/krydder", 0, "ts")) == 0.0


def test_stems_drop_filler_words() -> None:
    assert stems("skinn- og beinfri laksefilet") == {"lakse"}
    assert stems("frisk grønn asparges") == {"aspar"}


def test_candidates_share_a_stem_with_the_heading() -> None:
    offers = [offer("LAKSEFILET"), offer("RØKT LAKS"), offer("KYLLINGFILET"), offer("TOMATER")]
    found = candidates("laksefilet", offers)
    assert [o.heading for o in found] == ["LAKSEFILET"]
    assert [o.heading for o in candidates("kyllingbryst", offers)] == ["KYLLINGFILET"]


def test_short_words_need_the_whole_word() -> None:
    offers = [offer("EGG"), offer("EGGNUDLER"), offer("VEGGIEBURGER")]
    assert [o.heading for o in candidates("egg", offers)] == ["EGG", "EGGNUDLER", "VEGGIEBURGER"]


def test_cheapest_per_kg_first() -> None:
    dear = offer("KYLLINGFILET", 99, per_kg=141.0)
    cheap = offer("KYLLINGFILET", 139, per_kg=139.0, store="REMA 1000")
    assert cheapest_first([dear, cheap]) == (cheap, dear)


def test_snacks_and_pålegg_are_no_ingredient() -> None:
    assert heading_key("  Kylling  FILET ") == "kylling filet"
    assert not_an_ingredient("kyllingfilet", "Coop kyllingpålegg")
    assert not_an_ingredient("potet", "MAARUD POTETGULL") and not_an_ingredient("nudler", "COOP KOPPNUDLER")
    assert not not_an_ingredient("hamburgerbrød", "HAMBURGERBRØD GROVE")
    assert not not_an_ingredient("tunfisk", "Tunfisk")  # Named alike, still asked: it may be a tin


def test_meat_fish_and_shellfish_are_matched_per_dinner() -> None:
    assert per_dinner(Part("tunfisk", "/fisk og sjømat", 50, "g"))
    assert per_dinner(Part("reker", "/skalldyr", 50, "g"))
    assert per_dinner(Part("ribbe", "/kjøtt/svinekjøtt", 300, "g"))
    assert not per_dinner(Part("tomat", "/grønnsaker", 100, "g"))


def test_main_protein_is_the_heaviest_meat_or_fish() -> None:
    chicken = ingredient("kyllingfilet", 600, "g", "/kjøtt/kylling/høns")
    ham = ingredient("spekeskinke", 100, "g", "/kjøtt/spekemat")
    assert main_protein(dish(recipe("A", chicken, ham))) == ("kylling", "kyllingfilet")
    assert main_protein(dish(recipe("B", ham))) == ("kjøtt", "spekeskinke")
    assert main_protein(dish(recipe("C", ingredient("brokkoli", 300, "g", "/grønnsaker")))) == (
        "vegetar",
        "",
    )


def test_stock_is_the_main_protein_only_without_solid_meat_or_fish() -> None:
    stock = ingredient("kjøttkraft", 5, "dl", "/kjøtt/storfekjøtt")
    chops = ingredient("kotelett av svin", 4, "stk", "/kjøtt/svinekjøtt")
    assert main_protein(dish(recipe("A", stock, chops))) == ("svin", "kotelett av svin")
    assert main_protein(dish(recipe("B", stock))) == ("storfe", "kjøttkraft")


def test_a_near_name_has_the_same_words_once_fillers_are_dropped() -> None:
    assert words("frosne erter") == words("erter") == {"erter"}
    assert words("friske urter") == words("urter")
    assert words("rød chili") == words("chili") != words("tørket chili")  # A dried spice is its own product
    assert words("kjøttdeig av svin") != words("kjøttdeig")
