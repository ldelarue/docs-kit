"""Template rendering for generated docs files (stdlib only)."""

from __future__ import annotations

import json
from importlib.resources import files

from . import __version__

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
    cli: bool = False,
) -> str:
    bullets = []
    if api:
        bullets.append(
            "- **[API reference](references/api.md)** — interactive Swagger UI plus\n"
            "  generated endpoint tables."
        )
    if cli:
        bullets.append(
            "- **[CLI reference](references/cli/)** — commands, flags and exit codes\n"
            "  rendered from the committed usage specs."
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
                f"| `{name}` | {info.get('recipe', 'unknown')} | "
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
    recipe = info.get("recipe", "unknown")
    if recipe == "python":
        app = info.get("app", "<pkg>.cli:app")
        return (
            f"### `{name}` — Python / Typer\n\n"
            "```toml\n"
            "# mise.toml — regenerate the committed contract\n"
            '[tasks."cli:spec"]\n'
            'description = "Regenerate cli/{name}.usage.kdl from the Typer app"\n'
            'run = \'uv run python "$DOCS_KIT/shared/mise/usage-spec.py" '
            "--typer {app} --bin {name} "
            "--extra cli/{name}.usage.extra.kdl --out cli/{name}.usage.kdl'\n"
            "```\n".format(name=name, app=app)
        )
    if recipe == "go":
        return (
            f"### `{name}` — Go / cobra\n\n"
            "Add the hidden `--usage-spec` flag (cobra_usage) in main.go, then:\n\n"
            "```toml\n"
            '[tasks."cli:spec"]\n'
            'description = "Regenerate cli/{name}.usage.kdl from cobra"\n'
            'run = \'go run . --usage-spec | python "$DOCS_KIT/shared/mise/usage-spec.py" '
            "--kdl-stdin --bin {name} --extra cli/{name}.usage.extra.kdl "
            "--out cli/{name}.usage.kdl'\n"
            "```\n".format(name=name)
        )
    hand = (
        f"### `{name}` — committed spec\n\n"
        f"`cli/{name}.usage.kdl` is the hand-authored contract; run "
        "`usage lint cli/{name}.usage.kdl` after edits."
    )
    if recipe == "unknown":
        hand += " (no framework detected - keep the spec fully hand-written)"
    return hand


def render_section_stub(title: str) -> str:
    return _asset("section.md.tmpl").format(title=title)


def render_workflow_yml() -> str:
    # .replace, not .format: GitHub Actions '${{ }}' expressions are braces.
    return _asset("docs.yml.tmpl").replace("__KIT_VERSION__", __version__)
