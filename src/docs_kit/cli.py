"""docs-kit command line: init / refresh / check / pull-tasks / serve.

Doc generation is pure file I/O; the only subprocesses anywhere are the
task-layer syncs (init's best-effort shim update and `pull-tasks`), which
shell out to git to keep the pinned shared/mise payload at this CLI's tag,
and `serve`, which runs Zensical's live-reload server (PATH first, uvx else).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tomllib
from pathlib import Path

from . import __version__, render
from .generator import generate_endpoints_page

REGEN_CMD = "docs-kit refresh"

VENDORED_SPEC = "docs/reference/openapi.json"
SWAGGER_PAGE = "docs/reference/swagger.html"
API_PAGE = "docs/references/api.md"
ENDPOINTS_PAGE = "docs/references/endpoints.md"

ZENSONFIG = "zensical.toml"
ZENSICAL_VERSION = "0.0.62"
WORKFLOW = ".github/workflows/docs.yml"
GITIGNORE_ENTRIES = ("site/", ".cache/")
MISE_GITIGNORE_ENTRIES = (".docs-kit/", "mise.local.toml")

DEFAULT_SHIM = ".docs-kit"
MISE_LOCAL = "mise.local.toml"
DOCS_SNIPPET = "{{ vars.docs_kit }}/shared/mise/docs.toml"
MISE_BLOCK_MARK = re.compile(r"^\s*docs_kit\s*=", re.MULTILINE)
KIT_REPO_URL = "git@github.com:ldelarue/docs-kit.git"

RED, YELLOW, CYAN, BOLD, DIM = "31", "33", "36", "1", "2"


def _c(text: str, code: str) -> str:
    """ANSI-color text only for an interactive, non-NO_COLOR stdout."""
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
        return f"\033[{code}m{text}\033[0m"
    return text


def _section(title: str) -> None:
    print(_c(f"\n{title}", BOLD))


def _default_kit_home() -> str:
    """--docs-kit flag > DOCS_KIT env > .docs-kit shim default.

    A running kit checkout does NOT become the default: `init` always wires
    the pulled layer, so running the CLI from source (`uv run --project`)
    behaves exactly like the installed wheel. Clone installs are explicit:
    `--docs-kit /path/to/docs-kit` or the DOCS_KIT env.
    """
    return os.environ.get("DOCS_KIT") or DEFAULT_SHIM


def _is_shim(kit_home: str) -> bool:
    """A relative kit path is a repo-local .docs-kit layer to pull."""
    return not Path(kit_home).is_absolute()


def _read_spec(root: Path, spec_name: str) -> tuple[str, dict]:
    path = root / spec_name
    if not path.is_file():
        sys.exit(
            f"ERROR: {spec_name} not found in {root}. "
            "Export your API spec there first, or point at it with --spec."
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
        (
            root / ENDPOINTS_PAGE,
            generate_endpoints_page(spec, "reference/openapi.json", REGEN_CMD),
        ),
        (root / WORKFLOW, render.render_workflow_yml()),
    ]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def cmd_refresh(root: Path, spec_name: str) -> int:
    for path, content in _generated_outputs(root, spec_name):
        _write(path, content)
        print(f"  {_c('+', CYAN)} {path.relative_to(root)}")
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
        (
            root / "docs" / "tutorials" / "index.md",
            render.render_section_stub("Tutorials"),
        ),
        (root / "docs" / "guides" / "index.md", render.render_section_stub("Guides")),
        (
            root / "docs" / "explanation" / "index.md",
            render.render_section_stub("Explanation"),
        ),
        (
            root / "docs" / "references" / "index.md",
            render.render_section_stub("References"),
        ),
        (root / ZENSONFIG, render.render_zensical_toml(title, description)),
    ]


def pull_tasks(root: Path, shim: str = DEFAULT_SHIM, version: str = __version__) -> str:
    """Pin <root>/<shim> to tag v<version> (sparse: /shared/mise/); returns tag.

    Prefers the kit-sync engine inside a materialized layer (canonical
    implementation, itself versioned by pulls). The inline git fallback
    bootstraps in place with `git init` + `remote add` - `git clone` refuses
    non-empty directories, so a half-created shim dir never blocks it. A tag
    whose payload lacks shared/mise entirely (v0.1.x and older, e.g. a pin
    downgrade) is REJECTED without touching the existing layer. Set
    DOCS_KIT_REPO to pull from another URL (tests).
    """
    ver = str(version).removeprefix("v")  # engine contract: bare version arg
    tag = f"v{ver}"
    url = os.environ.get("DOCS_KIT_REPO") or KIT_REPO_URL
    shim_dir = root / shim
    engine = shim_dir / "shared" / "mise" / "kit-sync"
    env = {**os.environ, "GIT_SSH_COMMAND": "ssh -o BatchMode=yes"}
    if engine.is_file():
        rc = subprocess.run(
            ["sh", str(engine), shim, ver], cwd=root, env=env, check=False
        ).returncode
        if rc != 0:
            raise RuntimeError(
                f"kit-sync exited with {rc} (no payload at {tag}? layer left untouched)"
            )
        return tag

    def git(*args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            err = proc.stderr.strip()
            raise RuntimeError(
                f"`git {' '.join(args)}` failed: {err.splitlines()[-1] if err else 'no output'}"
            )
        return proc.stdout

    bootstrap = not (shim_dir / ".git").exists()
    if bootstrap:
        shim_dir.mkdir(parents=True, exist_ok=True)
        git("init", "-q", shim)
        git("-C", shim, "remote", "add", "origin", url)
    git(
        "-C",
        shim,
        "fetch",
        "-q",
        "--depth",
        "1",
        "origin",
        f"+refs/tags/{tag}:refs/tags/{tag}",
    )
    if not git(
        "-C",
        shim,
        "ls-tree",
        "-r",
        "--name-only",
        f"refs/tags/{tag}^{{}}",
        "--",
        "shared/mise",
    ).strip():
        raise RuntimeError(
            f"tag {tag} ships no task layer (predates shared/mise); "
            "the current layer was left untouched - upgrade the CLI"
        )
    if bootstrap:
        # untracked payload shadows (half-done pulls, init) abort `git checkout`
        # even byte-identical ones; the checkout supplies canonical copies
        shutil.rmtree(shim_dir / "shared", ignore_errors=True)
    git("-C", shim, "-c", "advice.detachedHead=false", "checkout", "-q", tag)
    git(
        "-C",
        shim,
        "-c",
        "advice.detachedHead=false",
        "sparse-checkout",
        "set",
        "--no-cone",
        "/shared/mise/",
    )
    return tag


def cmd_pull_tasks(root: Path, kit_home: str) -> int:
    """docs-kit pull-tasks: bootstrap/update the shim task layer."""
    if not _is_shim(kit_home):
        print(f"checkout install ({kit_home}): nothing to pull")
        return 0
    try:
        tag = pull_tasks(root, kit_home)
    except (RuntimeError, OSError) as exc:
        print(f"ERROR: could not sync the task layer: {exc}", file=sys.stderr)
        return 1
    print(f"docs task layer pinned at {tag}")
    return 0


def _port_free(port: int, host: str) -> bool:
    """True when nothing currently binds host:port (mirrors the serve bind)."""
    family = socket.AF_INET if ":" not in host else socket.AF_INET6
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _lease_port(preferred: int, host: str) -> int:
    """PREFERRED when free, else the first free port in FREE_PORT_MIN..FREE_PORT_MAX."""
    try:
        lo = int(os.environ.get("FREE_PORT_MIN", "8000"))
        hi = int(os.environ.get("FREE_PORT_MAX", "8999"))
    except ValueError:
        sys.exit("ERROR: FREE_PORT_MIN/FREE_PORT_MAX must be integers")
    if not 1 <= lo <= hi <= 65535:
        sys.exit(f"ERROR: bad port range {lo}-{hi}")
    if 1 <= preferred <= 65535 and _port_free(preferred, host):
        return preferred
    for port in range(lo, hi + 1):
        if _port_free(port, host):
            return port
    sys.exit(f"ERROR: no free TCP port in {lo}-{hi} (preferred {preferred} is in use)")


def cmd_serve(root: Path, port: int | None, host: str) -> int:
    """Live-reload serve: pinned port (--port/$DOCS_PORT), else leased (prefers 8010)."""
    pinned = port
    if pinned is None and (env := os.environ.get("DOCS_PORT")):
        if not env.isdigit():
            sys.exit(f"ERROR: DOCS_PORT must be an integer (got: {env})")
        pinned = int(env)
    chosen = pinned if pinned is not None else _lease_port(8010, host)
    dev_addr = f"{host}:{chosen}"
    server = ["zensical", "serve", "--dev-addr", dev_addr]
    if not shutil.which("zensical"):
        server = ["uvx", "--from", f"zensical=={ZENSICAL_VERSION}", *server]
    if not any(shutil.which(c) for c in ("zensical", "uvx")):
        sys.exit("ERROR: neither zensical nor uvx is on PATH; install uv or zensical")
    print(f"serving docs on http://{dev_addr} (Ctrl-C to stop)")
    try:
        return subprocess.run(server, cwd=root, check=False).returncode
    except FileNotFoundError as exc:
        sys.exit(f"ERROR: cannot start the docs server: {exc}")


def _mise_block(kit_home: str) -> str:
    """The comment-free block users copy into their own mise config (opt-in)."""
    return (
        "[vars]\n"
        f'docs_kit = "{kit_home}"\n\n[env]\n'
        'DOCS_KIT = "{{ vars.docs_kit }}"\n\n[task_config]\n'
        f'includes = ["{DOCS_SNIPPET}"]\n'
    )


_LEGACY_MISE_RE = re.compile(
    r"^\s*(docs_kit\s*=|DOCS_KIT\s*=)|docs\.toml|docs:(?:pull-tasks|kit-sync)|### docs "
)


def _report_legacy_mise_lines(root: Path) -> None:
    """Point at old init-generated .mise.toml lines; never rewrite the file."""
    path = root / ".mise.toml"
    if not path.is_file():
        return
    hits = [
        ln
        for ln in path.read_text(encoding="utf-8").splitlines()
        if _LEGACY_MISE_RE.search(ln)
    ]
    if not hits:
        return
    print(
        _c(
            "cleanup - old docs-kit lines in .mise.toml (init never writes\n"
            "  .mise.toml anymore; remove these by hand):",
            RED,
        )
    )
    for ln in hits:
        print(f"    {ln.strip()}")
    print('    (tables above: also delete their "description"/"run" body lines)')


def _mise_opt_in(root: Path) -> str:
    """The user's mise config(s) as pasted, if any - read-only, never written."""
    text = ""
    for name in (MISE_LOCAL, ".mise.toml", "mise.toml"):
        path = root / name
        if path.is_file():
            text += path.read_text(encoding="utf-8")
    return text


