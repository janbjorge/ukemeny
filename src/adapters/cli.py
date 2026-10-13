"""Command-line adapter: `matris --help` lists everything.

The read commands (`plan`, `candidates`, `check`) read datasets/ like the site. With `--json` they print
one JSON document on stdout (src/adapters/schema.py) and nothing else; errors are
`{"error": {"kind", "message"}}` with exit code 1. `build` makes datasets/ with Jev (src/pipeline/datasets.py).
"""

import asyncio
import shutil
import sys
from typing import Annotated, NoReturn

import click
import orjson
import typer
from pydantic import BaseModel

from adapters import profile, schema
from adapters.datasets import DATASETS, JsonDatasets
from app.queries import Queries
from core.models import LABELS, Dinner, Dish, Verdict
from core.search import Tag, protein_word

app = typer.Typer(
    help="Middager fra matprat.no som passer profile.yaml, med ukens tilbud. `matris build` lager datasets/, "
    "`matris plan` gir ukens middager.",
    no_args_is_help=True,
    add_completion=False,
)

JsonOption = Annotated[bool, typer.Option("--json", help="Skriv ett JSON-dokument, for agenter og skript.")]


def fail(kind: str, message: str, as_json: bool) -> NoReturn:
    if as_json:
        typer.echo(orjson.dumps({"error": {"kind": kind, "message": message}}, option=orjson.OPT_INDENT_2).decode())
    else:
        typer.echo(f"feil: {message}", err=True)
    raise typer.Exit(1)


def emit(out: BaseModel) -> None:
    typer.echo(out.model_dump_json(indent=2))


def queries(as_json: bool) -> Queries:
    try:
        p = profile.load(profile.PROFILE)
    except profile.ProfileError as e:
        fail("setup", str(e), as_json)
    if not (DATASETS / "dishes.json").exists():
        fail("setup", f"{DATASETS} mangler. Kjør `matris build` først.", as_json)
    return Queries(JsonDatasets(), p.household, p.week)


def _verdict_lines(verdict: Verdict) -> list[str]:
    lines = [f"   bytt: {s.ingredient}: {s.advice}" for s in verdict.swaps]
    notes: dict[str, list[str]] = {}
    for w in verdict.warnings:
        notes.setdefault(w.ingredient, []).append(w.advice)
    return lines + [f"   merk: {name}: {'; '.join(advice)}" for name, advice in notes.items()]


def _dish_line(dish: Dish, protein: str) -> str:
    rating = f" · ★{dish.rating:.1f} ({dish.rating_count})" if dish.rating else ""
    return f"{dish.name} · {protein} · {dish.prep_time}{rating}"


def _dinner(n: int, d: Dinner) -> str:
    lines = [f"{n}. {_dish_line(d.dish, d.protein)}", f"   {d.dish.url}"]
    for buy in d.buys:
        if (sale := buy.sale) and sale.discount and sale.pre_price:
            lines.append(
                f"   på tilbud: {buy.part.name} -{sale.discount:.0%} hos {sale.store} ({sale.heading}, "
                f"{sale.price:.2f} kr, før {sale.pre_price:.2f}, til {sale.valid_until:%d.%m})"
            )
    return "\n".join(lines + _verdict_lines(d.verdict))


@app.command()
def plan(as_json: JsonOption = False) -> None:
    """Ukens middager: variert, og hovedråvaren er på tilbud."""
    q = queries(as_json)
    week = q.plan()
    if as_json:
        return emit(schema.plan(q, week))
    typer.echo(
        f"{week.fitting:,} av {week.considered:,} middager passer, {week.on_sale:,} med hovedråvaren på tilbud. "
        f"{week.offers:,} tilbud fra {', '.join(week.stores)}.\n"
    )
    for n, d in enumerate(week.dinners, 1):
        typer.echo(_dinner(n, d) + "\n")


