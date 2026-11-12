from pathlib import Path
from unittest.mock import Mock

import pytest

from contacts_cli import cli


def test_authorize_subcommand_routes_credentials_and_token(monkeypatch, tmp_path):
    authorize, connect = Mock(), Mock()
    monkeypatch.setattr(cli, "authorize", authorize)
    monkeypatch.setattr(cli, "connect", connect)
    client, token = tmp_path / "client.json", tmp_path / "token.json"
    assert cli.main(["authorize", "--credentials", str(client), "--token", str(token)]) == 0
    authorize.assert_called_once_with(client, token, open_browser=True)
    connect.assert_not_called()


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--label", "Example", "--contact", "people/c123"],
        ["--authorize", "--credentials", "/tmp/client.json"],
        ["sender-sync", "--contact", "people/c123"],
        ["sender-sync", "--label", "Example"],
        ["authorize", "--credentials", "/tmp/client.json", "--apply"],
        [
            "sender-sync",
            "--label",
            "Example",
            "--contact",
            "people/c123",
            "--credentials",
            "/tmp/client.json",
        ],
    ],
)
def test_invalid_commands_do_not_access_google(monkeypatch, args):
    authorize, connect = Mock(), Mock()
    monkeypatch.setattr(cli, "authorize", authorize)
    monkeypatch.setattr(cli, "connect", connect)
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2
    authorize.assert_not_called()
    connect.assert_not_called()


def test_sender_sync_forwards_custom_token(api, monkeypatch, tmp_path):
    connect = Mock(return_value=api)
    monkeypatch.setattr(cli, "connect", connect)
    token = tmp_path / "custom.json"
    assert (
        cli.main(
            [
                "sender-sync",
                "--label",
                "Example/Delivery",
                "--contact",
                "people/c123",
                "--token",
                str(token),
            ]
        )
        == 0
    )
    connect.assert_called_once_with(Path(token))


@pytest.mark.parametrize("manual", [False, True])
def test_authorize_defaults_and_browser_choice(monkeypatch, tmp_path, manual):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    authorize = Mock()
    monkeypatch.setattr(cli, "authorize", authorize)
    assert cli.main(["authorize"] + (["--no-browser"] if manual else [])) == 0
    config = tmp_path / ".config" / "contacts-cli"
    authorize.assert_called_once_with(
        config / "credentials.json", config / "token.json", open_browser=not manual
    )
