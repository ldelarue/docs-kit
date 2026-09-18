from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

import pytest

from docs_kit import cli

FIXTURES = Path(__file__).parent / "fixtures"
SPEC = "openapi.json"


def make_repo(base: Path, name: str, fixture: str) -> Path:
    repo = base / name
    repo.mkdir(parents=True)
    shutil.copy(FIXTURES / fixture, repo / SPEC)
    return repo


def strip_spec_prose(text: str) -> str:
    keep = (
        "Canonical specification:",
        "<title>",
    )
    return "\n".join(l for l in text.splitlines() if not any(l.startswith(k) for k in keep))


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


def generated_rels():
    return (cli.VENDORED_SPEC, cli.SWAGGER_PAGE, cli.API_PAGE, cli.ENDPOINTS_PAGE)


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


def test_init_scaffolds_then_refuses(tmp_path):
    repo = make_repo(tmp_path, "repo", "golang.openapi.json")
    assert cli.cmd_init(repo, SPEC, False, "/tmp/kit-home") == 0
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
    assert (repo / ".gitignore").exists()
    ign = (repo / ".gitignore").read_text()
    assert "site/" in ign and ".cache/" in ign
    cfg = tomllib.loads((repo / "zensical.toml").read_text())
    assert cfg["project"]["site_name"] == "golang-api-playground"
    assert cfg["project"]["nav"][0] == {"Home": "index.md"}
    mise = (repo / ".mise.toml").read_text()
    assert 'DOCS_KIT = "/tmp/kit-home"' in mise
    assert "docs:build" in mise and "docs:check" in mise
    assert 'uv = "latest"' in mise
    with pytest.raises(SystemExit):
        cli.cmd_init(repo, SPEC, False, "/tmp/kit-home")
    assert cli.cmd_init(repo, SPEC, True, "/tmp/kit-home") == 0


def test_init_merges_existing_mise_tables(tmp_path):
    repo = make_repo(tmp_path, "repo", "golang.openapi.json")
    (repo / ".mise.toml").write_text('[env]\nFOO = "1"\n\n[tools]\nrestish = "latest"\n')
    assert cli.cmd_init(repo, SPEC, False, "/tmp/kit-home") == 0
    cfg = tomllib.loads((repo / ".mise.toml").read_text())
    assert cfg["tools"]["uv"] == "latest"
    assert cfg["tools"]["restish"] == "latest"
    assert cfg["env"]["FOO"] == "1"
    assert cfg["env"]["DOCS_KIT"] == "/tmp/kit-home"
    assert "docs:refresh" in cfg["tasks"]


def test_init_requires_spec(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(SystemExit):
        cli.cmd_init(repo, SPEC, False, "/tmp/kit-home")
