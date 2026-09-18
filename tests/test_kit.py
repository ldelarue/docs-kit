from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tomllib
from pathlib import Path

import pytest

from docs_kit import cli

FIXTURES = Path(__file__).parent / "fixtures"
KIT = Path(__file__).resolve().parents[1]
SPEC = "openapi.json"


@pytest.fixture(autouse=True)
def _skip_layer_pull(monkeypatch):
    """init never shells out to git in tests (the file:// tests opt back in)."""
    monkeypatch.setenv("DOCS_KIT_SKIP_PULL", "1")


def make_repo(base: Path, name: str, fixture: str) -> Path:
    repo = base / name
    repo.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / fixture, repo / SPEC)

    return repo


def strip_spec_prose(text: str) -> str:
    keep = (
        "Canonical specification:",
        "<title>",
    )
    return "\n".join(l for l in text.splitlines() if not any(l.startswith(k) for k in keep))


def generated_rels():
    return (cli.VENDORED_SPEC, cli.SWAGGER_PAGE, cli.API_PAGE, cli.ENDPOINTS_PAGE)


def test_both_specs_render_identical_pages(tmp_path):
    go = make_repo(tmp_path, "go", "golang.openapi.json")
    py = make_repo(tmp_path, "py", "python.openapi.json")
    assert cli.cmd_refresh(go, SPEC) == 0
    assert cli.cmd_refresh(py, SPEC) == 0
    for rel in (cli.ENDPOINTS_PAGE, cli.API_PAGE, cli.SWAGGER_PAGE):
        assert strip_spec_prose((go / rel).read_text()) == strip_spec_prose((py / rel).read_text()), rel
    assert (go / cli.VENDORED_SPEC).read_bytes() == (go / SPEC).read_bytes()


def test_refresh_is_byte_stable(tmp_path):
    repo = make_repo(tmp_path, "repo", "golang.openapi.json")
    assert cli.cmd_refresh(repo, SPEC) == 0
    before = {rel: (repo / rel).read_bytes() for rel in generated_rels()}
    assert cli.cmd_refresh(repo, SPEC) == 0
    after = {rel: (repo / rel).read_bytes() for rel in generated_rels()}
    assert before == after


def test_check_detects_stale_and_missing(tmp_path):
    repo = make_repo(tmp_path, "repo", "golang.openapi.json")
    assert cli.cmd_check(repo, SPEC) == 1  # nothing generated yet
    assert cli.cmd_refresh(repo, SPEC) == 0
    assert cli.cmd_check(repo, SPEC) == 0
    target = repo / cli.ENDPOINTS_PAGE
    target.write_text(target.read_text() + "\nhand edit\n")
    assert cli.cmd_check(repo, SPEC) == 1
    assert cli.cmd_refresh(repo, SPEC) == 0
    assert cli.cmd_check(repo, SPEC) == 0


def test_check_drifts_when_spec_changes(tmp_path):
    repo = make_repo(tmp_path, "repo", "golang.openapi.json")
    assert cli.cmd_refresh(repo, SPEC) == 0
    spec = repo / SPEC
    data = spec.read_bytes()
    data = data.replace(b"List Contents", b"List Contents (changed)")
    spec.write_bytes(data)
    assert cli.cmd_check(repo, SPEC) == 1


def test_init_scaffolds_without_touching_mise(tmp_path, capsys):
    repo = make_repo(tmp_path, "repo", "golang.openapi.json")
    assert cli.cmd_init(repo, SPEC, False, ".docs-kit") == 0
    for rel in (
        "docs/index.md",
        "docs/tutorials/index.md",
        "docs/guides/index.md",
        "docs/explanation/index.md",
        "docs/references/index.md",
        "zensical.toml",
        ".github/workflows/docs.yml",
        *generated_rels(),
    ):
        assert (repo / rel).is_file(), rel
    cfg = tomllib.loads((repo / "zensical.toml").read_text())
    assert cfg["project"]["site_name"] == "golang-api-playground"
    assert cfg["project"]["nav"][0] == {"Home": "index.md"}
    # the user's mise configs are never written, and no block template file
    # exists - .docs-kit/ is reserved for the pulled task layer only
    assert not (repo / ".mise.toml").exists()
    assert not (repo / "mise.local.toml").exists()
    assert not (repo / ".docs-kit").exists()  # pull skipped (DOCS_KIT_SKIP_PULL)
    ign = (repo / ".gitignore").read_text().split()
    assert {"site/", ".cache/", ".docs-kit/", "mise.local.toml"} <= set(ign)
    out = capsys.readouterr().out
    block = cli._mise_block(".docs-kit")
    assert tomllib.loads(block)["task_config"]["includes"] == ["{{ vars.docs_kit }}/shared/mise/docs.toml"]
    assert block.rstrip("\n") in out  # the exact block body is printed, comment-free...
    assert not any(ln.lstrip().startswith("#") for ln in block.splitlines())
    assert "copy-paste" in out  # ...for manual copy, phrased as "a mise config", never as
    assert "auto-loads" not in out  # mise.local.toml heredoc wiring (old message shape)
    before = (repo / ".gitignore").read_bytes()
    assert cli.cmd_init(repo, SPEC, False, ".docs-kit") == 0  # repair no-op
    assert before == (repo / ".gitignore").read_bytes()
    assert cli.cmd_init(repo, SPEC, True, ".docs-kit") == 0  # --force changes nothing either
    assert before == (repo / ".gitignore").read_bytes()
    assert not (repo / ".mise.toml").exists()
    assert not (repo / ".docs-kit").exists()


