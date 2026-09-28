"""docs-kit command line: init / refresh / spec / render / check / pull-tasks / serve.

Doc generation is pure file I/O; the subprocesses are the task-layer syncs
(init's best-effort shim update and `pull-tasks`, which shell out to git),
`serve` (Zensical), and `spec`/`render`: `spec` runs the Typer exporter that
lives inside this package's venv (dependency mode puts docs-kit - and with it
usage-spec-typer - in the CONSUMER's venv, so `uv run docs-kit spec` imports
the repo's own app), and `render` calls the `usage` binary from PATH (pinned
by the committed glue block's `[tools]` line).

What a repository gets is autodetected at every command: an OpenAPI pipeline
when `openapi.json` (or --spec) is there, a CLI-reference pipeline when CLI
evidence is (`cli/*.usage.kdl`, a Typer app in pyproject, cobra in go.mod),
both when both are. `docs-kit init --with-mise --committed` (dependency mode)
writes the committed mise.toml task block; from then on `spec` (contracts),
`render` (reference pages) and `refresh`/`check` (both, plus API pages) run
entirely inside this CLI. Without --committed - and on shim/no-venv consumers
ever - the task layer (`shared/mise/docs.toml` + the `.docs-kit` shim) drives
these same commands and the shared render/usage-spec payload scripts. Drift
is gated by `docs:check` as usual.
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

from . import __version__, render, render_cli, usage_spec
from .generator import generate_endpoints_page
from .render_cli import CLI_DIR, KDL_EXTRA_SUFFIX, KDL_SUFFIX

REGEN_CMD = "docs-kit refresh"

API_SPEC_DEFAULT = "openapi.json"
VENDORED_SPEC = "docs/reference/openapi.json"
SWAGGER_PAGE = "docs/reference/swagger.html"
API_PAGE = "docs/references/api.md"
ENDPOINTS_PAGE = "docs/references/endpoints.md"
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
    if bins:
        _respec_committed(root, bins)
    rc = render_cli.cmd_render(root)
    return rc or 0


def cmd_check(
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
    stale: list[str] = []
    for path, content in _generated_outputs(
        root, spec_name, api, _github_detected(root)
    ):
        rel = str(path.relative_to(root))
        if not path.exists():
            stale.append(f"missing: {rel}")
        elif path.read_text(encoding="utf-8") != content:
            stale.append(f"stale:   {rel}")
    if bins:
        stale += _respec_committed(root, bins, write=False)
    if not no_cli:
        stale += render_cli.check_rendered(root)
    glue_stale, glue_hint = _check_glue(root)
    stale += glue_stale
    if stale:
        print("docs are NOT up to date:", file=sys.stderr)
        for line in stale:
            print(f"  {line}", file=sys.stderr)
        if glue_hint:
            print(glue_hint, file=sys.stderr)
        print(f"run `{REGEN_CMD}` and commit the result.", file=sys.stderr)
        return 1
    print("docs are up to date")
    return 0


def _respec_committed(root: Path, bins: dict, *, write: bool = True) -> list[str]:
    """Regenerate (or, on check, diff-check) the committed contract of every
    python-recipe bin, through usage_spec's merge - the no-task half of the
    `cli:spec` contract (the glue's own `docs-kit spec` writes the same
    bytes; refresh/check must not hand-edit what a task could keep honest).

    - go bins: their core is cobra's (--usage-spec) - this CLI never sips
      the caller's stdin unasked; the glue's `mise run cli:spec` owns them.
    - kdl/unknown bins: the committed contract IS the source, nothing to regen.
    - an app that cannot be imported in THIS venv (shim/tool installs - the
      consumer app lives in ITS venv): skip with a note, same bytes will come
      from the consumer's own task run.
    """
    stale: list[str] = []
    for name, info in sorted(bins.items()):
        if info.get("recipe") != "python" or not info.get("app"):
            continue
        out = root / CLI_DIR / f"{name}{KDL_SUFFIX}"
        extra_path = root / CLI_DIR / f"{name}{KDL_EXTRA_SUFFIX}"
        try:
            app = usage_spec.load_app(info["app"])
        except (ImportError, ModuleNotFoundError):
            print(
                _c(
                    f"  note: {name}: cannot import {info['app']} here - the"
                    " contract is regenerated by `uv run docs-kit spec` (its own venv)",
                    DIM,
                )
            )
            continue
        text = usage_spec.render_text(
            usage_spec.typer_export(app, name),
            extra_path.read_text(encoding="utf-8") if extra_path.is_file() else None,
        )
        if write:
            _emit_contract(out, text, root)
        else:
            rel = (
                out.relative_to(root).as_posix()
                if out.is_relative_to(root)
                else str(out)
            )
            if not out.is_file():
                stale.append(f"missing: {rel}")
            elif out.read_text(encoding="utf-8") != text:
                stale.append(f"stale:   {rel}")
    return stale


def _emit_contract(out: Path, text: str, root: Path) -> None:
    """Byte-stable contract write with refresh-style reporting."""
    rel = out.relative_to(root).as_posix() if out.is_relative_to(root) else str(out)
    current = out.read_text(encoding="utf-8") if out.is_file() else None
    if current == text:
        print(_c(f"  contract current: {rel}", DIM))
        return
    _write(out, text)
    print(f"  {_c('+', CYAN)} {rel}")


def cmd_spec(
    root: Path,
    *,
    bins: list[str] | None = None,
    extra: str | None = None,
    out: str | None = None,
    no_cli: bool = False,
) -> int:
    """docs-kit spec - regenerate cli/<bin>.usage.kdl from the code behind.

    python recipe: introspects the console script's Typer app in THIS venv
    (dependency mode: docs-kit - with usage-spec-typer - lives in the
    consumer's venv, so `uv run docs-kit spec` sees the repo's own app).
    go recipe: the core is cobra's - pipe it (`go run . --usage-spec |
    docs-kit spec --bin mycli`), the same --kdl-stdin contract the payload
    script has always had. kdl/unknown recipes have no code to regen from.
    The curated extra defaults to cli/<bin>.usage.extra.kdl, the write to
    cli/<bin>.usage.kdl (the --extra/--out overrides serve single-contract
    runs and mirror usage-spec.py's flags).
    """
    explicit = list(bins or [])
    _, detected = detect_pipelines(
        root, API_SPEC_DEFAULT, False, explicit, no_api=True, no_cli=no_cli
    )
    targets = {n: detected[n] for n in (explicit or sorted(detected))}
    if not targets:
        print(_c("no CLI evidence (cli/, typer console script, go.mod+cobra)", DIM))
        return 0
    if (extra or out) and len(targets) != 1:
        sys.exit("ERROR: --extra/--out address one contract - name it with --bin NAME")
    for name, info in sorted(targets.items()):
        recipe = info.get("recipe")
        if extra:
            extra_path = Path(extra)
            if not extra_path.is_absolute():
                extra_path = root / extra
            if not extra_path.is_file():
                sys.exit(
                    f"ERROR: extra spec {extra} not found; create it or drop --extra"
                )
            extra_text = extra_path.read_text(encoding="utf-8")
        else:
            extra_path = root / CLI_DIR / f"{name}{KDL_EXTRA_SUFFIX}"
            extra_text = (
                extra_path.read_text(encoding="utf-8") if extra_path.is_file() else None
            )
        target = (root / out) if out else root / CLI_DIR / f"{name}{KDL_SUFFIX}"
        if recipe == "python":
            app = usage_spec.load_app(info["app"])
            _emit_contract(
                target,
                usage_spec.render_text(usage_spec.typer_export(app, name), extra_text),
                root,
            )
        elif recipe == "go" or (
            explicit and recipe == "unknown" and not sys.stdin.isatty()
        ):
            if sys.stdin.isatty():
                sys.exit(
                    f"ERROR: {name}'s core is cobra's - pipe it: "
                    f"`go run . --usage-spec | docs-kit spec --bin {name}`"
                )
            _emit_contract(
                target, usage_spec.render_text(sys.stdin.read(), extra_text), root
            )
        else:
            rel = (
                target.relative_to(root).as_posix()
                if target.is_relative_to(root)
                else str(target)
            )
            print(
                _c(
                    f"  {name}: hand-written contract (no code to regen)"
                    f" - leave {rel} authored",
                    DIM,
                )
            )
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


# ---------------------------------------------------------------------------
# committed mise glue (init --with-mise --committed): dependency mode's task
# set. Unlike the gitignored opt-in block above, THIS block is committed in
# the repo's mise.toml: it is byte-canonical output of _glue_block() below,
# delimited by marker comments, idempotently replaced, and drift-gated by
# every `docs-kit check` (consumers with no block - shim/Go users - are simply
# "not in glue mode": nothing is demanded, nothing is compared).


MISE_COMMITTED_FILES = ("mise.toml", ".mise.toml")
GLUE_BLOCK_END = "# --- end docs-kit tasks ---"
GLUE_MARK = re.compile(
    r"^# --- docs-kit tasks v\S+ ---\n.*?^# --- end docs-kit tasks ---$",
    re.MULTILINE | re.DOTALL,
)
GLUE_VERSION = re.compile(r"^# --- docs-kit tasks v(\S+) ---")
TOOLS_TABLE = re.compile(r"^\[tools\]\s*$", re.MULTILINE)
TOOLS_USAGE_KEY = re.compile(r"^\s*usage\s*=")

_GLUE_TASKS_CLI = (
    (
        '[tasks."cli:spec"]',
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
        f"run = 'mise run docs:refresh && if command -v zensical >/dev/null 2>&1; then zensical build --clean; else uvx --from \"zensical=={ZENSICAL_VERSION}\" zensical build --clean; fi'",
    ),
    (
        '[tasks."docs:serve"]',
        'description = "Serve the docs with live reload on http://127.0.0.1:$PORT (prefers 8010, falls back to the first free port in 8000-8999; pin exactly via DOCS_PORT)"',
        'run = "uv run docs-kit serve"',
    ),
    (
        '[tasks."docs:check"]',
        'description = "Fail when generated docs are stale (CI and git hooks): docs-kit check, then the docs diff must be empty"',
        'run = "uv run docs-kit check && git diff --exit-code -- docs openapi.json cli"',
    ),
)


def _glue_block(cli: bool, has_tools: bool) -> str:
    """The whole marker-delimited block, byte-canonical. [tools] joins the
    block only when the rest of the file has no [tools] table (a duplicate
    table header would be invalid TOML and make mise skip the WHOLE file);
    with one, `usage = "latest"` upserts into the existing table instead.
    cli=False (API-only glue) additionally skips [tools] and cli:spec."""
    lines = [f"# --- docs-kit tasks v{__version__} ---"]
    if cli and not has_tools:
        lines += ["[tools]", 'usage = "latest"', ""]
    for task in (_GLUE_TASKS_CLI if cli else ()) + _GLUE_TASKS_REST:
        lines += [*task, ""]
    lines.append(GLUE_BLOCK_END)
    return "\n".join(lines)


def _glue_task_file(root: Path) -> Path | None:
    """The file holding (or destined to hold) the block: existing marker
    first, else the repo's existing mise config, else mise.toml."""
    marked = next(
        (
            root / name
            for name in MISE_COMMITTED_FILES
            if (root / name).is_file() and GLUE_MARK.search(_read(root / name) or "")
        ),
        None,
    )
    if marked:
        return marked
    return next(
        ((root / name) for name in MISE_COMMITTED_FILES if (root / name).is_file()),
        root / MISE_COMMITTED_FILES[0],
    )


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _glue_split(text: str) -> tuple[str, str | None]:
    """(file text minus the glue block, block or None)."""
    m = GLUE_MARK.search(text)
    if not m:
        return text, None
    return text[: m.start()] + text[m.end() :], m.group(0)


def _tools_usage_missing(stripped: str) -> bool:
    """True when the config has a [tools] table (outside any block, which the
    caller already removed) that lacks a usage key."""
    m = TOOLS_TABLE.search(stripped)
    if m is None:
        return False
    for line in stripped[m.end() :].split("\n"):
        if line.startswith("["):
            return True  # the table ended without ever seeing usage
        if TOOLS_USAGE_KEY.match(line):
            return False
    return True


def _insert_tools_usage(stripped: str) -> str:
    """Right after the [tools] header line (canonical placement; the file is
    re-parse-checked before the merged result is ever written)."""
    m = TOOLS_TABLE.search(stripped)
    if m is None:
        return stripped
    idx = stripped.index("\n", m.start()) + 1
    return stripped[:idx] + 'usage = "latest"\n' + stripped[idx:]


def _write_committed_glue(root: Path, cli: bool) -> int:
    """Write/replace the canonical block in the repo's mise.toml (idempotent:
    re-running with the same kit version is a no-op; the block moves to EOF).
    The whole file must re-parse as TOML before anything is written - this is
    a COMMITTED file; the same _ensure_mise_local caution applies, only
    harsher: a risky merge never lands."""
    path = _glue_task_file(root)
    assert path is not None
    text = _read(path) or ""
    stripped, current = _glue_split(text)
    has_tools = bool(TOOLS_TABLE.search(stripped))
    if has_tools:
        stripped = (
            _insert_tools_usage(stripped)
            if _tools_usage_missing(stripped)
            else stripped
        )
    block = _glue_block(cli, has_tools=has_tools)
    body = stripped.rstrip("\n")
    merged = (body + "\n\n" if body else "") + block + "\n"
    if not _valid_toml(merged):
        print(
            _c(
                f"ERROR: {path.name} + the docs-kit block would not re-parse as "
                "valid TOML - nothing written. Paste this block instead and "
                "check the tables by hand:",
                RED,
            ),
            file=sys.stderr,
        )
        print(block, file=sys.stderr)
        return 1
    if merged == text:
        rel = path.relative_to(root) if path.is_relative_to(root) else path
        print(_c(f"  {rel}: docs-kit task block current (v{__version__})", DIM))
        return 0
    _write(path, merged)
    rel = path.relative_to(root) if path.is_relative_to(root) else path
    verb = "replaced" if current else "written"
    print(f"  {_c('+', CYAN)} {rel}: docs-kit task block {verb} (v{__version__})")
    return 0


def _check_glue(root: Path) -> tuple[list[str], str]:
    """(stale lines, remediation hint) for the committed block. Absent block
    = glue mode not in use (shim / Go / API-shim consumers) -> not stale."""
    stale: list[str] = []
    hint = ""
    for name in MISE_COMMITTED_FILES:
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        _stripped, block = _glue_split(text)
        if block is None:
            continue
        cli = '[tasks."cli:spec"]' in block
        expected = _glue_block(cli, has_tools=bool(TOOLS_TABLE.search(_stripped)))
        current_version = (GLUE_VERSION.match(block.split("\n", 1)[0]) or ["", "?"])[1]
        if block != expected:
            stale.append(
                f"stale:   {name} docs-kit task block (v{current_version} vs"
                f" expected v{__version__} + canonical body)"
            )
            hint = (
                "  the docs-kit task block in "
                f"{name}: run `docs-kit init --with-mise --committed`"
                " (idempotent) or paste the block it prints"
            )
        if _tools_usage_missing(_stripped):
            stale.append(f"stale:   {name} [tools] has no usage key")
            hint = hint or f'  add usage = "latest" under the [tools] table in {name}'
    return stale, hint


def _integrate_gitignore(
    root: Path, use_mise: bool, committed_mise: bool = False
) -> None:
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    if committed_mise:
        # dependency mode owns no shim layer; only personal overrides stay out
        entries: tuple[str, ...] = GITIGNORE_ENTRIES + ("mise.local.toml",)
    else:
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
    committed_mise: bool = False,
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
    - committed glue (--with-mise --committed, dependency mode: docs-kit is
      a dev dep of this repo): write/replace the marker-delimited canonical
      task block in mise.toml (idempotent, TOML-validity-checked; [tools]
      usage joins the block or upserts into an existing table) - no shim, no
      .docs-kit/, no gitignored docs wiring
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
    if committed_mise:
        # dependency mode: the task block is COMMITTED in mise.toml - no shim,
        # no include, no gitignored docs wiring. rc!=0 only when the merged
        # file would not re-parse as TOML (then the plan is printed instead).
        _report_legacy_mise_lines(root)
        rc = _write_committed_glue(root, cli=bool(bins))
        if rc:
            return rc
    elif use_mise:
        _mise_step(root, kit_home, cli=bool(bins))
    else:
        print(_c("  skipped - pass --with-mise to wire the docs:* tasks", DIM))

    _section("Git")
    _integrate_gitignore(root, use_mise, committed_mise)

    _section("Next steps")
    for line in _next_steps(root, bins, use_mise or committed_mise, committed_mise):
        print(line)
    return 0


def _next_steps(
    root: Path,
    bins: dict[str, dict[str, str]],
    use_mise: bool,
    committed: bool = False,
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
    if committed:
        steps += [
            _c(
                "  committed glue: the docs:* + cli:spec tasks live in mise.toml",
                DIM,
            ),
            _c("  (edit nothing there by hand: `docs-kit check` gates its drift)", DIM),
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
                if committed:
                    steps.append(
                        _c(
                            f"    {name}: `mise run cli:spec` regenerates"
                            f" cli/{name}.usage.kdl from {info['app']}",
                            DIM,
                        )
                    )
                else:
                    steps.append(
                        _c(
                            f'    {name}: uv add --dev "docs-kit @'
                            f' git+https://github.com/ldelarue/docs-kit.git@v{__version__}"'
                            " then `docs-kit init --with-mise --committed`"
                            " (or a cli:spec task running `uv run docs-kit spec`)",
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
# metadata by `mise run cli:spec` (`docs-kit spec`, whose Typer export the
# same package provides, merged with usage_spec's extra-file rules)
# - help strings here ARE the docs, edit the code,
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
            help="add mise integration (shim mode: pulls the .docs-kit task "
            "layer and wires the docs:* tasks through mise.local.toml)",
        ),
    ] = False,
    committed: Annotated[
        bool,
        typer.Option(
            "--committed/--no-committed",
            help="with --with-mise: dependency mode - write the canonical "
            "[tools] usage + docs task block into the repo's mise.toml "
            "(committed; requires docs-kit to be a dev dependency here)",
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
    if committed and not with_mise:
        raise typer.BadParameter("--committed needs --with-mise")
    raise typer.Exit(
        cmd_init(
            Path(root).resolve(),
            spec or API_SPEC_DEFAULT,
            force,
            docs_kit or _default_kit_home(),
            use_mise=with_mise,
            committed_mise=committed,
            spec_explicit=spec is not None,
            extra_bins=list(bin or []),
            no_api=no_api,
            no_cli=no_cli,
        )
    )


@app.command()
def spec(
    root: Annotated[str, typer.Argument(help=ROOT_HELP)] = ".",
    bin: Annotated[list[str] | None, typer.Option(help=BIN_HELP)] = None,
    extra: Annotated[
        str | None,
        typer.Option(
            help="curated extra .kdl file (default: cli/<bin>.usage.extra.kdl "
            "when present; single-contract runs only)"
        ),
    ] = None,
    out: Annotated[
        str | None,
        typer.Option(
            help="write the contract here instead of cli/<bin>.usage.kdl "
            "(single-contract runs only)"
        ),
    ] = None,
    no_cli: Annotated[bool, typer.Option("--no-cli/--cli", help=NO_CLI_HELP)] = False,
) -> NoReturn:
    """regenerate cli/<bin>.usage.kdl contracts from the code behind them"""
    raise typer.Exit(
        cmd_spec(
            Path(root).resolve(),
            bins=list(bin or []),
            extra=extra,
            out=out,
            no_cli=no_cli,
        )
    )


@app.command("render")
def render_cmd(
    root: Annotated[str, typer.Argument(help=ROOT_HELP)] = ".",
) -> NoReturn:
    """render docs/references/cli/<bin>.md from the committed usage contracts"""
    raise typer.Exit(render_cli.cmd_render(Path(root).resolve()))


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
