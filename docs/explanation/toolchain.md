# About the toolchain

docs-kit writes very little itself. It is glue between a handful of tools
that each do one job well, chosen so that the same commands work on a
laptop, in a git hook and on a CI runner. This page explains why each one is
there.

| Job | Tool |
| --- | --- |
| Build and serve the site | [Zensical](https://zensical.org) |
| Describe a CLI | [Usage](https://usage.jdx.dev) (KDL specs) |
| Pin tools, define tasks | [mise](https://mise.jdx.dev) |
| Install and lock Python packages | [uv](https://docs.astral.sh/uv/) |
| Run git hooks | [hk](https://hk.jdx.dev) |
| Organise the content | [Diátaxis](https://diataxis.fr) |

## Zensical, for the site

Zensical comes from the team behind Material for MkDocs. It keeps the
Markdown dialect and components that team's users already know (admonitions,
content tabs, code annotations, grids, search), with a fast native build and
a TOML configuration file.

Two properties matter for docs-kit in particular:

- **It is a Python package.** docs-kit declares it as a runtime dependency
  and runs it as `python -m zensical` from its own environment. Its version is
  locked with the kit's; there is no separate binary to find on `PATH`.
- **Its config is TOML.** `zensical.toml` can be scaffolded from a template,
  and the navigation can express the Diátaxis tabs directly.

## Usage, for CLIs

A CLI reference needs a description of the CLI that is not tied to one
language. Usage provides that: a KDL file listing commands, arguments,
flags, environment settings and exit codes, plus a binary that lints it and
renders it into Markdown, man pages and shell completions.

That neutrality is the point. A Typer app (through the `usage-spec-typer`
exporter bundled with docs-kit) and a cobra command tree (through its own
`--usage-spec` flag) both reduce to the same format, and from there one
pipeline handles both. Documentation generators built into a single CLI
framework could document only that framework.

KDL is also pleasant to diff, which matters because the contract is
committed and reviewed.

## mise, for tools and tasks

mise pins tools and defines tasks in one file, and runs identically on every
machine that has it. docs-kit leans on both halves:

- **Tools.** The `usage` binary is pinned under `[tools]`, so `mise install`
  provides it to developers and CI alike.
- **Tasks.** `docs:refresh`, `docs:serve`, `docs:check` and friends are the
  stable interface. What a task runs can change between releases; its name
  doesn't. Docs, hooks and CI all say `mise run docs:check`.

On GitHub Actions, `jdx/mise-action` gives the runner the same environment.
There is no separate CI script to keep in sync with local commands.

## uv, for Python packages

uv installs docs-kit straight from git with a lockfile, which is how the kit
is pinned without a package index. It covers every install mode with one
tool: `uv add --dev` for dependency mode, `uv tool install` for a CLI on
`PATH`, `uvx` for a one-off run. And `uv run` syncs the environment on
demand, so the committed tasks never need a separate install step.

## hk, for git hooks

The drift gate is most useful before a commit is made. hk runs hooks with
tools resolved through mise, and lets a step run only when matching files
are staged. A docs step that fires only for code, contract or docs changes
keeps commits fast. hk is optional: any hook runner that can call
`mise run docs:check` works.

## Diátaxis, for the content

Diátaxis sorts documentation by what the reader is doing: learning
(tutorials), working (how-to guides), looking something up (reference) or
trying to understand (explanation). The scaffold turns those into the
site's top-level tabs.

It is also what makes generation fit: reference is the one kind of page that
should mirror the machinery, so it is the one docs-kit generates. See
[About generated docs](generated-docs.md#why-the-other-three-quadrants-stay-human).

## Small constraints that follow

A few rules in the codebase exist only because of these choices:

- **Shim task bodies are POSIX `sh`, on one line.** mise runs task bodies
  with the system shell, and on many Linux runners `/bin/sh` is `dash`, not
  bash. TOML inline tables cannot span lines. A test enforces both.
- **The committed task block never duplicates a table header.** A second
  `[tools]` is invalid TOML, and mise skips an invalid file entirely, so
  docs-kit adds `usage` to your existing `[tools]` table instead.
- **Generated output is byte-stable.** Everything is diffed by git; see
  [About generated docs](generated-docs.md#why-byte-stability-matters).