def test_init_default_kit_home_is_the_shim(tmp_path, monkeypatch):
    # the CLI may live in a checkout; the default must STILL be the pullable
    # shim so `uv run --project <kit> docs-kit init` wires the task layer
    monkeypatch.delenv("DOCS_KIT", raising=False)
    assert cli._default_kit_home() == ".docs-kit"


def test_init_checkout_mode_records_absolute_kit_path(tmp_path, capsys, monkeypatch):
    repo = make_repo(tmp_path, "repo", "golang.openapi.json")

    def _boom(*args, **kwargs):
        raise AssertionError("checkout mode must never sync a task layer")

    monkeypatch.setattr(cli, "pull_tasks", _boom)
    monkeypatch.delenv("DOCS_KIT_SKIP_PULL", raising=False)
    assert cli.cmd_init(repo, SPEC, False, "/abs/docs-kit-checkout") == 0
    out = capsys.readouterr().out
    assert 'docs_kit = "/abs/docs-kit-checkout"' in out
    assert not (repo / ".mise.toml").exists()
    assert not (repo / ".docs-kit").exists()  # checkout mode creates nothing


def test_init_reports_legacy_mise_lines_but_never_rewrites(tmp_path, capsys):
    repo = make_repo(tmp_path, "repo", "golang.openapi.json")
    legacy = (
        '[vars]\nuv_python = "3.12"\ndocs_kit = "/tmp/old-kit"\n\n'
        '[env]\nFOO = "1"\nDOCS_KIT = "{{ vars.docs_kit }}"\n\n'
        '[task_config]\nincludes = ["{{ vars.docs_kit }}/shared/mise/docs.toml"]\n\n'
        "# docs-kit integration generated block\n"
        'docs_kit = ".docs-kit"\n'
        '[tasks."docs:pull-tasks"]\ndescription = "old"\nrun = "echo old"\n'
        '[tasks.mine]\nrun = "go run ."\n'
    )
    mise = repo / ".mise.toml"
    mise.write_text(legacy)
    before = mise.read_bytes()
    assert cli.cmd_init(repo, SPEC, False, ".docs-kit") == 0
    out = capsys.readouterr().out
    for quoted in (
        'docs_kit = "/tmp/old-kit"',
        'DOCS_KIT = "{{ vars.docs_kit }}"',
        "{{ vars.docs_kit }}/shared/mise/docs.toml",
        '[tasks."docs:pull-tasks"]',
    ):
        assert quoted in out, quoted
    assert "FOO" not in out  # foreign user lines are never reported
    assert "go run" not in out
    assert mise.read_bytes() == before  # init never rewrites .mise.toml


def test_opt_in_hints_on_existing_mise_local(tmp_path, capsys):
    repo = make_repo(tmp_path, "repo", "golang.openapi.json")
    assert cli.cmd_init(repo, SPEC, False, ".docs-kit") == 0
    block = cli._mise_block(".docs-kit")
    # consumer pasted the printed heredoc (their own config above it)
    before = '[tools]\nuv = "latest"\n\n'
    (repo / "mise.local.toml").write_text(before + block)
    capsys.readouterr()
    assert cli.cmd_init(repo, SPEC, False, ".docs-kit") == 0
    out = capsys.readouterr().out
    assert "copy-paste" not in out and "OUTDATED" not in out  # opt-in detected
    assert (repo / "mise.local.toml").read_text() == before + block  # untouched
    # an old-shape block (stale docs_kit value) asks for a replace
    old = "# docs-kit integration (generated by `docs-kit init --docs-kit .docs-kit`)\n[vars]\ndocs_kit = \".old\"\n"
    (repo / "mise.local.toml").write_text(old)
    assert cli.cmd_init(repo, SPEC, False, ".docs-kit") == 0
    assert "OUTDATED or hand-edited" in capsys.readouterr().out
    assert (repo / "mise.local.toml").read_text() == old  # still untouched


