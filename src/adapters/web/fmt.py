"""Jinja filters: Norwegian number and date formats."""

from datetime import date, datetime

__all__ = ["dato", "kr", "prosent"]

NBSP = "\u00a0"
MINUS = "\u2212"


def kr(value: float) -> str:
    """99.9 -> "99,90 kr"; whole kroner without decimals. A no-break space before kr."""
    text = f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
    return text.replace(",", NBSP).replace(".", ",") + f"{NBSP}kr"


def prosent(fraction: float) -> str:
    """0.27 -> "-27 %" with a real minus sign, for a discount."""
    return f"{MINUS}{round(fraction * 100)}{NBSP}%"


def dato(value: date | datetime) -> str:
    """2026-10-18 -> "18.10." """
    return f"{value.day}.{value.month}."
