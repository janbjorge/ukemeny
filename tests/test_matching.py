from core.dishes import dish
from core.matching import (
    agrees,
    candidates,
    cheapest_first,
    doubted,
    heading_key,
    main_protein,
    obvious,
    stems,
    weight,
)
from core.models import Item, Level, Part
from tests.fakes import ingredient, offer, recipe, traits


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


def test_obvious_answers() -> None:
    assert heading_key("  Kylling  FILET ") == "kylling filet"
    assert obvious("poteter", "POTETER") == 1.0
    assert obvious("kyllingfilet", "Coop kyllingpålegg") == 0.0
    assert obvious("hamburgerbrød", "HAMBURGERBRØD GROVE") is None
    assert obvious("kyllingfilet", "KYLLINGBRYST") is None


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


def test_a_picked_department_of_meat_fish_shellfish_or_dairy_needs_a_yes() -> None:
    fish, maybe_meat = traits(contains={Item.FISH: Level.YES}), traits(contains={Item.MEAT: Level.MAYBE})
    assert agrees("/fisk og sjømat", fish) and not agrees("/kjøtt/storfekjøtt", fish)
    assert not agrees("/kjøtt/pølser", maybe_meat)  # «maybe» is a sauce, not the dinner's meat
    assert agrees("/skalldyr", traits(contains={Item.MOLLUSC: Level.YES}))
    assert not agrees("/ost", traits()) and not agrees("/melk/melkeprodukter", traits())
    assert agrees("/grønnsaker", traits())  # Nothing to check


def test_traits_that_disagree_with_a_picked_department_say_maybe() -> None:
    duck = traits()  # Jev called «and» no meat
    assert doubted("/kjøtt/and/gås", duck).contains[Item.MEAT] is Level.MAYBE
    assert doubted("/fisk og sjømat", traits(contains={Item.MOLLUSC: Level.YES})).contains[Item.FISH] is Level.NO  # blekksprut
    assert doubted("/grønnsaker", duck) == duck