@app.command()
def candidates(
    query: Annotated[
        list[str] | None,
        typer.Argument(help="Søk i vanlig bokmål, med eller uten anførselstegn: rask kylling uten sopp, laks eller torsk på tilbud."),
    ] = None,
    top: Annotated[int, typer.Option(help="Hvor mange.")] = 20,
    protein: Annotated[str | None, typer.Option(help="Bare denne: fisk, kylling, svin, vegetar, ... Det samme som ordet i søket.")] = None,
    per_protein: Annotated[int, typer.Option(help="De beste så mange per protein først, for variasjon. 0: bare rangering.")] = 3,
    on_sale: Annotated[bool, typer.Option("--on-sale", help="Bare middager med hovedråvaren på tilbud.")] = False,
    as_json: JsonOption = False,
) -> None:
    """Middager som passer, færrest bytter først, så mest rabatt. Med et søk: de som passer søket."""
    q = queries(as_json)
    words = [*(query or []), protein_word(protein) if protein else "", Tag.ON_SALE.value if on_sale else ""]
    found = q.search(" ".join(w for w in words if w), limit=top, per_protein=per_protein)
    if as_json:
        return emit(schema.dinners(q, found))
    s = found.search
    if s.clauses:
        typer.echo(f"Søker etter: {' · '.join(c.label for c in s.clauses)}")
    for typed, used in s.corrected:
        typer.echo(f"Fant ikke «{typed}», så søker etter «{used}».")
    if s.clauses:
        typer.echo(f"{found.total:,} {'middag passer' if found.total == 1 else 'middager passer'}.\n")
    if not found.dinners and found.relax:
        tips = ", ".join(f"«{c.label}» ({n:,} middager)" for c, n in found.relax[:3])
        typer.echo(f"Ingen middager passer alt dette. Prøv å fjerne {tips}.")
    for n, d in enumerate(found.dinners, 1):
        typer.echo(_dinner(n, d) + "\n")


@app.command()
def check(url: Annotated[str, typer.Argument(help="En oppskrift på matprat.no.")], as_json: JsonOption = False) -> None:
    """Hvordan én oppskrift passer profile.yaml."""
    q = queries(as_json)
    found = q.check(url)
    if found is None:
        fail("not_found", f"Fant ingen middag på {url}", as_json)
    if as_json:
        return emit(schema.check(found))
    verdict = found.verdict
    typer.echo(found.dish.name)
    typer.echo(
        f"   passer ikke: {verdict.blocked}" if verdict.blocked else "   passer med bytter" if verdict.swaps else "   passer som den er"
    )
    typer.echo("\n".join(_verdict_lines(verdict)))
    typer.echo(f"   laktose: rundt {verdict.lactose_g:.1f} g per porsjon før bytter")


@app.command()
def build(
    refresh: Annotated[bool, typer.Option("--refresh", help="Hent også nye og endrede oppskrifter fra matprat.no.")] = False,
    relabel: Annotated[
        list[str] | None, typer.Option("--relabel", help="Spør Jev om denne merkelappen igjen for alle ingredienser («all» for alle).")
    ] = None,
) -> None:
    """Lag datasets/ med Jev: ukens tilbud og nye ingredienser. Trenger TYPESAFE_API_KEY."""
    from pipeline import datasets as pipeline

    steps = {
        "recipes": "matprat.no: {due} sider å hente",
        "ingredients": "Jev: {due} ingredienser å vurdere",
        "catalogs": "mattilbud.no: leser ukens kundeaviser",
        "offers": "Jev: {due} ingredienser å matche mot tilbud",
    }
    try:
        labels = LABELS if relabel and "all" in relabel else tuple(relabel or ())
        report = pipeline.reporter(steps, lambda line: typer.echo(line, err=True))
        result = asyncio.run(pipeline.run(refresh, progress=report, relabel=labels))
    except (pipeline.SetupError, profile.ProfileError) as e:
        fail("setup", str(e), False)
    s = result.snapshot
    typer.echo(f"{len(s.dishes):,} middager, {len(s.traits):,} ingredienser, {len(s.offers):,} tilbud.")
    typer.echo(result.jev, err=True)


@app.command("profile")
def edit_profile() -> None:
    """Endre profile.yaml (hva vi ikke tåler, hvor vi handler, uka). Lages fra malen første gang."""
    path = profile.PROFILE
    if not path.exists():
        shutil.copyfile(profile.TEMPLATE, path)
        typer.echo(f"Laget {path} fra malen.")
    click.edit(filename=str(path))
    try:
        profile.load(path)
    except profile.ProfileError as e:
        fail("setup", str(e), False)
    typer.echo(f"Lagret {path}.")


if __name__ == "__main__":
    sys.exit(app())
