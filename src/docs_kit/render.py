"""Template rendering for generated docs files (stdlib only)."""

from __future__ import annotations

import json
from importlib.resources import files

from . import __version__
from .detect import Recipe

_ASSETS = files("docs_kit") / "assets"


def _asset(name: str) -> str:
    return _ASSETS.joinpath(name).read_text(encoding="utf-8")


def _toml_str(value: str) -> str:
    # JSON string escaping is a subset of TOML basic-string escaping.
    return json.dumps(value)


def render_api_page() -> str:
    return _asset("api.md.tmpl")


def render_swagger_page(title: str) -> str:
    return _asset("swagger.html.tmpl").format(title=title)


def _cli_nav_entry(bins: dict[str, dict[str, str]]) -> str:
    """Nav entry for generated CLI pages + the standard (empty when no CLI)."""
    if not bins:
        return ""
    entries = ", ".join(f'"references/cli/{b}.md"' for b in sorted(bins))
    return '{"CLI" = [' + entries + ', "references/cli-standard.md"]},'


def render_zensical_toml(
    title: str,
    description: str,
    api: bool = True,
    bins: dict[str, dict[str, str]] | None = None,
) -> str:
    bins = bins or {}
    api_nav = (
        '{"API" = ["references/api.md", "references/endpoints.md"]},' if api else ""
    )
    cli_nav = _cli_nav_entry(bins)
    if api_nav and cli_nav:
        cli_nav = "\n    " + cli_nav
    return _asset("zensical.toml.tmpl").format(
        site_name=_toml_str(title),
        site_description=_toml_str(description),
        api_nav=api_nav,
        cli_nav=cli_nav,
    )


def render_index_page(
    title: str,
    description: str,
    api: bool = True,
    bins: dict[str, dict[str, str]] | None = None,
) -> str:
    bullets = []
    if api:
        bullets.append(
            "- **[API reference](references/api.md)** — interactive Swagger UI plus\n"
            "  generated endpoint tables."
        )
    bins = bins or {}
    # link the real pages (there is no page at the directory itself);
    # same targets as the zensical nav gets
    for name in sorted(bins):
        label = "CLI reference" if len(bins) == 1 else f"`{name}` reference"
        bullets.append(
            f"- **[{label}](references/cli/{name}.md)** — commands, flags and\n"
            "  exit codes rendered from the committed usage spec."
        )
    return _asset("index.md.tmpl").format(
        title=title,
        description=description.strip() or f"Documentation for {title}.",
        refs_lines="\n".join(bullets),
    )


def render_cli_standard_page(
    root_name: str,
    bins: dict[str, dict[str, str]],
    cli_page_dir: str = "references/cli",
) -> str:
    # .replace, not .format: the examples are KDL/TOML full of braces.
    return (
        _asset("cli-standard.md.tmpl")
        .replace("@@TITLE@@", root_name)
        .replace(
            "@@BINS@@",
            "\n".join(
                f"| `{name}` | {info.get('recipe', Recipe.UNKNOWN)} | "
                f"{cli_page_dir}/{name}.md | cli/{name}.usage.kdl |"
                for name, info in sorted(bins.items())
            ),
        )
        .replace(
            "@@RECIPES@@",
            "\n\n".join(_bin_recipe(name, info) for name, info in sorted(bins.items())),
        )
    )


def _bin_recipe(name: str, info: dict[str, str]) -> str:
    recipe = info.get("recipe", Recipe.UNKNOWN)
    if recipe == Recipe.PYTHON:
        return (
            f"### `{name}` — Python / Typer (dependency mode)\n\n"
            "docs-kit (which carries the Typer→usage exporter) is a dev\n"
            "dependency of this repo - `docs-kit init --with-mise --committed` turns\n"
            "it into a mise task. The exporter imports the Typer app and merges the\n"
            "curated extra through the venv the CLI is declared in.\n\n"
            "```toml\n"
            "# mise.toml — regenerate the committed contract\n"
            '[tasks."cli:spec"]\n'
            'description = "Regenerate cli/{name}.usage.kdl from the Typer app"\n'
            "run = 'uv run docs-kit spec --bin {name}'\n"
            "```\n"
            "`--extra`/`--out` default to the cli/{name}.usage.extra.kdl /\n"
            "cli/{name}.usage.kdl conventions shown above - pass them only to\n"
            "deviate. `docs-kit init --with-mise --committed` writes the canonical\n"
            "task block for you.\n".format(name=name)
        )
    if recipe == Recipe.GO:
        return (
            f"### `{name}` — Go / cobra\n\n"
            "Add the hidden `--usage-spec` flag (cobra_usage) in main.go, then:\n\n"
            "```toml\n"
            '[tasks."cli:spec"]\n'
            'description = "Regenerate cli/{name}.usage.kdl from cobra"\n'
            "run = 'go run . --usage-spec | docs-kit spec --bin {name}'\n"
            "```\n".format(name=name)
        )
    hand = (
        f"### `{name}` — committed spec\n\n"
        f"`cli/{name}.usage.kdl` is the hand-authored contract; run "
        f"`usage lint cli/{name}.usage.kdl` after edits."
    )
    if recipe == Recipe.UNKNOWN:
        hand += " (no framework detected - keep the spec fully hand-written)"
    return hand


def render_section_stub(title: str) -> str:
    return _asset("section.md.tmpl").format(title=title)


def render_workflow_yml() -> str:
    # .replace, not .format: GitHub Actions '${{ }}' expressions are braces.
    return _asset("docs.yml.tmpl").replace("__KIT_VERSION__", __version__)
