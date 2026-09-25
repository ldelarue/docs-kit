"""docs-kit command line: init / refresh / check / pull-tasks / serve.

Doc generation is pure file I/O; the only subprocesses anywhere are the
task-layer syncs (init's best-effort shim update and `pull-tasks`), which
shell out to git to keep the pinned shared/mise payload at this CLI's tag,
and `serve`, which runs Zensical's live-reload server (PATH first, uvx else).

What a repository gets is autodetected at every command: an OpenAPI pipeline
when `openapi.json` (or --spec) is there, a CLI-reference pipeline when CLI
evidence is (`cli/*.usage.kdl`, a Typer app in pyproject, cobra in go.mod),
both when both are. The CLI pipeline's pages are rendered by the task layer
(`shared/mise/render-cli-docs` via mise, calling the `usage` binary);
this CLI owns the scaffold those pages need: the Zensical nav, the CLI
standard page and the index; drift is gated by `docs:check` as usual.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from . import __version__, render
from .generator import generate_endpoints_page

REGEN_CMD = "docs-kit refresh"

API_SPEC_DEFAULT = "openapi.json"
VENDORED_SPEC = "docs/reference/openapi.json"
SWAGGER_PAGE = "docs/reference/swagger.html"
API_PAGE = "docs/references/api.md"
ENDPOINTS_PAGE = "docs/references/endpoints.md"
CLI_DIR = "cli"
KDL_SUFFIX = ".usage.kdl"
KDL_EXTRA_SUFFIX = ".usage.extra.kdl"
CLI_PAGE_DIR = "docs/references/cli"
CLI_STANDARD_PAGE = "docs/references/cli-standard.md"

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


# ---------------------------------------------------------------------------
# autodetection: every command works from what the repository actually holds


def _kdl_bins(root: Path) -> dict[str, str]:
    """Bins with a committed contract already: cli/<bin>.usage.kdl."""
    bins: dict[str, str] = {}
    cli_dir = root / CLI_DIR
    if cli_dir.is_dir():
        for path in sorted(cli_dir.glob(f"*{KDL_SUFFIX}")):
            if path.name.endswith(KDL_EXTRA_SUFFIX):  # paranoid: extra is *.kdl too
                continue
            bins[path.name[: -len(KDL_SUFFIX)]] = "kdl"
    return bins


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
            # :app when the script already targets a .cli module (standard §recipe 1)
            app_spec = (
                f"{module}.cli:app" if not module.endswith(".cli") else f"{module}:app"
            )
            bins[name] = app_spec
    return bins


def _cobra_bins(root: Path) -> dict[str, str]:
    """module basename of a go.mod requiring spf13/cobra."""
    gomod = root / "go.mod"
    if not gomod.is_file() or b"github.com/spf13/cobra" not in gomod.read_bytes():
        return {}
    for line in gomod.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("module "):
            return {line.split("/")[-1].strip(): "go"}
    return {}


def detect_pipelines(
    root: Path,
    spec_name: str,
    spec_explicit: bool,
    extra_bins: list[str],
    *,
    no_api: bool = False,
    no_cli: bool = False,
) -> tuple[bool, dict[str, dict[str, str]]]:
    """(api_active, bins) with bins[bin] = {recipe: python|go|kdl|unknown,
    app: "<pkg>.cli:app" when known}."""
    if spec_explicit and not (root / spec_name).is_file():
        sys.exit(
            f"ERROR: --spec {spec_name} not found in {root} (pass a path or drop it)."
        )
    api_active = (root / spec_name).is_file() and not no_api
    if no_cli:
        return api_active, {}

    bins: dict[str, dict[str, str]] = {}
    for name, app in _typer_bins(root).items():
        bins[name] = {"recipe": "python", "app": app}
    for name in _cobra_bins(root):
        bins.setdefault(name, {"recipe": "go"})
    for name in _kdl_bins(root):
        bins.setdefault(
            name, {"recipe": "kdl"}
        )  # committed contract, generator maybe unknown
    for name in extra_bins:
        bins.setdefault(name, {"recipe": "unknown"})
    return api_active, bins


def _github_detected(root: Path) -> bool:
    """True on clones/pull-request checkouts of a GitHub repository (and on
    GitHub Actions itself); the workflow file is meaningless everywhere else,
    e.g. the st.ovh.net-hosted fleets - init/check must own it only here."""
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


def _generated_outputs(
    root: Path, spec_name: str, api: bool, github: bool
) -> list[tuple[Path, str]]:
    """The kit-owned generated set for THIS repository: API pages when an
    OpenAPI spec is present; the CI workflow only on GitHub (the consumer's
    Pages deploy lives there - a workflow on a Stash-hosted repo is a lie)."""
    out: list[tuple[Path, str]] = []
    if api:
        text, spec = _read_spec(root, spec_name)
        info = spec.get("info", {})
        title = info.get("title") or root.resolve().name
        out += [
            (root / VENDORED_SPEC, text),
            (root / SWAGGER_PAGE, render.render_swagger_page(title)),
            (root / API_PAGE, render.render_api_page()),
            (
                root / ENDPOINTS_PAGE,
                generate_endpoints_page(spec, "reference/openapi.json", REGEN_CMD),
            ),
        ]
    if github:
        out.append((root / WORKFLOW, render.render_workflow_yml()))
    return out


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def cmd_refresh(
    root: Path,
    spec_name: str = API_SPEC_DEFAULT,
    *,
    spec_explicit: bool = False,
    extra_bins: list[str] | None = None,
    no_api: bool = False,
    no_cli: bool = False,
) -> int:
    api, bins = detect_pipelines(
        root, spec_name, spec_explicit, extra_bins or [], no_api=no_api, no_cli=no_cli
    )
    for path, content in _generated_outputs(
        root, spec_name, api, _github_detected(root)
    ):
        _write(path, content)
        print(f"  {_c('+', CYAN)} {path.relative_to(root)}")
    if bins and not (root / CLI_STANDARD_PAGE).is_file():
        print(
            _c(
                f"  note: CLI{'' if len(bins) == 1 else 's'} detected"
                f" ({', '.join(sorted(bins))}) - run `docs-kit init` to scaffold"
                " the reference pages, `mise run docs:refresh` to render them",
                DIM,
            )
        )
    return 0


def cmd_check(
    root: Path,
    spec_name: str = API_SPEC_DEFAULT,
    *,
    spec_explicit: bool = False,
    extra_bins: list[str] | None = None,
    no_api: bool = False,
    no_cli: bool = False,
) -> int:
    api, _bins = detect_pipelines(
        root, spec_name, spec_explicit, extra_bins or [], no_api=no_api, no_cli=no_cli
    )
    stale: list[str] = []
    for path, content in _generated_outputs(
        root, spec_name, api, _github_detected(root)
    ):
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


def _scaffold_files(
    root: Path, spec_name: str, api: bool, bins: dict[str, dict[str, str]]
) -> list[tuple[Path, str]]:
    title, description = "", ""
    if api:
        _, spec = _read_spec(root, spec_name)
        info = spec.get("info", {})
        title = info.get("title") or root.resolve().name
        description = info.get("description") or ""
    else:
        title = root.resolve().name
    files: list[tuple[Path, str]] = [
        (
            root / "docs" / "index.md",
            render.render_index_page(
                title, description, api=api, cli=bool(bins), bins=bins
            ),
        ),
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
        (
            root / ZENSONFIG,
            render.render_zensical_toml(title, description, api=api, bins=bins),
        ),
    ]
    if bins:
        files.append(
            (
                root / CLI_STANDARD_PAGE,
                render.render_cli_standard_page(
                    root.resolve().name, bins, cli_page_dir="references/cli"
                ),
            )
        )
    return files


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


def _mise_block(kit_home: str, cli: bool = False) -> str:
    """The comment-free block users copy into their own mise config (opt-in).

    [tools] usage is only for repos with a CLI pipeline: `usage` renders the
    reference pages from the KDL contracts (shared/mise/render-cli-docs).
    """
    block = (
        "[vars]\n"
        f'docs_kit = "{kit_home}"\n\n[env]\n'
        'DOCS_KIT = "{{ vars.docs_kit }}"\n\n[task_config]\n'
        f'includes = ["{DOCS_SNIPPET}"]\n'
    )
    if cli:
        block += '\n[tools]\nusage = "latest"\n'
    return block


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
                "  (keep only ONE [vars], [env], [task_config] and [tools] header each - a\n"
                "   duplicate is invalid TOML and mise then skips the whole file)",
                YELLOW,
            )
        )


def _mise_step(root: Path, kit_home: str, cli: bool = False) -> None:
    _report_legacy_mise_lines(root)
    block = _mise_block(kit_home, cli=cli)
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
    root: Path,
    spec_name: str = API_SPEC_DEFAULT,
    force: bool = False,
    kit_home: str = DEFAULT_SHIM,
    use_mise: bool = False,
    *,
    spec_explicit: bool = False,
    extra_bins: list[str] | None = None,
    no_api: bool = False,
    no_cli: bool = False,
) -> int:
    """Install or repair the docs integration (idempotent).

    Pipelines are autodetected: API pages for an OpenAPI spec when present,
    a CLI reference scaffold when `cli/*.usage.kdl`, a Typer console-script,
    or cobra-in-go.mod evidence exists (or --bin names one). With neither in
    sight init refuses rather than scaffolding an empty site.

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
    api, bins = detect_pipelines(
        root, spec_name, spec_explicit, extra_bins or [], no_api=no_api, no_cli=no_cli
    )
    # a GitHub-flavored environment is not a documentation source: without
    # anything real to render, init refuses everywhere (also in CI/Actions)
    if not api and not bins:
        sys.exit(
            "ERROR: no documentation source detected: no openapi.json, and no CLI "
            "evidence (cli/<bin>.usage.kdl, a typer console-script in pyproject.toml, "
            "or spf13/cobra in go.mod); name a CLI with --bin BIN, or pass --spec."
        )
    github = _github_detected(root)
    detected = ", ".join(
        ([f"API ({spec_name})"] if api else [])
        + sorted(bins)
        + (["workflow:github"] if github else [])
    )
    groups = {
        "Scaffold": _scaffold_files(root, spec_name, api, bins),
        "Generated": _generated_outputs(root, spec_name, api, github),
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
    print(_c(f"  repo {root}   detected {detected}", DIM))
    for path, content in plan:
        _write(path, content)
    for title in groups:
        _report_group(title, written[title], unchanged[title])

    _section("mise")
    if use_mise:
        _mise_step(root, kit_home, cli=bool(bins))
    else:
        print(_c("  skipped - pass --with-mise to wire the docs:* tasks", DIM))

    _section("Git")
    _integrate_gitignore(root, use_mise)

    _section("Next steps")
    for line in _next_steps(root, bins, use_mise):
        print(line)
    return 0


def _next_steps(
    root: Path, bins: dict[str, dict[str, str]], use_mise: bool
) -> list[str]:
    steps = []
    if use_mise:
        steps += [
            "  mise run docs:refresh   regenerate the reference pages",
            "  mise run docs:build     build the site, then commit",
        ]
    else:
        steps += [
            f"  {REGEN_CMD}    regenerate the reference pages",
            "  docs-kit serve      preview with live reload",
        ]
    if bins:
        steps += [
            _c(
                "  CLI reference pipeline (usage): every <bin>.md renders from",
                DIM,
            ),
            _c("  cli/<bin>.usage.kdl - see docs/references/cli-standard.md:", DIM),
        ]
        for name in sorted(bins):
            info = bins[name]
            if info["recipe"] == "kdl":
                steps.append(
                    _c(f"    {name}: contract ready -> mise run docs:refresh", DIM)
                )
            elif info["recipe"] == "python":
                steps.append(
                    _c(
                        f"    {name}: add usage-spec-typer to [dependency-groups] dev "
                        'and a "cli:spec" task (recipe in cli-standard.md)',
                        DIM,
                    )
                )
            elif info["recipe"] == "go":
                steps.append(
                    _c(
                        f"    {name}: add the --usage-spec hidden flag "
                        "(cobra_usage) and a cli:spec task (recipe in cli-standard.md)",
                        DIM,
                    )
                )
            else:
                steps.append(
                    _c(
                        f"    {name}: hand-write cli/{name}.usage.kdl + extras "
                        "(recipe in cli-standard.md)",
                        DIM,
                    )
                )
    return steps


# ---------------------------------------------------------------------------
# The interface contract. cli/docs-kit.usage.kdl is GENERATED from this
# metadata by `mise run cli:spec` (shared/mise/usage-spec.py plus the
# usage-spec-typer package) - help strings here ARE the docs, edit the code,
# never the committed KDL (docs/references/cli-standard.md).

ROOT_HELP = "target repo (default: cwd)"
SPEC_HELP = (
    "OpenAPI spec file relative to root (default: openapi.json when present; "
    "the API pipeline is skipped when it is not)"
)
BIN_HELP = (
    "name a CLI binary explicitly (repeatable); otherwise CLIs are detected "
    "from cli/*.usage.kdl, typer console scripts, or go.mod+cobra"
)
NO_API_HELP = "never run the OpenAPI pipeline, even when openapi.json is present"
NO_CLI_HELP = "never run the CLI-reference pipeline, even when CLI evidence is present"

app = typer.Typer(help=__doc__, add_completion=False)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"docs-kit {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    # NOT named "version": usage-spec-typer takes the default of any
    # version-named root param as the contract's version node (bool False
    # would render as "Version: False" on the page); the flag stays --version
    show_version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="show program's version number and exit",
            callback=_show_version,
            is_eager=True,
        ),
    ] = False,
) -> None:
    pass


