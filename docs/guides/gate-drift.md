# How to fail the build on stale docs

The gate is one command:

```bash
mise run docs:check
```

It exits non-zero when a generated file is missing or stale, when a CLI
contract no longer matches the code, or when regenerated docs are not
committed. Everything below is about running it in the right places.

## On GitHub: pull requests and Pages

On a GitHub repository (a `github.com` remote, a `.github/workflows/`
directory, or a GitHub Actions runner), `init` and `refresh` generate
`.github/workflows/docs.yml`:

- the **check** job runs `mise run docs:check` on every pull request;
- the **deploy** job runs `mise run docs:build` on pushes to `main` and
  publishes `site/` to GitHub Pages.

To turn it on:

1. Commit `.github/workflows/docs.yml`.
2. In the repository, open **Settings → Pages** and set **Source** to
   **GitHub Actions**.
3. Set `site_url` in `zensical.toml` to `https://<owner>.github.io/<repo>/`.

No secret is needed, so pull requests from forks are checked too.

!!! warning "Don't edit `docs.yml`"

    The workflow is a generated file. Its `ref:` pins the docs-kit release
    that generated it; `mise run docs:refresh` restamps it after an upgrade,
    and `docs:check` fails on any hand edit.

## On other CI systems

Outside GitHub no workflow is generated. Run the same gate from your pipeline
after installing the tools:

=== "Dependency mode"

    ```bash
    mise trust && mise install
    uv sync
    mise run docs:check
    ```

=== "Shim mode"

    The task layer is git-ignored, so recreate it the way the GitHub
    workflow does: a tag-pinned clone of docs-kit plus the three opt-in keys.

    ```bash
    git clone --quiet --depth 1 --branch vX.Y.Z https://github.com/ldelarue/docs-kit.git .docs-kit
    printf '[vars]\ndocs_kit = "%s/.docs-kit"\n[env]\nDOCS_KIT = "{{ vars.docs_kit }}"\n[task_config]\nincludes = ["{{ vars.docs_kit }}/shared/mise/docs.toml"]\n[tools]\nusage = "latest"\n' "$PWD" > mise.local.toml
    mise trust && mise install
    mise run docs:check
    ```

    Keep the `--branch` tag equal to the docs-kit version your team runs
    locally.

## Before each commit, with hk

Hooks catch drift before it reaches CI. With [hk](https://hk.jdx.dev), add a
`pre-commit` step that only runs when docs sources are staged:

```pkl title="hk.pkl"
hooks {
  ["pre-commit"] {
    steps {
      ["docs-drift"] {
        glob = List("docs/**", "src/**", "cli/**", "pyproject.toml", "zensical.toml") // (1)!
        check = "mise run docs:check" // (2)!
      }
    }
  }
}
```

1.  Adjust to where your code and contracts live, so commits that only touch
    tests or the changelog skip the step.
2.  `check`, not `fix`: the hook blocks the commit and never stages
    regenerated files behind your back.

Install the hook once per clone:

```bash
hk install --mise
```

Hooks are opt-in per clone and `git commit --no-verify` skips them: keep the
CI job as the gate that cannot be bypassed.

## When the gate fails

```text
docs are NOT up to date:
  stale:   cli/mycli.usage.kdl
  missing: docs/references/cli/mycli.md
run `docs-kit refresh` and commit the result.
```

Fix it the same way every time:

```bash
mise run docs:refresh
git add -A && git commit
```

| Line | Meaning | Fix |
| --- | --- | --- |
| `stale: <file>` | the file differs from what the code produces now | refresh, commit |
| `missing: <file>` | a generated file was never written or was deleted | refresh, commit |
| `lint: cli/<bin>.usage.kdl` | the contract fails `usage lint` | fix the code or the extra file, then refresh |
| `stale: mise.toml docs-kit task block …` | the committed task block was edited or is from another version | `uv run docs-kit init --with-mise --committed` |
| `git diff` output, task fails | regenerated files are not committed | `git add` them, commit |
