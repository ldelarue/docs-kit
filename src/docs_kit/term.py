"""Terminal output: ANSI colors only on an interactive, non-NO_COLOR stdout."""

from __future__ import annotations

import os
import sys
from enum import StrEnum


class Color(StrEnum):
    RED = "31"
    YELLOW = "33"
    CYAN = "36"
    BOLD = "1"
    DIM = "2"


def paint(text: str, color: Color) -> str:
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
        return f"\033[{color}m{text}\033[0m"
    return text


def section(title: str) -> None:
    print(paint(f"\n{title}", Color.BOLD))


def added(what: str) -> None:
    print(f"  {paint('+', Color.CYAN)} {what}")