@app.command()
def init(
    root: Annotated[str, typer.Argument(help=ROOT_HELP)] = ".",
    spec: Annotated[str | None, typer.Option(help=SPEC_HELP)] = None,
    bin: Annotated[list[str] | None, typer.Option(help=BIN_HELP)] = None,
    no_api: Annotated[bool, typer.Option("--no-api/--api", help=NO_API_HELP)] = False,
    no_cli: Annotated[bool, typer.Option("--no-cli/--cli", help=NO_CLI_HELP)] = False,
    force: Annotated[
        bool, typer.Option("--force/--no-force", help="overwrite scaffold files")
    ] = False,
    with_mise: Annotated[
        bool,
        typer.Option(
            "--with-mise/--no-with-mise",
            help="add mise integration (pulls the .docs-kit task layer, "
            "wires the docs:* tasks)",
        ),
    ] = False,
    docs_kit: Annotated[
        str | None,
        typer.Option(
            help="path recorded as vars.docs_kit (default: $DOCS_KIT or "
            "the .docs-kit shim; pass a clone path for checkout mode)"
        ),
    ] = None,
) -> NoReturn:
    """scaffold a Zensical docs site in a repo"""
    raise typer.Exit(
        cmd_init(
            Path(root).resolve(),
            spec or API_SPEC_DEFAULT,
            force,
            docs_kit or _default_kit_home(),
            use_mise=with_mise,
            spec_explicit=spec is not None,
            extra_bins=list(bin or []),
            no_api=no_api,
            no_cli=no_cli,
        )
    )


