from pathlib import Path
from unittest.mock import Mock

import pytest

from contacts_cli import auth, cli
from contacts_cli.errors import SyncError

from .test_timestamps import undecorated


def test_authorize_subcommand_routes_credentials_and_token(monkeypatch, tmp_path):
    authorize, connect = Mock(), Mock()
    monkeypatch.setattr(cli, "authorize", authorize)
    monkeypatch.setattr(cli, "connect", connect)
    client, token = tmp_path / "client.json", tmp_path / "token.json"
    assert cli.main(["authorize", "--credentials", str(client), "--token", str(token)]) == 0
    authorize.assert_called_once_with(client, token, open_browser=True, timeout_seconds=300)
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
        config / "credentials.json",
        config / "token.json",
        open_browser=not manual,
        timeout_seconds=300,
    )


@pytest.fixture
def missing_token_flow(monkeypatch, tmp_path, api):
    token = tmp_path / "custom token.json"
    with pytest.raises(SyncError) as failure:
        auth.load_credentials(token)
    connect = Mock(side_effect=[failure.value, api])
    authorize = Mock()
    monkeypatch.setattr(cli, "connect", connect)
    monkeypatch.setattr(cli, "authorize", authorize)
    args = [
        "sender-sync",
        "--label",
        "Example/Delivery",
        "--contact",
        "people/c123",
        "--token",
        str(token),
    ]
    return args, token, connect, authorize


def interactive_terminal(monkeypatch):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.sys.stderr, "isatty", lambda: True)


def test_missing_token_accepts_and_resumes_preview(missing_token_flow, monkeypatch, capsys, server):
    interactive_terminal(monkeypatch)
    args, token, connect, authorize = missing_token_flow
    monkeypatch.setattr("builtins.input", lambda: "Yes")
    assert cli.main(args) == 0
    authorize.assert_called_once_with(
        auth.default_credentials_path(), token, open_browser=True, timeout_seconds=300
    )
    assert connect.call_count == 2
    assert all(call.args == (token,) for call in connect.call_args_list)
    assert server.writes == 0
    captured = capsys.readouterr()
    assert undecorated(captured.out).startswith("Authorization succeeded.\n\nContact:")
    assert "Preview only" in captured.out
    assert "--credentials" in captured.err and "--no-browser" in captured.err
    assert "Authorize now in your browser? [y/N]" in captured.err
    assert str(token) in captured.err


@pytest.mark.parametrize("answer", ["", "n", "no", "maybe", EOFError()])
def test_missing_token_decline_never_authorizes(missing_token_flow, monkeypatch, answer):
    interactive_terminal(monkeypatch)
    args, _, connect, authorize = missing_token_flow
    read = Mock(side_effect=answer) if isinstance(answer, Exception) else Mock(return_value=answer)
    monkeypatch.setattr("builtins.input", read)
    assert cli.main(args) == 1
    read.assert_called_once()
    authorize.assert_not_called()
    assert connect.call_count == 1


def test_missing_token_noninteractive_lists_options(missing_token_flow, monkeypatch, capsys):
    interactive_terminal(monkeypatch)
    args, _, connect, authorize = missing_token_flow
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    read = Mock(side_effect=AssertionError("must not prompt"))
    monkeypatch.setattr("builtins.input", read)
    assert cli.main(args) == 1
    assert "--no-browser" in capsys.readouterr().err
    read.assert_not_called()
    authorize.assert_not_called()
    assert connect.call_count == 1


def test_missing_token_authorization_failure_stops(missing_token_flow, monkeypatch):
    interactive_terminal(monkeypatch)
    args, _, connect, authorize = missing_token_flow
    monkeypatch.setattr("builtins.input", lambda: "y")
    authorize.side_effect = SyncError("Synthetic authorization failure")
    assert cli.main(args) == 1
    authorize.assert_called_once()
    assert connect.call_count == 1


def test_other_connection_errors_do_not_offer_authorization(monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect", Mock(side_effect=SyncError("Synthetic revoked token")))
    authorize, read = Mock(), Mock()
    monkeypatch.setattr(cli, "authorize", authorize)
    monkeypatch.setattr("builtins.input", read)
    assert cli.main(["sender-sync", "--label", "Example", "--contact", "people/c123"]) == 1
    authorize.assert_not_called()
    read.assert_not_called()
    assert "Authorize now" not in capsys.readouterr().err


def test_authorization_success_is_reported_before_contact_error(
    missing_token_flow, monkeypatch, capsys, api
):
    interactive_terminal(monkeypatch)
    args, _, _, _ = missing_token_flow
    monkeypatch.setattr("builtins.input", lambda: "y")

    def fail_contact(resource):
        assert undecorated(capsys.readouterr().out) == "Authorization succeeded.\n\n"
        raise SyncError("Synthetic invalid contact")

    monkeypatch.setattr(api, "get_contact", fail_contact)
    assert cli.main(args) == 1
    assert "Synthetic invalid contact" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["authorize", "sender-sync"])
def test_custom_auth_timeout(missing_token_flow, monkeypatch, command):
    interactive_terminal(monkeypatch)
    args, _, _, authorize = missing_token_flow
    monkeypatch.setattr("builtins.input", lambda: "y")
    if command == "authorize":
        args = ["authorize"]
    assert cli.main(args + ["--auth-timeout", "5"]) == 0
    assert authorize.call_args.kwargs["timeout_seconds"] == 5


@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5"])
def test_auth_timeout_rejects_invalid_values(monkeypatch, value):
    authorize = Mock()
    monkeypatch.setattr(cli, "authorize", authorize)
    with pytest.raises(SystemExit) as exc:
        cli.main(["authorize", "--auth-timeout", value])
    assert exc.value.code == 2
    authorize.assert_not_called()


@pytest.mark.parametrize("command", ["sender-sync", "duplicate"])
@pytest.mark.parametrize(
    "display_name,company,expected",
    [
        ("Jane", "Example Company", "name: Jane"),
        (None, "Example Company", "company: Example Company"),
        ("  ", "Example Company", "company: Example Company"),
        (None, None, "Unnamed"),
        ("", "  ", "Unnamed"),
    ],
)
def test_contact_heading_name_precedes_company(
    api, server, monkeypatch, capsys, command, display_name, company, expected
):
    server.person["names"] = [] if display_name is None else [{"displayName": display_name}]
    server.person["organizations"] = [] if company is None else [{"name": company}]
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    args = [command, "--contact", "people/c123"]
    if command == "sender-sync":
        args += ["--label", "Example/Delivery"]
    assert cli.main(args) == 0
    assert undecorated(capsys.readouterr().out).splitlines()[0] == f"Contact: {expected!r} (c123)"
    assert server.writes == 0


def test_help_command_order():
    help_text = cli.parser().format_help()
    expected = [
        "add-contact",
        "duplicate",
        "sender-sync",
        "list-email",
        "add-email",
        "remove-email",
        "add-label",
        "remove-label",
        "add-custom-field",
        "remove-custom-field",
        "validate-contact",
        "authorize",
    ]
    assert "{" + ",".join(expected) + "}" in help_text
    rows = [
        line.split()[0]
        for line in help_text.splitlines()
        if line.startswith("    ") and line.split() and line.split()[0] in expected
    ]
    assert rows == expected
