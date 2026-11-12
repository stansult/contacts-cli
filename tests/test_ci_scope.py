"""CI routing uses the whole push or PR diff and defaults to full checks."""

import subprocess

import pytest

from scripts.ci_scope import changed_paths, docs_only


@pytest.mark.parametrize(
    "paths,expected",
    [
        (["README.md", "docs/testing.md"], True),
        (["README.md", "src/contacts_cli/cli.py"], False),
        ([".github/workflows/ci.yml"], False),
        (["tests/fixtures/input.md"], False),
        (["docs/new-generated.md"], False),
        ([], False),
    ],
)
def test_document_allowlist(paths, expected):
    assert docs_only(paths) is expected


def test_real_git_ranges_and_renames(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def git(*args):
        return subprocess.check_output(["git", *args], text=True).strip()

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (tmp_path / "README.md").write_text("initial\n")
    git("add", ".")
    git("commit", "-qm", "initial")
    base = git("rev-parse", "HEAD")
    (tmp_path / "runtime.py").write_text("pass\n")
    git("add", ".")
    git("commit", "-qm", "runtime")
    code = git("rev-parse", "HEAD")
    (tmp_path / "README.md").write_text("updated\n")
    git("commit", "-qam", "docs")
    head = git("rev-parse", "HEAD")
    assert docs_only(changed_paths("push", {"before": code, "after": head}))
    assert not docs_only(changed_paths("push", {"before": base, "after": head}))
    event = {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}
    assert set(changed_paths("pull_request", event)) == {"README.md", "runtime.py"}
    git("mv", "runtime.py", "CONTRIBUTING.md")
    git("commit", "-qm", "rename")
    paths = changed_paths("push", {"before": head, "after": git("rev-parse", "HEAD")})
    assert set(paths) == {"runtime.py", "CONTRIBUTING.md"}
    assert not docs_only(paths)


def test_manual_and_new_branch_use_full_checks():
    assert not docs_only(changed_paths("workflow_dispatch", {}))
    assert not docs_only(changed_paths("push", {"before": "0" * 40, "after": "a" * 40}))
