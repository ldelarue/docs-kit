"""`docs-kit init`: scaffold the site, wire mise, report next steps (idempotent)."""

from __future__ import annotations

import sys
from pathlib import Path

from . import __version__, render
from .detect import Bins, Recipe, detect_pipelines, github_detected
from .files import write
from .glue import write_committed_glue
from .layout import (
    API_SPEC_DEFAULT,
    CLI_STANDARD_PAGE,
    MISE_LOCAL,
    REGEN_CMD,
    ZENSICAL_CONFIG,
)
from .pipeline import generated_outputs, read_spec
from .shim import DEFAULT_SHIM, mise_step
from .term import Color, added, paint, section

GITIGNORE_ENTRIES = ("site/", ".cache/")
KIT_GIT_URL = "git+https://github.com/ldelarue/docs-kit.git"
SECTIONS = ("Tutorials", "Guides", "Explanation", "References")


def _scaffold_files(
    root: Path, spec_name: str, api: bool, bins: Bins
) -> list[tuple[Path, str]]:
    title, description = root.resolve().name, ""
    if api:
        info = read_spec(root, spec_name)[1].get("info", {})
        title = info.get("title") or title
        description = info.get("description") or ""
    files = [
        (
            root / "docs" / "index.md",
            render.render_index_page(title, description, api=api, bins=bins),
        ),
        *(
            (root / "docs" / s.lower() / "index.md", render.render_section_stub(s))
            for s in SECTIONS
        ),
        (
            root / ZENSICAL_CONFIG,
            render.render_zensical_toml(title, description, api=api, bins=bins),
        ),
    ]
    if bins:
        files.append(
            (
                root / CLI_STANDARD_PAGE,
                render.render_cli_standard_page(root.resolve().name, bins),
            )
        )
    return files


def _integrate_gitignore(root: Path, use_mise: bool, committed_mise: bool) -> None:
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    entries = GITIGNORE_ENTRIES
    if committed_mise:
        entries += (MISE_LOCAL,)  # dependency mode owns no shim layer
    elif use_mise:
        entries += (f"{DEFAULT_SHIM}/", MISE_LOCAL)
    lines = text.splitlines()
    new = [e for e in entries if e not in lines]
    if not new:
        print(paint(f"  .gitignore already covers {', '.join(entries)}", Color.DIM))
        return
    text = text.rstrip("\n")
    write(path, (text + "\n" if text else "") + "\n".join(new) + "\n")
    added(f".gitignore {', '.join(new)}")


def _report_group(title: str, written: list[str], unchanged: list[str]) -> None:
    section(title)
    for rel in written:
        added(rel)
    if unchanged:
        noun = "file" if len(unchanged) == 1 else "files"
        print(paint(f"  {len(unchanged)} {noun} already current", Color.DIM))


