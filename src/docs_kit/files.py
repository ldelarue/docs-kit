"""File helpers shared by the commands: UTF-8, LF line endings."""

from __future__ import annotations

import tomllib
from pathlib import Path


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


def valid_toml(text: str) -> bool:
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return False
    return True
