"""Removal wildcards expand once against the preview, then select concrete email entries."""

from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.address_inputs import edit_inputs
from contacts_cli.email_edit import make_edit_plan
from contacts_cli.errors import SyncError


@pytest.mark.parametrize(
    "pattern,expected",
    [
        ("abc*@example.com", ["abc@example.com", "abcdef@example.com"]),
        ("*@example.com", ["abc@example.com", "abcdef@example.com", "a+b@example.com"]),
        ("*@*.example.com", ["x@sub.example.com"]),
        (
            "*example.com",
            [
                "abc@example.com",
                "abcdef@example.com",
                "a+b@example.com",
                "x@sub.example.com",
                "x@notexample.com",
            ],
        ),
        ("A+B*@EXAMPLE.COM", ["a+b@example.com"]),
        ("abc**@example.com", ["abc@example.com", "abcdef@example.com"]),
        (
            "*",
            [
                "abc@example.com",
                "abcdef@example.com",
                "a+b@example.com",
                "x@sub.example.com",
                "x@notexample.com",
            ],
        ),
        ("example.com*", []),
    ],
)
def test_pattern_semantics(server, pattern, expected):
    values = [
        "abc@example.com",
        "abcdef@example.com",
        "a+b@example.com",
        "x@sub.example.com",
        "x@notexample.com",
    ]
    server.person["emailAddresses"] = [{"value": value} for value in values]
    entries = edit_inputs([pattern], [], "--remove")
    plan = make_edit_plan(server.person, entries, remove=True)
    assert {entry["value"] for entry in plan.removed} == set(expected)
    assert plan.emails == [{"value": value} for value in values if value not in expected]
    assert plan.absent == ([] if expected else [pattern])


def test_overlap_files_and_duplicate_groups(server, tmp_path):
    server.person["emailAddresses"] = [
        {"value": "A@example.com", "type": "Work"},
        {"value": "a@example.com"},
        {"value": "b@sub.example.com"},
        {"value": "keep@elsewhere.com"},
    ]
    file = tmp_path / "remove.txt"
    file.write_text(
        "# Patterns have no shell quotes\n*@*.example.com — ignored label\n\n*missing.com\n"
    )
    entries = edit_inputs(
        ["*@example.com", "a@example.com", "*example.com", "*MISSING.COM"], [file], "--remove"
    )
    plan = make_edit_plan(server.person, entries, remove=True)
    assert len(plan.changes) == 2 and len(plan.removed) == 3
    assert len(plan.absent) == 1 and plan.absent[0].casefold() == "*missing.com"
    assert plan.emails == [{"value": "keep@elsewhere.com"}]


@pytest.mark.parametrize(
    "value",
    [
        "*a?@example.com",
        "*a[bc]@example.com",
        "'*@example.com'",
        '"*@example.com"',
        "Name <*@example.com>",
        "*a\nb@example.com",
    ],
)
def test_invalid_patterns_fail_before_google(monkeypatch, capsys, value):
    monkeypatch.setattr(
        cli, "connect_with_authorization", lambda *a: pytest.fail("Google accessed")
    )
    assert cli.main(["remove-email", "--contact", "c123", "--remove", value]) == 1
    assert "--remove #1" in capsys.readouterr().err


def test_add_still_rejects_wildcards():
    with pytest.raises(SyncError):
        edit_inputs(["*@example.com"], [], "--add")


def setup(api, monkeypatch, answers=None):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (cli.sys.stdin, cli.sys.stdout, cli.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: answers is not None)
    replies = iter(answers or [])
    monkeypatch.setattr("builtins.input", lambda: next(replies))


@pytest.mark.parametrize("mode", ["subset", "cancel", "preview", "apply", "stale"])
def test_cli_pattern_selection_and_preservation(api, server, monkeypatch, mode):
    server.person["emailAddresses"] = [
        {"value": "a@example.com", "type": "Work", "metadata": {"sourcePrimary": True}},
        {"value": "A@example.com"},
        {"value": "b@example.com", "type": "Keep"},
        {"value": "keep@elsewhere.com"},
    ]
    before = deepcopy(server.person["emailAddresses"])
    setup(
        api,
        monkeypatch,
        ["1", "y"] if mode in {"subset", "stale"} else ["q"] if mode == "cancel" else None,
    )
    server.concurrent_edit = mode == "stale"
    args = ["remove-email", "--contact", "c123", "--remove", "*@example.com"]
    if mode == "apply":
        args += ["--apply"]
    assert cli.main(args) == (1 if mode == "stale" else 0)
    if mode in {"cancel", "preview"}:
        assert server.person["emailAddresses"] == before and server.writes == 0
    elif mode == "stale":
        assert server.writes == 0
    else:
        assert server.person["emailAddresses"] == (before[1:] if mode == "subset" else before[3:])
        assert server.writes == 1


def test_selected_literal_star_address_does_not_reexpand(api, server, monkeypatch):
    server.person["emailAddresses"] = [{"value": "a*@example.com"}, {"value": "abc@example.com"}]
    setup(api, monkeypatch, ["1", "y"])
    assert cli.main(["remove-email", "--contact", "c123", "--remove", "*@example.com"]) == 0
    assert server.person["emailAddresses"] == [{"value": "abc@example.com"}]


def test_unmatched_pattern_does_not_prompt(api, server, monkeypatch, capsys):
    setup(api, monkeypatch, [])
    assert cli.main(["remove-email", "--contact", "c123", "--remove", "*missing.example"]) == 0
    output = capsys.readouterr().out
    assert "Not found: 1 address or pattern" in output
    assert "No changes selected" in output
    assert server.writes == 0


def test_invalid_file_pattern_reports_line(tmp_path):
    path = tmp_path / "remove.txt"
    path.write_text("# comment\n*@example.com\n*bad?.com\n")
    with pytest.raises(SyncError, match="remove.txt:3:"):
        edit_inputs([], [path], "--remove")
