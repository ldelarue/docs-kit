"""Committed mise task block (`init --with-mise --committed`, dependency mode).

The block lives in the repo's committed mise.toml: byte-canonical output of
glue_block(), delimited by marker comments, idempotently replaced, and
drift-gated by every `docs-kit check`. A repo without the block is simply
not in glue mode: nothing is demanded, nothing is compared.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from . import __version__
from .files import read, rel, valid_toml, write
from .layout import USAGE_TOOL_PIN
from .serve import DEFAULT_HOST, DEFAULT_PORT, FREE_PORTS
from .term import Color, added, paint

MISE_COMMITTED_FILES = ("mise.toml", ".mise.toml")
GLUE_BLOCK_END = "# --- end docs-kit tasks ---"
GLUE_MARK = re.compile(
    r"^# --- docs-kit tasks v\S+ ---\n.*?^# --- end docs-kit tasks ---$",
    re.MULTILINE | re.DOTALL,
)
GLUE_VERSION = re.compile(r"^# --- docs-kit tasks v(\S+) ---")
TOOLS_TABLE = re.compile(r"^\[tools\]\s*$", re.MULTILINE)
TOOLS_USAGE_KEY = re.compile(r"^\s*usage\s*=")
CLI_SPEC_TASK = '[tasks."cli:spec"]'

_GLUE_TASKS_CLI = (
    (
        CLI_SPEC_TASK,
        'description = "Regenerate cli/*.usage.kdl contracts from the code (docs-kit spec)"',
        'run = "uv run docs-kit spec"',
    ),
)
_GLUE_TASKS_REST = (
    (
        '[tasks."docs:refresh"]',
        'description = "Regenerate everything detected: contracts, reference pages, API pages when an openapi.json is here"',
        'run = "uv run docs-kit refresh"',
    ),
    (
        '[tasks."docs:build"]',
        'description = "Refresh, then build the static site into site/"',
        'run = "mise run docs:refresh && uv run docs-kit build"',
    ),
    (
        '[tasks."docs:serve"]',
        (
            f'description = "Serve the docs with live reload on http://{DEFAULT_HOST}:$PORT'
            f" (prefers {DEFAULT_PORT}, falls back to the first free port in"
            f' {FREE_PORTS[0]}-{FREE_PORTS[1]}; pin exactly via DOCS_PORT)"'
        ),
        'run = "uv run docs-kit serve"',
    ),
    (
        '[tasks."docs:check"]',
        'description = "Fail when generated docs are stale (CI and git hooks): docs-kit check, then the docs diff must be empty"',
        'run = "uv run docs-kit check && git diff --exit-code -- docs openapi.json cli"',
    ),
)


def glue_block(cli: bool, has_tools: bool) -> str:
    """The whole marker-delimited block, byte-canonical. [tools] joins the
    block only when the rest of the file has none (a duplicate table header
    is invalid TOML and mise skips the WHOLE file); otherwise the usage pin
    upserts into the existing table. cli=False skips [tools] and cli:spec."""
    lines = [f"# --- docs-kit tasks v{__version__} ---"]
    if cli and not has_tools:
        lines += ["[tools]", USAGE_TOOL_PIN, ""]
    for task in (_GLUE_TASKS_CLI if cli else ()) + _GLUE_TASKS_REST:
        lines += [*task, ""]
    lines.append(GLUE_BLOCK_END)
    return "\n".join(lines)


def _task_file(root: Path) -> Path:
    """The file holding (or destined to hold) the block: existing marker
    first, else the repo's existing mise config, else mise.toml."""
    existing = [root / name for name in MISE_COMMITTED_FILES if (root / name).is_file()]
    for path in existing:
        if GLUE_MARK.search(read(path) or ""):
            return path
    return existing[0] if existing else root / MISE_COMMITTED_FILES[0]


def _split(text: str) -> tuple[str, str | None]:
    """(file text minus the glue block, block or None)."""
    m = GLUE_MARK.search(text)
    if not m:
        return text, None
    return text[: m.start()] + text[m.end() :], m.group(0)


def _tools_usage_missing(stripped: str) -> bool:
    """True when the config (block removed) has a [tools] table without usage."""
    m = TOOLS_TABLE.search(stripped)
    if m is None:
        return False
    for line in stripped[m.end() :].split("\n"):
        if line.startswith("["):
            return True
        if TOOLS_USAGE_KEY.match(line):
            return False
    return True


def _insert_tools_usage(stripped: str) -> str:
    """The usage pin right after the [tools] header line."""
    m = TOOLS_TABLE.search(stripped)
    if m is None:
        return stripped
    idx = stripped.index("\n", m.start()) + 1
    return stripped[:idx] + USAGE_TOOL_PIN + "\n" + stripped[idx:]


def write_committed_glue(root: Path, cli: bool) -> int:
    """Write/replace the canonical block (idempotent; the block moves to EOF).
    The whole file must re-parse as TOML first: a risky merge of a COMMITTED
    file never lands - the block is printed for a manual paste instead."""
    path = _task_file(root)
    text = read(path) or ""
    stripped, current = _split(text)
    has_tools = bool(TOOLS_TABLE.search(stripped))
    if has_tools and _tools_usage_missing(stripped):
        stripped = _insert_tools_usage(stripped)
    block = glue_block(cli, has_tools=has_tools)
    body = stripped.rstrip("\n")
    merged = (body + "\n\n" if body else "") + block + "\n"
    if not valid_toml(merged):
        print(
            paint(
                f"ERROR: {path.name} + the docs-kit block would not re-parse as "
                "valid TOML - nothing written. Paste this block instead and "
                "check the tables by hand:",
                Color.RED,
            ),
            file=sys.stderr,
        )
        print(block, file=sys.stderr)
        return 1
    where = rel(path, root)
    if merged == text:
        print(
            paint(f"  {where}: docs-kit task block current (v{__version__})", Color.DIM)
        )
        return 0
    write(path, merged)
    verb = "replaced" if current else "written"
    added(f"{where}: docs-kit task block {verb} (v{__version__})")
    return 0


def check_glue(root: Path) -> tuple[list[str], str]:
    """(stale lines, remediation hint) for the committed block."""
    stale: list[str] = []
    hint = ""
    for name in MISE_COMMITTED_FILES:
        path = root / name
        if not path.is_file():
            continue
        stripped, block = _split(path.read_text(encoding="utf-8"))
        if block is None:
            continue
        expected = glue_block(
            CLI_SPEC_TASK in block, has_tools=bool(TOOLS_TABLE.search(stripped))
        )
        if block != expected:
            m = GLUE_VERSION.match(block)
            stale.append(
                f"stale:   {name} docs-kit task block (v{m[1] if m else '?'} vs"
                f" expected v{__version__} + canonical body)"
            )
            hint = (
                f"  the docs-kit task block in {name}: run `docs-kit init"
                " --with-mise --committed` (idempotent) or paste the block it prints"
            )
        if _tools_usage_missing(stripped):
            stale.append(f"stale:   {name} [tools] has no usage key")
            hint = hint or f"  add {USAGE_TOOL_PIN} under the [tools] table in {name}"
    return stale, hint