def test_init_without_mise(tmp_path, capsys):
    repo = make_repo(tmp_path, "repo", "golang.openapi.json")
    mise = repo / ".mise.toml"
    mise.write_text('[tools]\nuv = "latest"\n\ndocs_kit = ".docs-kit"\n')
    before = mise.read_bytes()
    assert cli.cmd_init(repo, SPEC, False, ".docs-kit", use_mise=False) == 0
    out = capsys.readouterr().out
    assert "--without-mise" in out
    assert "cleanup" not in out and "copy-paste" not in out and "docs_kit" not in out
    assert not (repo / ".docs-kit").exists()  # no dir, no template, no layer
    assert not (repo / "mise.local.toml").exists()
    ign = (repo / ".gitignore").read_text().split()
    assert "site/" in ign and ".cache/" in ign
    assert ".docs-kit/" not in ign and "mise.local.toml" not in ign
    for rel in (
        "docs/index.md", "docs/tutorials/index.md", "docs/guides/index.md",
        "docs/explanation/index.md", "docs/references/index.md", "zensical.toml",
        ".github/workflows/docs.yml", *generated_rels(),
    ):
        assert (repo / rel).is_file(), rel
    assert mise.read_bytes() == before


def test_shared_docs_toml_ships_pull_tasks():
    tasks = tomllib.loads((KIT / "shared/mise/docs.toml").read_text())
    assert {"docs:init", "docs:refresh", "docs:build", "docs:serve", "docs:check", "docs:pull-tasks"} <= set(tasks)
    run = tasks["docs:pull-tasks"]["run"]
    assert 'exec sh "$shim/shared/mise/kit-sync" "$shim"' in run  # engine fast-path
    assert 'sparse-checkout set --no-cone "/shared/mise/"' in run
    assert "nothing to pull" in run  # checkout installs ($DOCS_KIT absolute): exit-0 guard


def make_tagged_kit(base: Path) -> Path:
    """Throwaway kit repo: v0.1.0 predates the payload, v9.9.9 ships shared/mise.

    The real clone carries no release tags until release-please cuts one,
    so pull tests must never depend on tags of the repo they live in.
    """
    kit = base / "kit"
    kit.mkdir()

    def git(*args):
        subprocess.run(
            ("git", *args), cwd=kit, check=True, capture_output=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
        )

    (kit / "README.md").write_text("kit before the payload\n")
    git("init", "-q", "-b", "main", ".")
    git("add", "-A")
    git("commit", "-q", "-m", "pre-payload")
    git("tag", "v0.1.0")
    (kit / "shared/mise").mkdir(parents=True)
    shutil.copy(KIT / "shared/mise/kit-sync", kit / "shared/mise/kit-sync")
    (kit / "shared/mise/docs.toml").write_text('"docs:x" = { run = "true" }\n')
    git("add", "-A")
    git("commit", "-q", "-m", "task layer")
    git("tag", "v9.9.9")
    return kit


