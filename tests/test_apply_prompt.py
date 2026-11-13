"""Interactive write consent after a complete, visible preview."""

import sys

import pytest

from contacts_cli import cli


@pytest.mark.parametrize(
    "command,prompt",
    [
        ("sender-sync", "Apply these additions? [y/N]"),
        ("duplicate", "Create this duplicate? [y/N]"),
    ],
)
@pytest.mark.parametrize(
    "answer,apply,tty,expected",
    [
        ("y", False, (True, True, True), 1),
        (" YES ", False, (True, True, True), 1),
        ("n", False, (True, True, True), 0),
        ("", False, (True, True, True), 0),
        ("maybe", False, (True, True, True), 0),
        (None, False, (True, True, True), 0),
        ("y", False, (False, True, True), 0),
        ("y", False, (True, False, True), 0),
        ("y", False, (True, True, False), 0),
        ("n", True, (True, True, True), 1),
    ],
)
def test_apply_consent(
    command, prompt, answer, apply, tty, expected, api, server, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream, interactive in zip((sys.stdin, sys.stdout, sys.stderr), tty, strict=True):
        monkeypatch.setattr(stream, "isatty", lambda value=interactive: value)
    asked = []

    def respond():
        output = capsys.readouterr()
        assert prompt in output.err
        assert (
            "Proposed additions: 3"
            if command == "sender-sync"
            else "Contact: 'name: Example Delivery' (c123)"
        ) in output.out
        assert server.writes == 0
        asked.append(True)
        if answer is None:
            raise EOFError
        return answer

    monkeypatch.setattr("builtins.input", respond)
    argv = [command, "--contact", "people/c123"]
    if command == "sender-sync":
        argv += ["--label", "Example/Delivery"]
    if apply:
        argv += ["--apply"]
    assert cli.main(argv) == 0
    assert bool(asked) == (all(tty) and not apply)
    assert server.writes == expected


def test_no_additions_does_not_prompt(api, server, monkeypatch):
    server.mailbox["messages"] = []
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("No write to confirm"))
    assert cli.main(["sender-sync", "--label", "Example/Delivery", "--contact", "people/c123"]) == 0
    assert server.writes == 0
