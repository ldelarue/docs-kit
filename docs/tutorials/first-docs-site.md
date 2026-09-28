# Your first docs site

In this tutorial we will take a tiny Python command-line tool, give it a
documentation site whose CLI reference is generated from the code, preview it
in the browser, and then break the docs on purpose to watch docs-kit catch it.

By the end you will have:

- [x] a `hello` CLI built with Typer
- [x] a Zensical site with a generated `hello` reference page
- [x] a live preview at `http://127.0.0.1:8010`
- [x] a `docs:check` task that fails when the reference no longer matches the code

## Before we start

We need three tools on the machine. Install any that are missing:

| Tool | Check | Install |
| --- | --- | --- |
| git | `git --version` | your package manager |
| uv | `uv --version` | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) |
| mise | `mise --version` | [mise.jdx.dev](https://mise.jdx.dev/getting-started.html) |

That is all: mise will fetch everything else for us.

## Create the CLI

Let's create a fresh project and add Typer to it:

```bash
uv init --package hello
cd hello
uv add typer
```

`uv init` created a git repository and a `src/hello/` package for us. Let's
add a small Typer app to it. Create `src/hello/cli.py`:

```python title="src/hello/cli.py"
import typer

app = typer.Typer(help="Say hello from the command line.")


@app.command()
def greet(
    name: str = typer.Argument(help="who to greet"),
    shout: bool = typer.Option(False, help="print the greeting in capitals"),
) -> None:
    """greet someone by name"""
    text = f"Hello, {name}!"
    typer.echo(text.upper() if shout else text)


@app.command()
def version() -> None:
    """print the version"""
    typer.echo("hello 0.1.0")
```

Then point the `hello` console script at this app in `pyproject.toml`:

```toml title="pyproject.toml" hl_lines="2"
[project.scripts]
hello = "hello.cli:app"
```

Let's try it:

```console
$ uv run hello greet Ada
Hello, Ada!
```

Our CLI works. Notice that every argument and option carries a `help=`
string: those strings are about to become our documentation.

## Add docs-kit

We add docs-kit as a **dev dependency**, so it lives in the project's own
virtual environment next to the CLI it documents:

```bash
uv add --dev "docs-kit @ git+https://github.com/ldelarue/docs-kit.git@latest"
```

!!! tip "Pin a release in real projects"

    `@latest` always follows the newest release, which keeps this tutorial
    current. For your own repositories, pin a release tag (`@vX.Y.Z`); see
    [How to install docs-kit](../guides/install.md).

## Scaffold the site

Now we ask docs-kit to set up the documentation, and to write its mise tasks
into a committed `mise.toml`:

```bash
uv run docs-kit init --with-mise --committed
```

The output tells us what it found and what it wrote (`X.Y.Z` is the
docs-kit version we installed):

```text
docs-kit X.Y.Z · init
  repo /tmp/hello   detected hello

Scaffold
  + docs/index.md
  + zensical.toml
  + docs/references/cli-standard.md

Generated

mise
  + mise.toml: docs-kit task block written (vX.Y.Z)

Git
  + .gitignore site/, .cache/, mise.local.toml
...
```

docs-kit **detected** `hello`: it read `pyproject.toml`, saw Typer in the
dependencies and a console script, and switched the CLI pipeline on. Let's
look at the `mise.toml` it created:

```toml title="mise.toml"
# --- docs-kit tasks vX.Y.Z ---
[tools]
usage = "latest"

[tasks."cli:spec"]
description = "Regenerate cli/*.usage.kdl contracts from the code (docs-kit spec)"
run = "uv run docs-kit spec"

[tasks."docs:refresh"]
description = "Regenerate everything detected: contracts, reference pages, API pages when an openapi.json is here"
run = "uv run docs-kit refresh"

# ... docs:build, docs:serve, docs:check ...
# --- end docs-kit tasks ---
```

Every task is a one-liner calling `uv run docs-kit …`. We will only ever use
them through `mise run`.

## Generate the reference

Let's trust the new config, install the tools it pins, and generate the docs:

```bash
mise trust
mise install
mise run docs:refresh
```

```text
[docs:refresh] $ uv run docs-kit refresh
No issues found.
  + cli/hello.usage.kdl
  rendered docs/references/cli/hello.md
```

Two new files appeared:

- `cli/hello.usage.kdl` is the **contract**: a machine-readable description
  of every command and flag, extracted from the Typer app.
- `docs/references/cli/hello.md` is the **page** rendered from that contract.

Open `docs/references/cli/hello.md` and you will find our help strings,
including `print the greeting in capitals`.

## Preview the site

Let's see the site:

```bash
mise run docs:serve
```

```text
serving docs on http://127.0.0.1:8010 (Ctrl-C to stop)
```

Open [http://127.0.0.1:8010](http://127.0.0.1:8010) in the browser. Under the
**References** tab there is a **CLI** section with the `hello` page: usage,
arguments, flags, one section per command.

Leave the server running and press ++ctrl+c++ when you are done looking.

## Commit the baseline

docs-kit compares the docs against what is committed, so let's commit
everything we have:

```bash
git add -A
git commit -m "docs: first docs site"
```

## Break the docs on purpose

Now let's change the code **without** touching the docs. In
`src/hello/cli.py`, change the help of `--shout`:

```python title="src/hello/cli.py" hl_lines="3"
def greet(
    name: str = typer.Argument(help="who to greet"),
    shout: bool = typer.Option(False, help="SHOUT the greeting"),
) -> None:
```

And run the gate that CI will run:

```bash
mise run docs:check
```

```text
[docs:check] $ uv run docs-kit check && git diff --exit-code -- docs openapi.json cli
No issues found.
docs are NOT up to date:
  stale:   cli/hello.usage.kdl
run `docs-kit refresh` and commit the result.
[docs:check] ERROR task failed
```

The check failed. The published reference still says "print the greeting in
capitals", the code says otherwise, and docs-kit refuses to let that pass.

## Fix the drift

The fix is always the same: regenerate, then commit.

```bash
mise run docs:refresh
git diff --stat
```

```text
 cli/hello.usage.kdl          | 2 +-
 docs/references/cli/hello.md | 2 +-
 src/hello/cli.py             | 2 +-
 3 files changed, 3 insertions(+), 3 deletions(-)
```

The code change and its documentation change now sit side by side in the
same diff. Let's commit them together and run the gate again:

```bash
git commit -am "feat: shout louder"
mise run docs:check
```

```text
docs are up to date
```

## What we did

We built a CLI, and without writing a single line of reference documentation
we got a site that:

1. **generates** its CLI reference from the code (`docs:refresh`),
2. **previews** with live reload (`docs:serve`),
3. **fails** as soon as the reference and the code disagree (`docs:check`).
