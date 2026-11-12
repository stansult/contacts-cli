"""Check that CI infrastructure detects bad artifacts and documentation links."""

import zipfile

import pytest

from scripts.check_repository import check_archive, check_links


@pytest.mark.parametrize(
    "bad_file", ["HANDOFF.md", "credentials.json", ".env", "token.json", ".contacts-cli/runs.jsonl"]
)
def test_archive_rejects_private_files(tmp_path, bad_file):
    archive = tmp_path / "bad.whl"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(bad_file, "synthetic")
    with pytest.raises(ValueError, match="forbidden packaged file"):
        check_archive(archive)


def test_archive_rejects_missing_runtime_module(tmp_path):
    archive = tmp_path / "bad.whl"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("contacts_cli/cli.py", "")
    with pytest.raises(ValueError, match="missing module"):
        check_archive(archive)


def test_documentation_links_detect_missing_files_and_headings(tmp_path):
    (tmp_path / "CONTRIBUTING.md").write_text("# Contributing\n")
    readme = tmp_path / "README.md"
    readme.write_text("[missing](missing.md)")
    with pytest.raises(ValueError, match="missing link"):
        check_links(tmp_path)
    readme.write_text("[missing](CONTRIBUTING.md#absent)")
    with pytest.raises(ValueError, match="missing heading"):
        check_links(tmp_path)
    readme.write_text("[present](CONTRIBUTING.md#contributing)")
    check_links(tmp_path)


@pytest.mark.parametrize("kind", ["wheel", "source"])
def test_archive_accepts_valid_runtime_layout(tmp_path, kind):
    import io
    import tarfile

    modules = (
        "cli.py",
        "auth.py",
        "api.py",
        "core.py",
        "duplicate.py",
        "errors.py",
        "progress.py",
        "metrics.py",
    )
    if kind == "wheel":
        path = tmp_path / "valid.whl"
        with zipfile.ZipFile(path, "w") as archive:
            for module in modules:
                archive.writestr("contacts_cli/" + module, "# synthetic module\n")
    else:
        path = tmp_path / "valid.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for module in modules:
                data = b"# synthetic module\n"
                info = tarfile.TarInfo("contacts_cli-0.1.0/src/contacts_cli/" + module)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
    check_archive(path)