def _ensure_mise_local(root: Path, block: str) -> bool:
    """Add the opt-in keys to mise.local.toml, touching nothing else.

    - absent (no docs-kit keys in any mise config) -> created with the block
    - present, block already in verbatim           -> untouched
    - present, docs-kit keys present but stale     -> NEVER rewritten (a
      hand-edited/stale file only gets the printed replace hint)
    - present, no docs-kit keys at all (simple)    -> block APPENDED iff the
      merged text re-parses as TOML (no duplicate [vars]/[env]/[task_config]
      headers); otherwise untouched and left for manual paste

    Returns True when the docs-kit keys are in place afterwards.
    """
    path = root / MISE_LOCAL
    if not path.exists():
        if MISE_BLOCK_MARK.search(_mise_opt_in(root)):
            return False
        _write(path, block)
        print(_c(f"  {MISE_LOCAL}: created with the docs-kit keys (auto-loaded)", CYAN))
        return True
    text = path.read_text(encoding="utf-8")
    if block.strip() in text or MISE_BLOCK_MARK.search(text):
        return block.strip() in text
    merged = text.rstrip("\n") + "\n\n" + block
    if not _valid_toml(merged):
        return False
    _write(path, merged)
    print(
        _c(
            f"  {MISE_LOCAL}: docs-kit keys appended (existing config left as-is)",
            CYAN,
        )
    )
    return True


