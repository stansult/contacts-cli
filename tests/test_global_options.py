"""Global help placement and options on either side of a command."""

from pathlib import Path

import pytest

from contacts_cli import cli


@pytest.mark.parametrize(
    "command", ["authorize", "list-email", "add-email", "remove-email", "sender-sync", "duplicate"]
)
def test_global_help_only_at_top(command, capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    top = capsys.readouterr().out
    assert "--token" in top and "--auth-timeout" not in top
    with pytest.raises(SystemExit):
        cli.main([command, "--help"])
    help_text = capsys.readouterr().out
    assert "--token" not in help_text and "--auth-timeout" not in help_text
    assert "contacts-cli --help" in help_text


@pytest.mark.parametrize(
    "command",
    [
        "list-email",
        "list-emails",
        "add-emails",
        "remove-emails",
        "authorize",
        "sender-sync",
        "duplicate",
    ],
)
@pytest.mark.parametrize("position", ["before", "after", "both"])
def test_global_option_positions(command, position, monkeypatch):
    captured = []
    monkeypatch.setattr(cli, "execute_command", lambda args: captured.append(args) or 0)
    inputs = [] if command == "authorize" else ["--contact", "people/c123"]
    if command == "add-emails":
        inputs += ["--add", "a@example.com"]
    if command == "remove-emails":
        inputs += ["--remove", "a@example.com"]
    if command == "sender-sync":
        inputs += ["--label", "Example"]
    before = ["--token", "before.json", "--auth-timeout", "5"] if position != "after" else []
    after = ["--token", "after.json", "--auth-timeout", "9"] if position != "before" else []
    assert cli.main(before + [command] + inputs + after) == 0
    assert captured[0].token == Path("before.json" if position == "before" else "after.json")
    assert captured[0].auth_timeout == (5 if position == "before" else 9)
    expected = command.removesuffix("s") if command.endswith("emails") else command
    assert captured[0].command == expected


def test_plural_after_equals_global_and_alias_like_token(monkeypatch):
    captured = []
    monkeypatch.setattr(cli, "execute_command", lambda args: captured.append(args) or 0)
    assert (
        cli.main(
            ["--token=add-emails", "--auth-timeout=5", "list-emails", "--contact", "people/c123"]
        )
        == 0
    )
    assert captured[0].token == Path("add-emails")
    assert captured[0].command == "list-email"
