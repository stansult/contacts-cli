"""Upgrade saved metadata-only grants without changing contacts or old tokens on decline."""

import json
from unittest.mock import Mock

import pytest

from contacts_cli import auth, cli
from contacts_cli.errors import SyncError

OLD_SCOPES = [
    "https://www.googleapis.com/auth/gmail.metadata",
    "https://www.googleapis.com/auth/contacts",
]
NEW_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/contacts",
]


@pytest.fixture
def old_token(tmp_path):
    path = tmp_path / "custom token.json"
    path.write_text(
        json.dumps(
            {
                "client_id": "synthetic",
                "client_secret": "synthetic",
                "refresh_token": "synthetic",
                "token": "synthetic",
                "scopes": OLD_SCOPES,
                "expiry": "2000-01-01T00:00:00Z",
            }
        )
    )
    return path


def test_old_token_detected_before_refresh(old_token, monkeypatch):
    original = old_token.read_bytes()
    refresh = Mock()
    monkeypatch.setattr(auth.Credentials, "refresh", refresh)
    with pytest.raises(SyncError, match="gmail.readonly"):
        auth.load_credentials(old_token)
    refresh.assert_not_called()
    assert old_token.read_bytes() == original


@pytest.mark.parametrize("answer", ["y", "n", "", EOFError()])
def test_scope_upgrade_prompt(old_token, api, monkeypatch, capsys, answer):
    original = old_token.read_bytes()

    def connect(token):
        assert token == old_token
        if authorize.called:
            return api
        return auth.load_credentials(token)

    authorize = Mock()
    monkeypatch.setattr(cli, "connect", Mock(side_effect=connect))
    monkeypatch.setattr(cli, "authorize", authorize)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.sys.stderr, "isatty", lambda: True)
    read = Mock(side_effect=answer) if isinstance(answer, Exception) else Mock(return_value=answer)
    monkeypatch.setattr("builtins.input", read)
    args = [
        "sender-sync",
        "--contact",
        "people/c123",
        "--label",
        "Example/Delivery",
        "--token",
        str(old_token),
        "--auth-timeout",
        "5",
    ]
    assert cli.main(args) == (0 if answer == "y" else 1)
    output = capsys.readouterr()
    assert "Reauthorize now in your browser? [y/N]" in output.err
    assert "gmail.readonly" in output.err
    assert "--auth-timeout 5" in output.err
    assert str(old_token) in output.err
    read.assert_called_once()
    if answer == "y":
        authorize.assert_called_once_with(
            auth.default_credentials_path(), old_token, open_browser=True, timeout_seconds=5
        )
        assert "Authorization succeeded." in output.out
        assert "Searching senders: 3 inspected, 3 new senders" in output.err
    else:
        authorize.assert_not_called()
    assert old_token.read_bytes() == original


def test_scope_upgrade_noninteractive(old_token, monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect", auth.load_credentials)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    authorize = Mock()
    monkeypatch.setattr(cli, "authorize", authorize)
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("Must not prompt"))
    assert cli.connect_with_authorization(old_token) is None
    error = capsys.readouterr().err
    assert "gmail.readonly" in error
    assert "./contacts-cli authorize --token" in error
    assert "Reauthorize now" not in error
    authorize.assert_not_called()


def test_authorize_requests_new_scopes_and_preserves_old_token_on_failure(
    old_token, tmp_path, monkeypatch
):
    original = old_token.read_bytes()
    client = tmp_path / "client.json"
    client.write_text('{"installed": {"client_id": "synthetic"}}')
    credentials = Mock()
    credentials.granted_scopes = OLD_SCOPES
    flow = Mock()
    flow.run_local_server.return_value = credentials
    factory = Mock(return_value=flow)
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_config", factory)
    with pytest.raises(SyncError, match="Required scopes"):
        auth.authorize(client, old_token)
    assert set(factory.call_args.kwargs["scopes"]) == set(NEW_SCOPES)
    assert old_token.read_bytes() == original


def test_new_scope_token_accepted_without_browser(old_token):
    data = json.loads(old_token.read_text())
    data.update(scopes=NEW_SCOPES, expiry="2099-01-01T00:00:00Z")
    old_token.write_text(json.dumps(data))
    assert auth.load_credentials(old_token).valid


def test_successful_upgrade_replaces_saved_scopes(old_token, tmp_path, monkeypatch):
    from datetime import datetime

    client = tmp_path / "client.json"
    client.write_text('{"installed": {"client_id": "synthetic"}}')
    credentials = auth.Credentials(
        token="synthetic-new",
        refresh_token="synthetic-new-refresh",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="synthetic",
        client_secret="synthetic",
        scopes=NEW_SCOPES,
        expiry=datetime(2099, 1, 1),
    )
    flow = Mock()
    flow.run_local_server.return_value = credentials
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_config", Mock(return_value=flow))
    auth.authorize(client, old_token)
    saved = json.loads(old_token.read_text())
    assert saved["token"] == "synthetic-new"
    assert set(saved["scopes"]) == set(NEW_SCOPES)
    assert auth.load_credentials(old_token).valid


@pytest.mark.parametrize("failure", ["timeout", "denied"])
def test_failed_upgrade_preserves_existing_token(old_token, tmp_path, monkeypatch, failure):
    from google_auth_oauthlib.flow import WSGITimeoutError
    from oauthlib.oauth2 import AccessDeniedError

    original = old_token.read_bytes()
    client = tmp_path / "client.json"
    client.write_text('{"installed": {"client_id": "synthetic"}}')
    flow = Mock()
    flow.run_local_server.side_effect = (
        WSGITimeoutError() if failure == "timeout" else AccessDeniedError()
    )
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_config", Mock(return_value=flow))
    with pytest.raises(SyncError):
        auth.authorize(client, old_token)
    assert old_token.read_bytes() == original
