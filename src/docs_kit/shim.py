"""Shim mode: the pulled `.docs-kit` task layer + the gitignored mise.local.toml opt-in.

For Go / no-venv consumers. `.docs-kit/` is a sparse checkout of this repo's
/shared/mise/ at the tag matching the installed CLI; mise.local.toml includes
its docs.toml. Existing mise configs are never rewritten: the block is only
created or safely appended, otherwise printed for a manual paste.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .files import valid_toml, write
from .layout import MISE_LOCAL, USAGE_TOOL_PIN
from .term import Color, paint

DEFAULT_SHIM = ".docs-kit"
KIT_REPO_URL = "git@github.com:ldelarue/docs-kit.git"
PAYLOAD_DIR = "shared/mise"
DOCS_SNIPPET = "{{ vars.docs_kit }}/" + PAYLOAD_DIR + "/docs.toml"
MISE_BLOCK_MARK = re.compile(r"^\s*docs_kit\s*=", re.MULTILINE)
MISE_CONFIGS = (MISE_LOCAL, ".mise.toml", "mise.toml")


def default_kit_home() -> str:
    """DOCS_KIT env > .docs-kit shim (a running checkout is never implied)."""
    return os.environ.get("DOCS_KIT") or DEFAULT_SHIM


def is_shim(kit_home: str) -> bool:
    """A relative kit path is a repo-local layer to pull; absolute = a clone."""
    return not Path(kit_home).is_absolute()


def pull_tasks(root: Path, shim: str = DEFAULT_SHIM, version: str = __version__) -> str:
    """Pin <root>/<shim> to tag v<version> (sparse: /shared/mise/); returns tag.

    Bootstraps in place with `git init` + `remote add` (`git clone` refuses
    non-empty directories). A tag without shared/mise is REJECTED before the
    existing layer is touched. DOCS_KIT_REPO overrides the URL (tests).
    """
    tag = f"v{str(version).removeprefix('v')}"
    url = os.environ.get("DOCS_KIT_REPO") or KIT_REPO_URL
    shim_dir = root / shim
    env = {**os.environ, "GIT_SSH_COMMAND": "ssh -o BatchMode=yes"}

    def git(*args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", shim, *args],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            err = proc.stderr.strip()
            last = err.splitlines()[-1] if err else "no output"
            raise RuntimeError(f"`git {' '.join(args)}` failed: {last}")
        return proc.stdout

    bootstrap = not (shim_dir / ".git").exists()
    if bootstrap:
        shim_dir.mkdir(parents=True, exist_ok=True)
        git("init", "-q")
        git("remote", "add", "origin", url)
    git("fetch", "-q", "--depth", "1", "origin", f"+refs/tags/{tag}:refs/tags/{tag}")
    if not git(
        "ls-tree", "-r", "--name-only", f"refs/tags/{tag}^{{}}", "--", PAYLOAD_DIR
    ).strip():
        raise RuntimeError(
            f"tag {tag} ships no task layer (predates {PAYLOAD_DIR}); "
            "the current layer was left untouched - upgrade the CLI"
        )
    if bootstrap:
        # untracked payload leftovers abort `git checkout`, even identical ones
        shutil.rmtree(shim_dir / PAYLOAD_DIR.split("/")[0], ignore_errors=True)
    detached = ("-c", "advice.detachedHead=false")
    git(*detached, "checkout", "-q", tag)
    git(*detached, "sparse-checkout", "set", "--no-cone", f"/{PAYLOAD_DIR}/")
    return tag


def cmd_pull_tasks(root: Path, kit_home: str) -> int:
    """docs-kit pull-tasks: bootstrap/update the shim task layer."""
    if not is_shim(kit_home):
        print(f"checkout install ({kit_home}): nothing to pull")
        return 0
    try:
        tag = pull_tasks(root, kit_home)
    except (RuntimeError, OSError) as exc:
        print(f"ERROR: could not sync the task layer: {exc}", file=sys.stderr)
        return 1
    print(f"docs task layer pinned at {tag}")
    return 0


def mise_block(kit_home: str, cli: bool = False) -> str:
    """The comment-free opt-in block; [tools] usage only with a CLI pipeline."""
    block = (
        "[vars]\n"
        f'docs_kit = "{kit_home}"\n\n[env]\n'
        'DOCS_KIT = "{{ vars.docs_kit }}"\n\n[task_config]\n'
        f'includes = ["{DOCS_SNIPPET}"]\n'
    )
    if cli:
        block += f"\n[tools]\n{USAGE_TOOL_PIN}\n"
    return block


def _mise_configs_text(root: Path) -> str:
    return "".join(
        (root / name).read_text(encoding="utf-8")
        for name in MISE_CONFIGS
        if (root / name).is_file()
    )


def _ensure_mise_local(root: Path, block: str) -> None:
    """Create mise.local.toml, or append the block when it has no docs-kit
    keys yet and the merge still parses as TOML; never rewrite anything."""
    path = root / MISE_LOCAL
    if not path.exists():
        if MISE_BLOCK_MARK.search(_mise_configs_text(root)):
            return
        write(path, block)
        print(
            paint(
                f"  {MISE_LOCAL}: created with the docs-kit keys (auto-loaded)",
                Color.CYAN,
            )
        )
        return
    text = path.read_text(encoding="utf-8")
    if MISE_BLOCK_MARK.search(text):
        return
    merged = text.rstrip("\n") + "\n\n" + block
    if valid_toml(merged):
        write(path, merged)
        print(
            paint(
                f"  {MISE_LOCAL}: docs-kit keys appended (existing config left as-is)",
                Color.CYAN,
            )
        )


def _print_next_steps(root: Path, block: str) -> None:
    current = _mise_configs_text(root)
    if not MISE_BLOCK_MARK.search(current):
        print(
            paint(
                "  next step - copy-paste this block into mise.local.toml (init can\n"
                "  only append it when your config has none of the [vars]/[env]/[task_config]\n"
                "  tables yet); or merge its three keys into the tables you already have:",
                Color.CYAN,
            )
        )
    elif block.strip() not in current:
        print(
            paint(
                "  note - the docs-kit keys in your mise config are OUTDATED or hand-edited;\n"
                "  replace them with:",
                Color.YELLOW,
            )
        )
    else:
        return
    print(block.rstrip("\n"))
    print(
        paint(
            "  (keep only ONE [vars], [env], [task_config] and [tools] header each - a\n"
            "   duplicate is invalid TOML and mise then skips the whole file)",
            Color.YELLOW,
        )
    )


def mise_step(root: Path, kit_home: str, cli: bool = False) -> None:
    """init --with-mise (shim mode): pull the layer, then wire mise.local.toml."""
    block = mise_block(kit_home, cli=cli)
    # only point mise at the include once it resolves; DOCS_KIT_SKIP_PULL skips the pull
    layer_ready = not is_shim(kit_home)
    if is_shim(kit_home) and not os.environ.get("DOCS_KIT_SKIP_PULL"):
        try:
            tag = pull_tasks(root, kit_home)
            print(f"  task layer: {kit_home}/ {PAYLOAD_DIR} pinned at {tag}")
            layer_ready = True
        except (RuntimeError, OSError) as exc:
            print(paint(f"  WARNING: task layer sync failed: {exc}", Color.YELLOW))
            print("  docs:* tasks stay unavailable/reverted until the pull succeeds;")
            print("  retry with `docs-kit pull-tasks` (init itself completed fine).")
    if layer_ready:
        _ensure_mise_local(root, block)
    _print_next_steps(root, block)
