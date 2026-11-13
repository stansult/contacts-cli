"""Exclusion files extend explicit addresses and fail before authorization."""

from pathlib import Path

import pytest

from contacts_cli import cli

from .test_exclude import ARGS

FIXTURE = Path(__file__).parent / "fixtures" / "exclusions.txt"


def test_files_and_addresses_combine_and_are_reread(api, server, monkeypatch, tmp_path, capsys):
    first = tmp_path / "first.txt"
    first.write_bytes(FIXTURE.read_bytes())
    second = tmp_path / "second.txt"
    second.write_text("trash@example.com\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    args = ARGS + [
        "--exclude-file",
        "first.txt",
        "--exclude-file",
        "second.txt",
        "--exclude",
        "DIRECT@example.com",
    ]
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    assert "Proposed additions: 0" in output
    for call in server.calls:
        if call[1].endswith("/messages"):
            query = call[2]["q"][0]
            assert query.count('-from:"new@example.com"') == 1
            assert query.count('-from:"spam@example.com"') == 1
            assert '-from:"me@example.com"' in query
            assert '-from:"trash@example.com"' in query
            assert '-from:"direct@example.com"' in query
    first.write_text("# now empty\n\n", encoding="utf-8")
    assert cli.main(args) == 0
    assert "Proposed additions: 2" in capsys.readouterr().out
    assert server.writes == 0


@pytest.mark.parametrize(
    "line",
    [
        "not-an-email",
        "@example.com",
        "person@",
        "*@example.com",
        "one@example.com, two@example.com",
        "Name <one@example.com>",
    ],
)
def test_invalid_line_reports_file_and_line_before_authorization(
    tmp_path, monkeypatch, capsys, line
):
    path = tmp_path / "bad.txt"
    path.write_text("# comment\nvalid@example.com\n" + line + "\n", encoding="utf-8")
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("authorization"))
    assert cli.main(ARGS + ["--exclude-file", str(path)]) == 1
    assert f"{path}:3: expected one supported email address" in capsys.readouterr().err


@pytest.mark.parametrize("kind", ["missing", "encoding", "unreadable"])
def test_file_errors_before_authorization(tmp_path, monkeypatch, capsys, kind):
    path = tmp_path / "input.txt"
    if kind == "encoding":
        path.write_bytes(b"\xff\xfe")
    if kind == "unreadable":
        original = Path.read_text

        def denied(self, *args, **kwargs):
            if self == path:
                raise PermissionError("synthetic denial")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", denied)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("authorization"))
    assert cli.main(ARGS + ["--exclude-file", str(path)]) == 1
    assert str(path) in capsys.readouterr().err


def test_file_fixture_parsing_contract():
    assert cli.file_exclusions([FIXTURE]) == {"new@example.com", "spam@example.com"}
