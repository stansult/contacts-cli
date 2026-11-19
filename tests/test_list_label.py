"""List only this contact's active user labels without prompting or writing."""

from copy import deepcopy

import pytest

from contacts_cli import cli

from .test_label_edit import group
from .test_remove_label import apply_group


@pytest.mark.parametrize("command", ["list-label", "list-labels"])
def test_listing(command, api, server, monkeypatch, capsys):
    for name in ("Zulu", "alpha", "Elsewhere", "System", "Deleted"):
        resource = group(server, name)
        if name != "Elsewhere":
            apply_group(server, resource)
        if name == "System":
            server.groups[resource]["groupType"] = "SYSTEM_CONTACT_GROUP"
        if name == "Deleted":
            server.groups[resource]["metadata"] = {"deleted": True}
    before = deepcopy(server.person)
    baseline = server.writes
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("prompt"))
    assert cli.main([command, "--contact", "c123"]) == 0
    output = capsys.readouterr().out
    assert "Contact:" in output
    assert "Labels: 2 labels" in output
    assert "1. alpha" in output and "2. Zulu" in output
    assert all(name not in output for name in ("Elsewhere", "System", "Deleted"))
    assert server.person == before and server.writes == baseline


def test_empty_listing(api, server, monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(["list-label", "--contact", "c123"]) == 0
    assert "Labels: 0 labels" in capsys.readouterr().out
    assert server.writes == 0


def test_global_options_and_no_apply():
    args = cli.parser().parse_args(["list-label", "--contact", "c123", "--token", "/tmp/token"])
    assert str(args.token) == "/tmp/token"
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["list-label", "--contact", "c123", "--apply"])
