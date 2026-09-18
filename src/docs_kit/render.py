"""Template rendering for generated docs files (stdlib only)."""

from __future__ import annotations

import json
from importlib.resources import files

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


def render_zensical_toml(title: str, description: str) -> str:
    return _asset("zensical.toml.tmpl").format(
        site_name=_toml_str(title),
        site_description=_toml_str(description),
    )


def render_index_page(title: str, description: str) -> str:
    return _asset("index.md.tmpl").format(
        title=title,
        description=description.strip() or "Documentation for this API.",
    )


def render_section_stub(title: str) -> str:
    return _asset("section.md.tmpl").format(title=title)


def render_workflow_yml() -> str:
    return _asset("docs.yml.tmpl")