@app.command()
def refresh(
    root: Annotated[str, typer.Argument(help=ROOT_HELP)] = ".",
    spec: Annotated[str | None, typer.Option(help=SPEC_HELP)] = None,
    bin: Annotated[list[str] | None, typer.Option(help=BIN_HELP)] = None,
    no_api: Annotated[bool, typer.Option("--no-api/--api", help=NO_API_HELP)] = False,
    no_cli: Annotated[bool, typer.Option("--no-cli/--cli", help=NO_CLI_HELP)] = False,
) -> NoReturn:
    """regenerate all generated docs files"""
    raise typer.Exit(
        cmd_refresh(
            Path(root).resolve(),
            spec or API_SPEC_DEFAULT,
            spec_explicit=spec is not None,
            extra_bins=list(bin or []),
            no_api=no_api,
            no_cli=no_cli,
        )
    )


@app.command()
def check(
    root: Annotated[str, typer.Argument(help=ROOT_HELP)] = ".",
    spec: Annotated[str | None, typer.Option(help=SPEC_HELP)] = None,
    bin: Annotated[list[str] | None, typer.Option(help=BIN_HELP)] = None,
    no_api: Annotated[bool, typer.Option("--no-api/--api", help=NO_API_HELP)] = False,
    no_cli: Annotated[bool, typer.Option("--no-cli/--cli", help=NO_CLI_HELP)] = False,
) -> NoReturn:
    """fail if generated docs files are stale"""
    raise typer.Exit(
        cmd_check(
            Path(root).resolve(),
            spec or API_SPEC_DEFAULT,
            spec_explicit=spec is not None,
            extra_bins=list(bin or []),
            no_api=no_api,
            no_cli=no_cli,
        )
    )


