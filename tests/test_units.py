from core.units import counted


def test_a_unit_counts_pieces_unless_it_is_a_mass_a_volume_or_nothing() -> None:
    assert all(counted(unit) for unit in ("stk", "båt", "skive", "boks", "pk", "bunt", "potte", "kvist"))
    assert not any(counted(unit) for unit in ("g", "kg", "ml", "dl", "l", "ss", "ts", ""))
