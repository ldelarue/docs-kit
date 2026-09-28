# How to upgrade docs-kit

An upgrade has three parts that must move together: the **CLI**, the **task
definitions** it runs under mise, and the **generated files** stamped with
its version (the task block and `docs.yml`). Follow the section for your
install mode, then commit everything in one change.

## Dependency mode

1. Move the pin:

    === "Pinned tag"

        ```bash
        uv add --dev "docs-kit @ git+https://github.com/ldelarue/docs-kit.git@vX.Y.Z"
        ```

    === "`@latest`"

        ```bash
        uv lock --upgrade-package docs-kit && uv sync
        ```

2. Rewrite the committed task block for the new version:

    ```bash
    uv run docs-kit init --with-mise --committed
    ```

3. Regenerate the docs (this also restamps `.github/workflows/docs.yml`):

    ```bash
    mise run docs:refresh
    mise run docs:check
    ```

4. Commit `pyproject.toml`, `uv.lock`, `mise.toml` and the regenerated files.

## Shim mode (uv tool)

1. Upgrade the CLI:

    === "`@latest`"

        ```bash
        uv tool upgrade docs-kit
        ```

    === "Pinned tag"

        ```bash
        uv tool install --force --from "docs-kit @ git+https://github.com/ldelarue/docs-kit.git@vX.Y.Z" docs-kit
        ```

2. Re-pin the task layer to the new CLI version:

    ```bash
    docs-kit pull-tasks      # or: mise run docs:pull-tasks
    ```

    ```text
    docs task layer pinned at vX.Y.Z
    ```

3. Regenerate and commit:

    ```bash
    mise run docs:refresh
    mise run docs:check
    ```

Teammates run steps 1 and 2 on their own machines; the regenerated files
reach them through git.

!!! warning "Skipping `pull-tasks`"

    Without it, `.docs-kit/` keeps the previous release's task bodies while
    the CLI is newer. Tasks may be missing or behave like the old version.

## Checkout mode

```bash
cd ~/Dev/docs-kit && git pull
mise run install-local    # if you also run the CLI from PATH
```

The tasks follow the clone directly; there is nothing to pull.

## Check the versions line up

```bash
uv run docs-kit --version                     # dependency mode
docs-kit --version                            # uv tool
grep 'docs-kit tasks v' mise.toml             # committed block
grep 'ref: v' .github/workflows/docs.yml      # CI pin
```

All of them should name the same version. `docs-kit check` fails when the
committed block or `docs.yml` lag behind the CLI.