def cmd_init(
    root: Path,
    spec_name: str = API_SPEC_DEFAULT,
    force: bool = False,
    kit_home: str = DEFAULT_SHIM,
    use_mise: bool = False,
    *,
    committed_mise: bool = False,
    spec_explicit: bool = False,
    extra_bins: list[str] | None = None,
    no_api: bool = False,
    no_cli: bool = False,
) -> int:
    """Install or repair the docs integration (idempotent).

    Missing files are written, identical ones skipped, differing ones refused
    unless --force (generated files: fix with refresh). --with-mise wires the
    shim layer (shim.mise_step); --committed writes the glue block instead.
    Without any documentation source, init refuses.
    """
    api, bins = detect_pipelines(
        root, spec_name, spec_explicit, extra_bins or [], no_api=no_api, no_cli=no_cli
    )
    if not api and not bins:
        sys.exit(
            "ERROR: no documentation source detected: no openapi.json, and no CLI "
            "evidence (cli/<bin>.usage.kdl, a typer console-script in pyproject.toml, "
            "or spf13/cobra in go.mod); name a CLI with --bin BIN, or pass --spec."
        )
    github = github_detected(root)
    detected = ", ".join(
        ([f"API ({spec_name})"] if api else [])
        + sorted(bins)
        + (["workflow:github"] if github else [])
    )
    groups = {
        "Scaffold": _scaffold_files(root, spec_name, api, bins),
        "Generated": generated_outputs(root, spec_name, api, github),
    }
    plan: list[tuple[Path, str]] = []
    written: dict[str, list[str]] = {}
    unchanged: dict[str, list[str]] = {}
    conflicts: list[str] = []
    for title, files in groups.items():
        written[title], unchanged[title] = [], []
        for path, content in files:
            rel = str(path.relative_to(root))
            current = path.read_text(encoding="utf-8") if path.exists() else None
            if current == content:
                unchanged[title].append(rel)
            elif current is None or force:
                plan.append((path, content))
                written[title].append(rel)
            elif title == "Generated":
                conflicts.append(
                    f"  generated: {rel}   -> fix with `{REGEN_CMD}` instead"
                )
            else:
                conflicts.append(f"  hand-written: {rel}")
    if conflicts:
        sys.exit(
            "ERROR: existing files differ from what docs-kit would generate"
            " (not touched):\n"
            + "\n".join(sorted(conflicts))
            + "\nReview them, or re-run with --force to overwrite."
        )

    print(paint(f"docs-kit {__version__} · init", Color.BOLD))
    print(paint(f"  repo {root}   detected {detected}", Color.DIM))
    for path, content in plan:
        write(path, content)
    for title in groups:
        _report_group(title, written[title], unchanged[title])

    section("mise")
    if committed_mise:
        if rc := write_committed_glue(root, cli=bool(bins)):
            return rc
    elif use_mise:
        mise_step(root, kit_home, cli=bool(bins))
    else:
        print(paint("  skipped - pass --with-mise to wire the docs:* tasks", Color.DIM))

    section("Git")
    _integrate_gitignore(root, use_mise, committed_mise)

    section("Next steps")
    for line in _next_steps(bins, use_mise or committed_mise, committed_mise):
        print(line)
    return 0


def _bin_step(name: str, info: dict[str, str], committed: bool) -> str:
    recipe = info["recipe"]
    if recipe == Recipe.KDL:
        return f"    {name}: contract ready -> mise run docs:refresh"
    if recipe == Recipe.PYTHON and committed:
        return (
            f"    {name}: `mise run cli:spec` regenerates"
            f" cli/{name}.usage.kdl from {info['app']}"
        )
    if recipe == Recipe.PYTHON:
        return (
            f'    {name}: uv add --dev "docs-kit @ {KIT_GIT_URL}@v{__version__}"'
            " then `docs-kit init --with-mise --committed`"
            " (or a cli:spec task running `uv run docs-kit spec`)"
        )
    if recipe == Recipe.GO:
        return (
            f"    {name}: add the --usage-spec hidden flag "
            "(cobra_usage) and a cli:spec task (recipe in cli-standard.md)"
        )
    return (
        f"    {name}: hand-write cli/{name}.usage.kdl + extras "
        "(recipe in cli-standard.md)"
    )


def _next_steps(bins: Bins, use_mise: bool, committed: bool) -> list[str]:
    if use_mise:
        steps = [
            "  mise run docs:refresh   regenerate the reference pages",
            "  mise run docs:build     build the site, then commit",
        ]
    else:
        steps = [
            f"  {REGEN_CMD}    regenerate the reference pages",
            "  docs-kit serve      preview with live reload",
        ]
    dim: list[str] = []
    if committed:
        dim += [
            "  committed glue: the docs:* + cli:spec tasks live in mise.toml",
            "  (edit nothing there by hand: `docs-kit check` gates its drift)",
        ]
    if bins:
        dim += [
            "  CLI reference pipeline (usage): every <bin>.md renders from",
            "  cli/<bin>.usage.kdl - see docs/references/cli-standard.md:",
            *(_bin_step(n, bins[n], committed) for n in sorted(bins)),
        ]
    return steps + [paint(line, Color.DIM) for line in dim]