def _valid_toml(text: str) -> bool:
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return False
    return True


def _print_mise_next_steps(root: Path, block: str) -> None:
    current = _mise_opt_in(root)
    shown = None
    if not MISE_BLOCK_MARK.search(current):
        shown = _c(
            "  next step - copy-paste this block into mise.local.toml (init can\n"
            "  only append it when your config has none of the [vars]/[env]/[task_config]\n"
            "  tables yet); or merge its three keys into the tables you already have:",
            CYAN,
        )
    elif block.strip() not in current:
        shown = _c(
            "  note - the docs-kit keys in your mise config are OUTDATED or hand-edited;\n"
            "  replace them with:",
            YELLOW,
        )
    if shown:
        print(shown)
        print(block.rstrip("\n"))
        print(
            _c(
                "  (keep only ONE [vars], [env] and [task_config] header each - a duplicate\n"
                "   is invalid TOML and mise then skips the whole file)",
                YELLOW,
            )
        )


def _mise_step(root: Path, kit_home: str) -> None:
    _report_legacy_mise_lines(root)
    block = _mise_block(kit_home)
    # only point mise at the include once it can resolve it: a checkout
    # provides shared/mise straight away, a shim once its pull landed (or
    # when DOCS_KIT_SKIP_PULL runs init without syncing - nothing to create)
    layer_ready = not _is_shim(kit_home)
    if _is_shim(kit_home) and not os.environ.get("DOCS_KIT_SKIP_PULL"):
        try:
            tag = pull_tasks(root, kit_home)
            print(f"  task layer: {kit_home}/ shared/mise pinned at {tag}")
            layer_ready = True
        except (RuntimeError, OSError) as exc:
            print(_c(f"  WARNING: task layer sync failed: {exc}", YELLOW))
            print("  docs:* tasks stay unavailable/reverted until the pull succeeds;")
            print("  retry with `docs-kit pull-tasks` (init itself completed fine).")
    if layer_ready:
        _ensure_mise_local(root, block)
    _print_mise_next_steps(root, block)


