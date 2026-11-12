import json
import stat
from unittest.mock import Mock

import httplib2
import pytest
from google.auth.exceptions import RefreshError
from google_auth_oauthlib.flow import WSGITimeoutError
from googleapiclient.errors import HttpError
from oauthlib.oauth2 import AccessDeniedError

from contacts_cli import auth
from contacts_cli.errors import SyncError


def test_missing_token_never_starts_browser(tmp_path, monkeypatch):
    flow = Mock()
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_config", flow)
    with pytest.raises(SyncError, match="No token"):
        auth.load_credentials(tmp_path / "token.json")
    flow.assert_not_called()


def test_tokens_and_clients_rejected_in_git_worktree(tmp_path):
    (tmp_path / ".git").mkdir()
    with pytest.raises(SyncError, match="outside Git"):
        auth.private_path(tmp_path / "nested" / "token.json")


def test_token_symlink_into_worktree_rejected(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: elsewhere")
    link = tmp_path / "link.json"
    link.symlink_to(repo / "token.json")
    with pytest.raises(SyncError, match="outside Git"):
        auth.private_path(link)


def test_atomic_private_token_file(tmp_path):
    token = tmp_path / "private" / "token.json"
    credentials = Mock()
    credentials.to_json.return_value = '{"token": "synthetic-only"}'
    auth.save_credentials(credentials, token)
    assert json.loads(token.read_text())["token"] == "synthetic-only"
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    assert stat.S_IMODE(token.parent.stat().st_mode) == 0o700
    assert list(token.parent.iterdir()) == [token]


@pytest.mark.parametrize("fault", ["scopes", "refresh"])
def test_invalid_credentials_do_not_fallback_to_authorization(tmp_path, monkeypatch, fault):
    token = tmp_path / "token.json"
    token.write_text("{}")
    credentials = Mock()
    credentials.has_scopes.return_value = fault != "scopes"
    credentials.valid = False
    credentials.refresh.side_effect = RefreshError("synthetic revoked token")
    monkeypatch.setattr(auth.Credentials, "from_authorized_user_file", lambda _: credentials)
    flow = Mock()
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_config", flow)
    with pytest.raises(SyncError):
        auth.load_credentials(token)
    flow.assert_not_called()


def test_refresh_is_saved_without_browser(tmp_path, monkeypatch):
    token = tmp_path / "token.json"
    token.write_text("{}")
    credentials = Mock()
    credentials.has_scopes.return_value = True
    credentials.valid = False
    credentials.to_json.return_value = '{"token": "refreshed-synthetic-only"}'
    monkeypatch.setattr(auth.Credentials, "from_authorized_user_file", lambda _: credentials)
    assert auth.load_credentials(token) is credentials
    credentials.refresh.assert_called_once()
    assert json.loads(token.read_text())["token"] == "refreshed-synthetic-only"


def test_authorization_is_explicit_and_never_opens_browser(tmp_path, monkeypatch):
    client = tmp_path / "client.json"
    client.write_text('{"installed": {"client_id": "synthetic"}}')
    credentials = Mock()
    credentials.granted_scopes = auth.SCOPES
    credentials.to_json.return_value = '{"token": "synthetic-only"}'
    flow = Mock()
    flow.run_local_server.return_value = credentials
    factory = Mock(return_value=flow)
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_config", factory)
    auth.authorize(client, tmp_path / "token.json")
    assert factory.call_args.kwargs["autogenerate_code_verifier"] is True
    assert flow.run_local_server.call_args.kwargs["open_browser"] is False
    assert flow.run_local_server.call_args.kwargs["host"] == "127.0.0.1"


def test_denied_scopes_do_not_save_token(tmp_path, monkeypatch):
    client = tmp_path / "client.json"
    client.write_text('{"installed": {"client_id": "synthetic"}}')
    credentials = Mock()
    credentials.granted_scopes = [auth.SCOPES[0]]
    flow = Mock()
    flow.run_local_server.return_value = credentials
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_config", lambda *a, **k: flow)
    with pytest.raises(SyncError, match="scopes"):
        auth.authorize(client, tmp_path / "token.json")
    assert not (tmp_path / "token.json").exists()


@pytest.mark.parametrize("error", [AccessDeniedError(), WSGITimeoutError("synthetic timeout")])
def test_oauth_denial_or_timeout_is_clean_error(tmp_path, monkeypatch, error):
    client = tmp_path / "client.json"
    client.write_text('{"installed": {"client_id": "synthetic"}}')
    flow = Mock()
    flow.run_local_server.side_effect = error
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_config", lambda *a, **k: flow)
    with pytest.raises(SyncError, match="Authorization failed"):
        auth.authorize(client, tmp_path / "token.json")
    assert not (tmp_path / "token.json").exists()


def test_transport_does_not_replay_writes_after_401(tmp_path, monkeypatch):
    credentials = Mock(universe_domain="googleapis.com")
    http = Mock()
    http.request.side_effect = [
        (httplib2.Response({"status": "401"}), b'{"error": {"message": "synthetic"}}'),
        (httplib2.Response({"status": "200"}), b"{}"),
    ]
    monkeypatch.setattr(auth, "load_credentials", lambda _: credentials)
    monkeypatch.setattr(auth.httplib2, "Http", lambda **kwargs: http)
    api = auth.connect(tmp_path / "token.json")
    with pytest.raises(HttpError):
        api.people.people().updateContact(
            resourceName="people/c123", updatePersonFields="emailAddresses", body={}
        ).execute(num_retries=0)
    assert http.request.call_count == 1
    credentials.refresh.assert_not_called()
