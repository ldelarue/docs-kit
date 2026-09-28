"""Generate and drift-check a Zensical docs site from openapi.json and Usage CLI specs.

Pipelines are autodetected in the target repo: the API pipeline when
openapi.json (or --spec) exists, the CLI pipeline when cli/*.usage.kdl, a
Typer console script, or spf13/cobra in go.mod does. Typical flow: `init`
once, `refresh` after changing the code, `check` in CI and git hooks.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from . import __version__, render_cli
from .layout import API_SPEC_DEFAULT
from .pipeline import cmd_check, cmd_refresh, cmd_spec
from .scaffold import cmd_init
from .serve import DEFAULT_HOST, DEFAULT_PORT, FREE_PORTS, cmd_build, cmd_serve
from .shim import cmd_pull_tasks, default_kit_home

# cli/docs-kit.usage.kdl is GENERATED from this metadata (`mise run cli:spec`):
# the help strings here ARE the docs - edit the code, never the committed KDL.

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

Root = Annotated[str, typer.Argument(help=ROOT_HELP)]
Spec = Annotated[str | None, typer.Option(help=SPEC_HELP)]
BinNames = Annotated[list[str] | None, typer.Option(help=BIN_HELP)]
NoApi = Annotated[bool, typer.Option("--no-api/--api", help=NO_API_HELP)]
NoCli = Annotated[bool, typer.Option("--no-cli/--cli", help=NO_CLI_HELP)]

app = typer.Typer(help=__doc__, add_completion=False)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"docs-kit {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    # NOT named "version": usage-spec-typer would render its default as the
    # contract's version node ("Version: False")
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
    root: Root = ".",
    spec: Spec = None,
    bin: BinNames = None,
    no_api: NoApi = False,
    no_cli: NoCli = False,
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
            docs_kit or default_kit_home(),
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
    root: Root = ".",
    bin: BinNames = None,
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
    no_cli: NoCli = False,
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
def render_cmd(root: Root = ".") -> NoReturn:
    """render docs/references/cli/<bin>.md from the committed usage contracts"""
    raise typer.Exit(render_cli.cmd_render(Path(root).resolve()))


@app.command()
def refresh(
    root: Root = ".",
    spec: Spec = None,
    bin: BinNames = None,
    no_api: NoApi = False,
    no_cli: NoCli = False,
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
    root: Root = ".",
    spec: Spec = None,
    bin: BinNames = None,
    no_api: NoApi = False,
    no_cli: NoCli = False,
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
def pull_tasks_cmd(root: Root = ".") -> NoReturn:
    """pin the .docs-kit task layer to this CLI's version"""
    raise typer.Exit(cmd_pull_tasks(Path(root).resolve(), default_kit_home()))


@app.command()
def serve(
    root: Root = ".",
    port: Annotated[
        int | None,
        typer.Option(
            help=f"exact port to bind (default: $DOCS_PORT, else prefer {DEFAULT_PORT}, "
            "then first free port in $FREE_PORT_MIN-$FREE_PORT_MAX, "
            f"{FREE_PORTS[0]}-{FREE_PORTS[1]} by default)"
        ),
    ] = None,
    host: Annotated[
        str, typer.Option(help=f"bind address (default: {DEFAULT_HOST})")
    ] = DEFAULT_HOST,
) -> NoReturn:
    """serve the docs with live reload (Zensical)"""
    raise typer.Exit(cmd_serve(Path(root).resolve(), port, host))


@app.command()
def build(root: Root = ".") -> NoReturn:
    """build the static site into site/ (Zensical)"""
    raise typer.Exit(cmd_build(Path(root).resolve()))


def main(argv: list[str] | None = None) -> int:
    """Console entry: run the Typer app; the return value is the exit code.

    cmd_* raise SystemExit for hard errors (message on stderr, code 1);
    typer.Exit carries per-command codes; click usage errors print usage and
    exit 2. typer vendors its click fork, so those are matched by attributes.
    """
    try:
        # non-standalone click RETURNS typer.Exit's code instead of raising it
        rc = app(args=argv, prog_name="docs-kit", standalone_mode=False)
    except typer.Exit as exc:
        return int(exc.exit_code)
    except typer.Abort:
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as exc:
        show = getattr(exc, "show", None)
        code = getattr(exc, "exit_code", None)
        if callable(show) and isinstance(code, int) and not isinstance(code, bool):
            show()
            sys.exit(code)
        raise
    return rc if isinstance(rc, int) and not isinstance(rc, bool) else 0


if __name__ == "__main__":
    sys.exit(main())
