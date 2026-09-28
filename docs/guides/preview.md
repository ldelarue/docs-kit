# How to preview the docs locally

## Start a live preview

=== "mise"

    ```bash
    mise run docs:serve
    ```

=== "Dependency mode, without mise"

    ```bash
    uv run docs-kit serve
    ```

=== "uv tool, without mise"

    ```bash
    docs-kit serve
    ```

```text
serving docs on http://127.0.0.1:8010 (Ctrl-C to stop)
```

Zensical rebuilds and reloads the browser whenever a file under `docs/` or
`zensical.toml` changes. Stop it with ++ctrl+c++.

`docs:serve` does **not** regenerate the reference pages. When you change
the code behind them, run `mise run docs:refresh` in a second terminal while
the server is running; the preview picks up the new pages.

## Serve on a fixed port

```bash
uv run docs-kit serve --port 8123
DOCS_PORT=8123 mise run docs:serve
```

A pinned port is exact: if it is taken, Zensical fails to bind instead of
picking another. To pin it for good, put `DOCS_PORT` in `mise.local.toml`
(see [Tune the tasks](configure-mise-and-uv.md#tune-the-tasks-with-environment-variables)).

## Run several previews side by side

Without a pinned port, `serve` prefers `8010` and otherwise takes the first
free port in `8000-8999`. Two repositories, or two worktrees of the same
one, can therefore be served at the same time with no configuration: read
the URL from the `serving docs on …` line.

To keep previews in a range of your own:

```bash
FREE_PORT_MIN=8100 FREE_PORT_MAX=8199 mise run docs:serve
```

## Preview a branch or a pull request

Use a git worktree so your current checkout keeps running its own preview:

```bash
git fetch origin feature/new-guide
git worktree add ../myrepo-preview origin/feature/new-guide
cd ../myrepo-preview
mise trust && mise install     # (1)!
mise run docs:serve            # takes the next free port
```

1.  Dependency mode: `uv run` inside the task syncs the worktree's venv on
    first use. Shim mode: `.docs-kit/` and `mise.local.toml` are git-ignored,
    so run `docs-kit init --with-mise` in the worktree first.

Remove it with `git worktree remove ../myrepo-preview` when you are done.

## Preview on another device or from a container

Bind to all interfaces instead of loopback:

```bash
uv run docs-kit serve --host 0.0.0.0 --port 8010
```

!!! warning

    `0.0.0.0` exposes the preview to your whole network. Use it only on
    networks you trust, or bind to a specific interface address instead.

Call the CLI directly for options like `--host`: it behaves the same in
every install mode (use `docs-kit serve …` for a uv tool install).

## Preview exactly what CI publishes

`serve` is a development server. To check the static output that the GitHub
Pages job uploads, build it and serve the `site/` directory:

```bash
mise run docs:build                    # refresh + zensical build --clean
python3 -m http.server --directory site 8080
```

Open `http://127.0.0.1:8080`. `site/` is git-ignored.

!!! tip "Links behave differently on Pages"

    The `site_url` in `zensical.toml` must be the address you publish to
    (for GitHub Pages, `https://<owner>.github.io/<repo>/`); instant
    navigation relies on it.
