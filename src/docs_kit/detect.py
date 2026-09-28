"""Autodetection: which pipelines a repository gets, from what it holds."""

from __future__ import annotations

import os
import sys
import tomllib
from enum import StrEnum
from pathlib import Path

from . import render_cli

# bin name -> {"recipe": Recipe, "app": "<pkg>.cli:app" for Typer bins}
Bins = dict[str, dict[str, str]]


class Recipe(StrEnum):
    """How a CLI's committed contract is regenerated."""

    PYTHON = "python"  # Typer app exported in this venv
    GO = "go"  # cobra core piped on stdin
    KDL = "kdl"  # committed contract, generator unknown
    UNKNOWN = "unknown"  # only named with --bin


def _typer_bins(root: Path) -> dict[str, str]:
    """console-scripts of pyprojects that depend on typer: <name> -> app spec."""
    py = root / "pyproject.toml"
    if not py.is_file():
        return {}
    try:
        data = tomllib.loads(py.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}
    deps = list(data.get("project", {}).get("dependencies", []))
    deps += list(data.get("dependency-groups", {}).get("runtime", []))
    if not any(dep.strip().lower().startswith("typer") for dep in deps):
        return {}
    bins: dict[str, str] = {}
    for name, target in data.get("project", {}).get("scripts", {}).items():
        module = str(target).partition(":")[0].strip()
        if module:
            # convention: the Typer app is <pkg>.cli:app, or the same module's
            # :app when the script already targets a .cli module
            bins[name] = (
                f"{module}:app" if module.endswith(".cli") else f"{module}.cli:app"
            )
    return bins


def _cobra_bins(root: Path) -> list[str]:
    """module basename of a go.mod requiring spf13/cobra."""
    gomod = root / "go.mod"
    if not gomod.is_file() or b"github.com/spf13/cobra" not in gomod.read_bytes():
        return []
    for line in gomod.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("module "):
            return [line.split("/")[-1].strip()]
    return []


def detect_pipelines(
    root: Path,
    spec_name: str,
    spec_explicit: bool,
    extra_bins: list[str],
    *,
    no_api: bool = False,
    no_cli: bool = False,
) -> tuple[bool, Bins]:
    """(api_active, bins) for the repository at root."""
    if spec_explicit and not (root / spec_name).is_file():
        sys.exit(
            f"ERROR: --spec {spec_name} not found in {root} (pass a path or drop it)."
        )
    api_active = (root / spec_name).is_file() and not no_api
    if no_cli:
        return api_active, {}

    bins: Bins = {}
    for name, app in _typer_bins(root).items():
        bins[name] = {"recipe": Recipe.PYTHON, "app": app}
    for name in _cobra_bins(root):
        bins.setdefault(name, {"recipe": Recipe.GO})
    for name in render_cli.contract_kdls(root):
        bins.setdefault(name, {"recipe": Recipe.KDL})
    for name in extra_bins:
        bins.setdefault(name, {"recipe": Recipe.UNKNOWN})
    return api_active, bins


def github_detected(root: Path) -> bool:
    """True on clones of a GitHub repository and on GitHub Actions; the
    workflow file is meaningless elsewhere (e.g. Stash-hosted repos)."""
    if (root / ".github" / "workflows").is_dir():
        return True
    if os.environ.get("GITHUB_REPOSITORY"):
        return True
    try:
        return "github.com" in (root / ".git" / "config").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return False
