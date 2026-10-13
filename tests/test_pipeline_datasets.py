from pipeline.datasets import STEPS, reporter


def test_the_build_says_what_it_does_lightly() -> None:
    lines: list[str] = []
    report = reporter(STEPS, lines.append)
    report("ingredients", 0, 1148)
    for done in range(1, 1149):
        report("ingredients", done, 1148)
    report("catalogs", 0, 1)
    report("catalogs", 1, 1)
    assert lines[0] == "Jev: 1,148 ingredients to label"
    assert lines[1] == "  114/1,148" and lines[-2] == "  1,148/1,148"
    assert len(lines) == 13  # a start, ten steps of a tenth, the end, and the catalogs
    assert lines[-1] == "mattilbud.no: reading this week's catalogs"
