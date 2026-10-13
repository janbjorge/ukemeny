"""core/ is the pure domain: standard library and other core modules only (hexagonal layout, see AGENTS.md)."""

import ast
from pathlib import Path

CORE = Path(__file__).parent.parent / "src" / "core"
ALLOWED = {"core", "collections", "dataclasses", "datetime", "enum", "re", "typing"}


def test_core_imports_nothing_from_outside() -> None:
    bad = []
    for path in CORE.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            bad += [f"{path.name}: {n}" for n in names if n.split(".")[0] not in ALLOWED]
    assert not bad, bad
