import io

from pipeline.datasets import STEPS, Bars


def test_each_step_leaves_its_bar_behind() -> None:
    out = io.StringIO()
    bars = Bars(STEPS, out)
    bars("ingredients", 0, 1148)
    for done in range(1, 1149):
        bars("ingredients", done, 1148)
    bars("catalogs", 0, 1)
    bars("catalogs", 1, 1)
    lines = out.getvalue().split("\n")
    assert lines[0].rsplit("\r", 1)[-1].startswith("Jev ingredient labels: 100%")
    assert "1148/1148" in lines[0]
    assert lines[1].rsplit("\r", 1)[-1].startswith("mattilbud.no catalogs: 100%")


def test_the_url_being_fetched_shows_while_a_step_runs() -> None:
    out = io.StringIO()
    bars = Bars(STEPS, out)
    bars.fetching("https://www.matprat.no/sitemap.xml")
    bars("recipes", 0, 2)
    bars.fetching("https://www.matprat.no/oppskrifter/middag/a/")
    bars("recipes", 1, 2)
    bars("recipes", 2, 2)
    bars.fetching("https://www.matprat.no/oppskrifter/middag/b/")
    text = out.getvalue()
    assert "/oppskrifter/middag/a/" in text
    assert "sitemap.xml" not in text and "/oppskrifter/middag/b/" not in text


def test_an_empty_step_closes_at_once() -> None:
    out = io.StringIO()
    bars = Bars(STEPS, out)
    bars("offers", 0, 0)
    bars.fetching("https://squid-api.tjek.com/v2/offers")
    assert "Jev offer matches" in out.getvalue() and "squid-api" not in out.getvalue()


def test_the_bars_are_ascii_on_a_utf8_terminal() -> None:
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="utf-8", write_through=True)  # A StringIO has no encoding, so tqdm picks ASCII there anyway
    bars = Bars(STEPS, out)
    bars("recipes", 0, 4)
    bars.fetching("https://www.matprat.no/oppskrifter/middag/a/")
    bars("recipes", 2, 4)
    bars("recipes", 4, 4)
    assert raw.getvalue().isascii()