def test_pull_tasks_bootstraps_shim_in_place(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCS_KIT_REPO", "file://" + str(make_tagged_kit(tmp_path)))
    repo = tmp_path / "consumer"
    shim = repo / ".docs-kit"
    shim.mkdir(parents=True)
    (shim / "stray.txt").write_text("dir already existed without a checkout\n")
    assert cli.pull_tasks(repo, ".docs-kit", "9.9.9") == "v9.9.9"
    assert (shim / "shared/mise/docs.toml").is_file()  # payload materialized around it
    assert not (shim / "src").exists()  # sparse: only /shared/mise/
    assert "dir already existed" in (shim / "stray.txt").read_text()
    assert cli.pull_tasks(repo, ".docs-kit", "9.9.9") == "v9.9.9"  # idempotent re-pin
    # a missing dir is also fine (pull creates it)
    repo2 = tmp_path / "consumer2"
    assert cli.pull_tasks(repo2, ".docs-kit", "9.9.9") == "v9.9.9"


def test_pull_tasks_uses_engine_fast_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCS_KIT_REPO", "file://" + str(make_tagged_kit(tmp_path)))
    repo = tmp_path / "consumer"
    shim = repo / ".docs-kit"
    (shim / "shared/mise").mkdir(parents=True)
    shutil.copy(KIT / "shared/mise/kit-sync", shim / "shared/mise/kit-sync")
    (shim / "stray.txt").write_text("dir already existed without a checkout\n")
    assert cli.pull_tasks(repo, ".docs-kit", "9.9.9") == "v9.9.9"
    assert (shim / "shared/mise/docs.toml").is_file()  # engine bootstrapped in place
    assert (shim / "shared/mise/kit-sync").read_text() == (KIT / "shared/mise/kit-sync").read_text()  # shadow replaced by the payload copy
    assert "dir already existed" in (shim / "stray.txt").read_text()


@pytest.mark.parametrize("setup_engine", [False, True])
def test_pull_tasks_refuses_tag_without_payload(tmp_path, monkeypatch, setup_engine):
    """v0.1.x tags predate shared/mise - pulling one must never wipe a layer."""
    monkeypatch.setenv("DOCS_KIT_REPO", "file://" + str(make_tagged_kit(tmp_path)))
    repo = tmp_path / "consumer"
    assert cli.pull_tasks(repo, ".docs-kit", "9.9.9") == "v9.9.9"
    if setup_engine:
        shutil.copy(KIT / "shared/mise/kit-sync", repo / ".docs-kit/shared/mise/kit-sync")
    with pytest.raises(RuntimeError, match="no task layer|kit-sync exited"):
        cli.pull_tasks(repo, ".docs-kit", "0.1.0")
    assert git_describe(repo / ".docs-kit") == "v9.9.9"  # layer untouched
    assert (repo / ".docs-kit/shared/mise/docs.toml").is_file()


def git_describe(path):
    import subprocess

    return subprocess.run(
        ["git", "-C", str(path), "describe", "--tags", "--exact-match"],
        capture_output=True, text=True,
    ).stdout.strip()


def test_init_refuses_hand_edits(tmp_path):
    repo = make_repo(tmp_path, "repo", "golang.openapi.json")
    assert cli.cmd_init(repo, SPEC, False, ".docs-kit") == 0
    (repo / "zensical.toml").write_text("[project]\nsite_name = 'mine'\n")
    with pytest.raises(SystemExit):
        cli.cmd_init(repo, SPEC, False, ".docs-kit")
    assert (repo / "zensical.toml").read_text().startswith("[project]")  # untouched
    assert cli.cmd_init(repo, SPEC, True, ".docs-kit") == 0
    assert "golang-api-playground" in (repo / "zensical.toml").read_text()
    drifted = repo / cli.ENDPOINTS_PAGE
    drifted.write_text(drifted.read_text() + "\ndrift\n")
    with pytest.raises(SystemExit):
        cli.cmd_init(repo, SPEC, False, ".docs-kit")
    assert cli.cmd_refresh(repo, SPEC) == 0  # generated files are refresh's job
    assert cli.cmd_init(repo, SPEC, False, ".docs-kit") == 0


def test_init_requires_spec(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(SystemExit):
        cli.cmd_init(repo, SPEC, False, ".docs-kit")


def _fake_server(monkeypatch):
    calls = []

    class _Done:
        returncode = 0

    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or _Done())
    return calls


def test_serve_pinned_via_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("DOCS_PORT", raising=False)
    monkeypatch.setattr(cli.shutil, "which", lambda n: f"/usr/bin/{n}")
    calls = _fake_server(monkeypatch)
    assert cli.main(["serve", str(tmp_path), "--port", "9998"]) == 0
    assert calls == [["zensical", "serve", "--dev-addr", "127.0.0.1:9998"]]


def test_serve_pinned_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCS_PORT", "9997")
    monkeypatch.setattr(cli.shutil, "which", lambda n: f"/usr/bin/{n}")
    calls = _fake_server(monkeypatch)
    assert cli.main(["serve", str(tmp_path)]) == 0
    assert calls == [["zensical", "serve", "--dev-addr", "127.0.0.1:9997"]]


def test_serve_leases_around_a_busy_preferred(tmp_path, monkeypatch):
    monkeypatch.delenv("DOCS_PORT", raising=False)
    monkeypatch.setenv("FREE_PORT_MIN", "8010")
    monkeypatch.setenv("FREE_PORT_MAX", "8015")
    monkeypatch.setattr(cli.shutil, "which", lambda n: f"/usr/bin/{n}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 8010))
        expected = next(p for p in range(8011, 8016) if cli._port_free(p, "127.0.0.1"))
        calls = _fake_server(monkeypatch)
        assert cli.main(["serve", str(tmp_path)]) == 0
    assert calls == [["zensical", "serve", "--dev-addr", f"127.0.0.1:{expected}"]]


def test_serve_falls_back_to_uvx_pin(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCS_PORT", "9996")
    monkeypatch.setattr(
        cli.shutil, "which", lambda n: None if n == "zensical" else f"/usr/bin/{n}"
    )
    calls = _fake_server(monkeypatch)
    assert cli.main(["serve", str(tmp_path)]) == 0
    assert calls == [
        ["uvx", "--from", f"zensical=={cli.ZENSICAL_VERSION}",
         "zensical", "serve", "--dev-addr", "127.0.0.1:9996"]
    ]


def test_serve_without_any_server_tool_exits(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCS_PORT", "9995")
    monkeypatch.setattr(cli.shutil, "which", lambda n: None)
    with pytest.raises(SystemExit):
        cli.main(["serve", str(tmp_path)])