@app.command("pull-tasks")
def pull_tasks_cmd(
    root: Annotated[str, typer.Argument(help=ROOT_HELP)] = ".",
) -> NoReturn:
    """pin the .docs-kit task layer to this CLI's version"""
    raise typer.Exit(cmd_pull_tasks(Path(root).resolve(), _default_kit_home()))


@app.command()
def serve(
    root: Annotated[str, typer.Argument(help=ROOT_HELP)] = ".",
    port: Annotated[
        int | None,
        typer.Option(
            help="exact port to bind (default: $DOCS_PORT, else prefer 8010, "
            "then first free port in $FREE_PORT_MIN-$FREE_PORT_MAX)"
        ),
    ] = None,
    host: Annotated[
        str, typer.Option(help="bind address (default: 127.0.0.1)")
    ] = "127.0.0.1",
) -> NoReturn:
    """serve the docs with live reload (Zensical)"""
    raise typer.Exit(cmd_serve(Path(root).resolve(), port, host))


def main(argv: list[str] | None = None) -> int:
    """Console entry: run the Typer app; the return value is the exit code.

    cmd_* keep raising SystemExit directly for hard errors (message on
    stderr, code 1); typer.Exit carries per-command codes (0 included);
    click UsageError-style failures (no/unknown subcommand, bad values)
    print usage and exit 2 like the old argparse front end. typer vendors
    its click fork, so those are caught by their public attributes, not by
    an isinstance against the separately installed click.
    """
    try:
        app(args=argv, prog_name="docs-kit", standalone_mode=False)
    except typer.Exit as exc:  # per-command exit code, --version included
        return int(exc.exit_code)
    except typer.Abort:  # Ctrl-C during a prompt
        sys.exit(130)
    except SystemExit:  # cmd_* hard errors keep their own code/message
        raise
    except Exception as exc:  # click UsageError family (vendored): show + exit
        show = getattr(exc, "show", None)
        code = getattr(exc, "exit_code", None)
        if callable(show) and isinstance(code, int) and not isinstance(code, bool):
            show()
            sys.exit(code)
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
