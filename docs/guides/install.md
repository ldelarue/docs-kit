# How to install docs-kit

docs-kit is distributed from its git repository: there is no PyPI package,
and a git ref is the version pin: a release tag (`@vX.Y.Z`, listed on the
[releases page](https://github.com/ldelarue/docs-kit/releases)) or the
`@latest` branch, which always points at the newest release.

## Pick an installation

| Your repository | Install docs-kit as | Why |
| --- | --- | --- |
| Python project with a Typer CLI, or any repo managed by uv | a **dev dependency** | `docs-kit spec` must import your CLI from your own venv; `uv.lock` pins the kit |
| Go project, or any repo without a Python venv | a **uv tool** on `PATH` | nothing to add to the project |
| docs-kit itself (kit development) | a **local wheel** or checkout | test unreleased changes |

[About the install modes](../explanation/install-modes.md) explains the
trade-offs in depth.

## Prerequisites

- **git**, and **[uv](https://docs.astral.sh/uv/)** for every method below.
- **[mise](https://mise.jdx.dev)** if you want the `docs:*` tasks (recommended).
- **[usage](https://usage.jdx.dev)**, only when you document a CLI. With
  `--with-mise`, docs-kit pins it in your mise config and `mise install`
  provides it; otherwise run `mise use -g usage@latest`.

## Install as a dev dependency

=== "A released tag (recommended)"

    ```bash
    uv add --dev "docs-kit @ git+https://github.com/ldelarue/docs-kit.git@vX.Y.Z"
    ```

=== "The latest release"

    ```bash
    uv add --dev "docs-kit @ git+https://github.com/ldelarue/docs-kit.git@latest"
    ```

    `uv.lock` records the resolved commit, so the pin still only moves when
    you run `uv lock --upgrade-package docs-kit`.

Run it through uv so it sees your project's environment:

```console
$ uv run docs-kit --version
docs-kit X.Y.Z
```

Next: [wire the tasks with `--committed`](configure-mise-and-uv.md#python-repository-dependency-mode).

## Install as a uv tool

=== "A released tag"

    ```bash
    uv tool install --from "docs-kit @ git+https://github.com/ldelarue/docs-kit.git@vX.Y.Z" docs-kit
    ```

=== "The latest release"

    ```bash
    uv tool install --from "docs-kit @ git+https://github.com/ldelarue/docs-kit.git@latest" docs-kit
    ```

    `uv tool upgrade docs-kit` re-resolves `@latest` later.

```console
$ docs-kit --version
docs-kit X.Y.Z
```

Next: [wire the tasks in shim mode](configure-mise-and-uv.md#go-or-no-venv-repository-shim-mode).

## Try it without installing

```bash
uvx --from "docs-kit @ git+https://github.com/ldelarue/docs-kit.git@latest" docs-kit --help
```

## Install from a local checkout

To run unreleased changes of the kit:

```bash
git clone git@github.com:ldelarue/docs-kit.git ~/Dev/docs-kit
cd ~/Dev/docs-kit
mise install
mise run install-local   # builds dist/*.whl, then `uv tool install --force` it
```

Or run a built wheel once, without changing your `PATH`:

```bash
uv run --no-project --with dist/docs_kit-*.whl docs-kit --version
```

In a consumer repository, point init at the clone to use its task bodies
directly ([checkout mode](configure-mise-and-uv.md#kit-development-checkout-mode)):

```bash
docs-kit init --with-mise --docs-kit ~/Dev/docs-kit
```

## Troubleshooting

`ERROR: 'usage' is not on PATH.`
:   You are rendering CLI pages without the `usage` binary. Run
    `mise install` in a repo wired with `--with-mise`, or
    `mise use -g usage@latest`.

`WARNING: task layer sync failed` during `init --with-mise`
:   Shim mode fetches `.docs-kit/` over SSH
    (`git@github.com:ldelarue/docs-kit.git`) and fails fast without a key.
    Retry over HTTPS:

    ```bash
    DOCS_KIT_REPO=https://github.com/ldelarue/docs-kit.git docs-kit pull-tasks
    ```

`uv run docs-kit` works but `docs-kit` does not
:   Expected in dependency mode: the kit lives in the project's venv, not on
    `PATH`. Use `uv run docs-kit` or the `mise run docs:*` tasks.
