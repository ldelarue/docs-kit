"""docs-kit command line: init / refresh / check (pure file I/O)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from . import __version__, render
from .generator import generate_endpoints_page

REGEN_CMD = "mise run docs:refresh"

VENDORED_SPEC = "docs/reference/openapi.json"
SWAGGER_PAGE = "docs/reference/swagger.html"
API_PAGE = "docs/references/api.md"
ENDPOINTS_PAGE = "docs/references/endpoints.md"

ZENSONFIG = "zensical.toml"
WORKFLOW = ".github/workflows/docs.yml"
GITIGNORE_ENTRIES = ("site/", ".cache/")

# Used only when this run is a legacy `uvx --from <local path>` bootstrap (the
# wheel lives under the uv cache but the source tree is a local checkout).
BAKED_KIT_HOME = "/Users/ladelaru/Dev/me/docs-kit"
KIT_HOME_PLACEHOLDER = "PASTE-PATH-TO-DOCS-KIT-CHECKOUT-OR-REMOVE-THIS"


def _default_kit_home() -> str:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists() and (parent / "pyproject.toml").is_file():
            return str(parent)
    if os.environ.get("DOCS_KIT"):
        return os.environ["DOCS_KIT"]
    if ".cache" in str(here) and "/uv/" in str(here):
        return BAKED_KIT_HOME
    return KIT_HOME_PLACEHOLDER


def _read_spec(root: Path, spec_name: str) -> tuple[str, dict]:
    path = root / spec_name
    if not path.is_file():
        sys.exit(
            f"ERROR: {spec_name} not found in {root}. "
            "Generate it first (e.g. `mise run openapi`)."
        )
    text = path.read_text(encoding="utf-8")
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as exc:
        sys.exit(f"ERROR: {path} is not valid JSON: {exc}")
    return text, spec


def _generated_outputs(root: Path, spec_name: str) -> list[tuple[Path, str]]:
    text, spec = _read_spec(root, spec_name)
    info = spec.get("info", {})
    title = info.get("title") or root.resolve().name
    return [
        (root / VENDORED_SPEC, text),
        (root / SWAGGER_PAGE, render.render_swagger_page(title)),
        (root / API_PAGE, render.render_api_page()),
        (root / ENDPOINTS_PAGE, generate_endpoints_page(spec, "reference/openapi.json", REGEN_CMD)),
    ]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def cmd_refresh(root: Path, spec_name: str) -> int:
    for path, content in _generated_outputs(root, spec_name):
        _write(path, content)
        print(f"  wrote {path.relative_to(root)}")
    return 0


def cmd_check(root: Path, spec_name: str) -> int:
    stale: list[str] = []
    for path, content in _generated_outputs(root, spec_name):
        rel = str(path.relative_to(root))
        if not path.exists():
            stale.append(f"missing: {rel}")
        elif path.read_text(encoding="utf-8") != content:
            stale.append(f"stale:   {rel}")
    if stale:
        print("docs are NOT up to date:", file=sys.stderr)
        for line in stale:
            print(f"  {line}", file=sys.stderr)
        print(f"run `{REGEN_CMD}` and commit the result.", file=sys.stderr)
        return 1
    print("docs are up to date")
    return 0


def _scaffold_files(root: Path, spec_name: str) -> list[tuple[Path, str]]:
    _, spec = _read_spec(root, spec_name)
    info = spec.get("info", {})
    title = info.get("title") or root.resolve().name
    description = info.get("description") or ""
    return [
        (root / "docs" / "index.md", render.render_index_page(title, description)),
        (root / "docs" / "tutorials" / "index.md", render.render_section_stub("Tutorials")),
        (root / "docs" / "guides" / "index.md", render.render_section_stub("Guides")),
        (root / "docs" / "explanation" / "index.md", render.render_section_stub("Explanation")),
        (root / "docs" / "references" / "index.md", render.render_section_stub("References")),
        (root / ZENSONFIG, render.render_zensical_toml(title, description)),
        (root / WORKFLOW, render.render_workflow_yml()),
    ]


def _insert_under_table(text: str, header_re: str, line: str) -> tuple[str, bool]:
    """Insert `line` right below the first line matching header_re."""
    m = re.search(rf"(?m)^{header_re}$", text)
    if not m:
        return text, False
    idx = m.end() + 1
    if text[idx : idx + len(line)] == line:
        return text, True
    return text[:idx] + line + "\n" + text[idx:], True


def _integrate_mise(root: Path, kit_home: str, spec_name: str) -> None:
    path = root / ".mise.toml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if 'docs:refresh' in text:
        print("  .mise.toml: docs tasks already present, left untouched")
        return

    # uv must exist (tasks use uvx fallbacks; the pypi backend installs via uv).
    if not re.search(r'(?m)^\s*uv\s*=', text):
        header = r'\[tools\]'
        if re.search(rf"(?m)^{header}$", text):
            text, _ = _insert_under_table(text, header, 'uv = "latest"')
        else:
            text = '[tools]\nuv = "latest"\n\n' + text

    tasks = f'''
### docs (block generated by docs-kit init; delete to remove) ###
# Model: docs-kit lives in a LOCAL CLONE recorded below as $DOCS_KIT.
# Tasks call `uv run --no-dev --project "$DOCS_KIT"` (project installs
# revalidate by source mtime; a bare `uvx --from <path>` would cache stale
# wheels). No PyPI, no version pins: the clone is the version.
# Update docs-kit by hand, whenever you want:
#   cd $DOCS_KIT && git pull                    # latest from the main branch
#   cd $DOCS_KIT && git checkout vX.Y.Z         # stay on a tagged release
#   cd <this repo> && mise run docs:refresh && git diff docs/   # review result
# Optional: `uv tool install "$DOCS_KIT"` puts `docs-kit` on PATH so the
# `command -v` branches here take over (re-run it after each pull).
# CI: the docs workflow needs a clone too -- it checks out the kit repo and
# overrides DOCS_KIT; see the comment at the top of .github/workflows/docs.yml.
# ($DOCS_KIT may use ~/ but NOT for init defaults, which are written absolute.)

[tasks."docs:init"]
description = "Re-scaffold the docs site (refuses existing files without --force)"
run = 'DOCS_KIT="${{DOCS_KIT/#\\~/$HOME}}"; if command -v docs-kit >/dev/null 2>&1; then docs-kit init; else uv run --no-dev --project "$DOCS_KIT" docs-kit init; fi'

[tasks."docs:refresh"]
description = "Re-export the OpenAPI spec and regenerate reference pages"
run = 'mise run openapi && DOCS_KIT="${{DOCS_KIT/#\\~/$HOME}}"; if command -v docs-kit >/dev/null 2>&1; then docs-kit refresh; else uv run --no-dev --project "$DOCS_KIT" docs-kit refresh; fi'

[tasks."docs:build"]
description = "Refresh, then build the static site into site/"
run = 'mise run docs:refresh && if command -v zensical >/dev/null 2>&1; then zensical build --clean; else uvx --from "zensical==0.0.62" zensical build --clean; fi'

[tasks."docs:check"]
description = "Fail when generated docs are stale (for CI and git hooks)"
run = 'mise run openapi && DOCS_KIT="${{DOCS_KIT/#\\~/$HOME}}"; if command -v docs-kit >/dev/null 2>&1; then docs-kit check; else uv run --no-dev --project "$DOCS_KIT" docs-kit check; fi && git diff --exit-code -- docs openapi.json'
'''

    if re.search(r"(?m)^\[env\]$", text):
        text, _ = _insert_under_table(text, r"\[env\]", f'DOCS_KIT = "{kit_home}"')
    else:
        tasks = tasks.replace(
            "[tasks.",
            f'[env]\nDOCS_KIT = "{kit_home}"\n\n[tasks.',
            1,
        )
    text = text.rstrip("\n") + "\n" + tasks
    _write(path, text)
    print("  updated .mise.toml (env + docs tasks)")
    if kit_home == KIT_HOME_PLACEHOLDER:
        print(
            f"  WARNING: $DOCS_KIT is set to '{KIT_HOME_PLACEHOLDER}' because this\n"
            "  init run could not detect a docs-kit checkout. Replace that value\n"
            "  with the absolute path of your docs-kit clone (or remove the line\n"
            "  if you installed the binary on PATH). See docs-kit README."
        )


def _integrate_gitignore(root: Path) -> None:
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    added = [e for e in GITIGNORE_ENTRIES if e not in lines]
    if not added:
        print("  .gitignore: already covers", ", ".join(GITIGNORE_ENTRIES))
        return
    text = text.rstrip("\n")
    if text:
        text += "\n"
    text += "\n".join(added) + "\n"
    _write(path, text)
    print(f"  .gitignore: added {', '.join(added)}")


def cmd_init(root: Path, spec_name: str, force: bool, kit_home: str) -> int:
    scaffold = _scaffold_files(root, spec_name) + _generated_outputs(root, spec_name)
    if not force:
        existing = [str(p.relative_to(root)) for p, _ in scaffold if p.exists()]
        if existing or (root / ".mise.toml").exists() and "docs:refresh" in (root / ".mise.toml").read_text(encoding="utf-8"):
            msg = "ERROR: already initialized (existing: " + ", ".join(existing) + "). Use --force to overwrite."
            sys.exit(msg)
    for path, content in scaffold:
        _write(path, content)
        print(f"  wrote {path.relative_to(root)}")
    _integrate_gitignore(root)
    _integrate_mise(root, kit_home, spec_name)
    print("done. Next: `mise run docs:refresh` to verify, then commit.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docs-kit", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("root", nargs="?", default=".", help="target repo (default: cwd)")
        p.add_argument("--spec", default="openapi.json", help="spec file relative to root")

    p_init = sub.add_parser("init", help="scaffold a Zensical docs site in a repo")
    common(p_init)
    p_init.add_argument("--force", action="store_true", help="overwrite scaffold files")
    p_init.add_argument("--docs-kit", default=_default_kit_home(), help="path recorded as $DOCS_KIT")
    p_refresh = sub.add_parser("refresh", help="regenerate all generated docs files")
    common(p_refresh)
    p_check = sub.add_parser("check", help="fail if generated docs files are stale")
    common(p_check)

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "init":
        return cmd_init(root, args.spec, args.force, args.docs_kit)
    if args.command == "refresh":
        return cmd_refresh(root, args.spec)
    return cmd_check(root, args.spec)


if __name__ == "__main__":
    sys.exit(main())