def _integrate_gitignore(root: Path, use_mise: bool) -> None:
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    entries = GITIGNORE_ENTRIES + (MISE_GITIGNORE_ENTRIES if use_mise else ())
    added = [e for e in entries if e not in lines]
    if not added:
        print(_c(f"  .gitignore already covers {', '.join(entries)}", DIM))
        return
    text = text.rstrip("\n")
    if text:
        text += "\n"
    text += "\n".join(added) + "\n"
    _write(path, text)
    print(f"  {_c('+', CYAN)} .gitignore {', '.join(added)}")


def _report_group(title: str, written: list[str], unchanged: list[str]) -> None:
    """One init section: the files just written, then a count of the current ones."""
    _section(title)
    for rel in written:
        print(f"  {_c('+', CYAN)} {rel}")
    if unchanged:
        noun = "file" if len(unchanged) == 1 else "files"
        print(_c(f"  {len(unchanged)} {noun} already current", DIM))


def cmd_init(
    root: Path, spec_name: str, force: bool, kit_home: str, use_mise: bool = False
) -> int:
    """Install or repair the docs integration (idempotent).

    - missing files                             -> written
    - byte-identical files                      -> skipped
    - existing files that differ (hand edits)   -> only overwritten with --force
    - mise.local.toml absent (and no opt-in in other mise configs, and the
      task layer ready)   -> created with the opt-in keys (git-ignored)
    - mise.local.toml / .mise.toml present      -> NEVER written or modified;
      the block is printed for manual copy-paste/merge, and legacy generated
      lines in .mise.toml are reported for manual removal
    - mise mode (--with-mise) additionally prints the opt-in mise.local.toml
      block when it could not be auto-created and, for shim installs, pins
      shared/mise into <kit-home>/
      (DOCS_KIT_SKIP_PULL=1 skips the sync; checkout installs never pull)
    """
    groups = {
        "Scaffold": _scaffold_files(root, spec_name),
        "Generated": _generated_outputs(root, spec_name),
    }
    plan: list[tuple[Path, str]] = []
    written: dict[str, list[str]] = {}
    unchanged: dict[str, list[str]] = {}
    conflicts: list[str] = []
    gen_conflicts: list[str] = []
    for title, files in groups.items():
        written[title], unchanged[title] = [], []
        for path, content in files:
            rel = str(path.relative_to(root))
            if not path.exists() or (
                force and path.read_text(encoding="utf-8") != content
            ):
                plan.append((path, content))
                written[title].append(rel)
            elif path.read_text(encoding="utf-8") == content:
                unchanged[title].append(rel)
            elif title == "Generated":
                gen_conflicts.append(rel)
            else:
                conflicts.append(rel)
    if conflicts or gen_conflicts:
        parts = [
            "ERROR: existing files differ from what docs-kit would generate (not touched):"
        ]
        for rel in gen_conflicts:
            parts.append(f"  generated: {rel}   -> fix with `{REGEN_CMD}` instead")
        for rel in conflicts:
            parts.append(f"  hand-written: {rel}")
        parts.append("Review them, or re-run with --force to overwrite.")
        sys.exit("\n".join(parts))

    print(_c(f"docs-kit {__version__} · init", BOLD))
    print(_c(f"  repo {root}   spec {spec_name}", DIM))
    for path, content in plan:
        _write(path, content)
    for title in groups:
        _report_group(title, written[title], unchanged[title])

    _section("mise")
    if use_mise:
        _mise_step(root, kit_home)
    else:
        print(_c("  skipped - pass --with-mise to wire the docs:* tasks", DIM))

    _section("Git")
    _integrate_gitignore(root, use_mise)

    _section("Next steps")
    if use_mise:
        print("  mise run docs:refresh   regenerate the reference pages")
        print("  mise run docs:build     build the site, then commit")
    else:
        print(f"  {REGEN_CMD}    regenerate the reference pages")
        print("  docs-kit serve      preview with live reload")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docs-kit", description=__doc__)
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "root", nargs="?", default=".", help="target repo (default: cwd)"
        )
        p.add_argument(
            "--spec", default="openapi.json", help="spec file relative to root"
        )

    p_init = sub.add_parser("init", help="scaffold a Zensical docs site in a repo")
    common(p_init)
    p_init.add_argument("--force", action="store_true", help="overwrite scaffold files")
    p_init.add_argument(
        "--with-mise",
        action="store_true",
        help="add mise integration (pulls the .docs-kit task layer, wires the docs:* tasks)",
    )
    p_init.add_argument(
        "--docs-kit",
        default=_default_kit_home(),
        help="path recorded as vars.docs_kit (default: $DOCS_KIT or the .docs-kit shim; pass a clone path for checkout mode)",
    )
    p_refresh = sub.add_parser("refresh", help="regenerate all generated docs files")
    common(p_refresh)
    p_check = sub.add_parser("check", help="fail if generated docs files are stale")
    common(p_check)
    p_pull = sub.add_parser(
        "pull-tasks", help="pin the .docs-kit task layer to this CLI's version"
    )
    p_pull.add_argument(
        "root", nargs="?", default=".", help="target repo (default: cwd)"
    )
    p_serve = sub.add_parser("serve", help="serve the docs with live reload (Zensical)")
    p_serve.add_argument(
        "root", nargs="?", default=".", help="target repo (default: cwd)"
    )
    p_serve.add_argument(
        "--port",
        type=int,
        default=None,
        help="exact port to bind (default: $DOCS_PORT, else prefer 8010, then first free "
        "port in $FREE_PORT_MIN-$FREE_PORT_MAX)",
    )
    p_serve.add_argument(
        "--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)"
    )

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "init":
        return cmd_init(
            root, args.spec, args.force, args.docs_kit, use_mise=args.with_mise
        )
    if args.command == "serve":
        return cmd_serve(root, args.port, args.host)
    if args.command == "refresh":
        return cmd_refresh(root, args.spec)
    if args.command == "pull-tasks":
        return cmd_pull_tasks(root, _default_kit_home())
    return cmd_check(root, args.spec)


if __name__ == "__main__":
    sys.exit(main())
