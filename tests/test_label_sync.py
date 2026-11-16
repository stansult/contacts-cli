"""Label sync needs no filter discovery; address-based selection requires search."""

import sys

import pytest

from contacts_cli import cli

ARGS = ["sender-sync", "--contact", "c123", "--label", "Example/Delivery"]


@pytest.mark.parametrize("apply", [False, True])
def test_label_sync_without_filter_fetch(api, server, monkeypatch, capsys, apply):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *args: api)
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    prompts = []

    def decline():
        prompts.append(capsys.readouterr().err)
        return "n"

    monkeypatch.setattr("builtins.input", decline)
    assert cli.main(ARGS + (["--apply"] if apply else [])) == 0
    output = capsys.readouterr()
    assert not any("filter" in path for _, path, _, _ in server.calls)
    assert len(prompts) == (0 if apply else 1)
    if prompts:
        assert "Apply these additions?" in prompts[0]
    assert "Ungrouped:" not in output.out
    assert server.writes == int(apply)
    assert len(server.person["emailAddresses"]) == (5 if apply else 2)


@pytest.mark.parametrize("apply", [False, True])
def test_label_exclude_other_rejected_before_connection(monkeypatch, capsys, apply):
    def forbidden(*args):
        pytest.fail("Invalid label selection must fail before authorization")

    monkeypatch.setattr(cli, "connect_with_authorization", forbidden)
    assert cli.main(ARGS + ["--exclude-other"] + (["--apply"] if apply else [])) == 1
    assert "--exclude-other cannot be used with --label" in capsys.readouterr().err


def test_refresh_filters_not_advertised(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "refresh-filters" not in capsys.readouterr().out
