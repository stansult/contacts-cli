"""Rejected refresh grants survive the worker boundary and offer authorization once."""

import json
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from google.auth.exceptions import RefreshError

from contacts_cli import auth, cli, deadline, read_worker
from contacts_cli.errors import SyncError

WORKER = [sys.executable, str(Path(__file__).parent / "fixtures" / "deadline_worker.py")]


@pytest.fixture
def expired_token(tmp_path):
    path = tmp_path / "expired token.json"
    path.write_text(
        json.dumps(
            {
                "client_id": "synthetic",
                "client_secret": "synthetic",
                "refresh_token": "revoked-refresh",
                "token": "synthetic",
                "scopes": list(auth.SCOPES),
                "expiry": "2000-01-01T00:00:00Z",
            }
        )
    )
    return path


def test_fixture_reports_rejected_grant(expired_token):
    payload = {"action": "refresh", "credentials": json.loads(expired_token.read_text())}
    result = subprocess.run(
        WORKER, input=json.dumps(payload), text=True, capture_output=True, timeout=5, check=True
    )
    error = json.loads(result.stdout)["error"]
    assert error["details"][0]["type"] == "RefreshError"
    assert "invalid_grant" in error["details"][0]["message"]
    assert "expired or revoked" in error["details"][0]["message"]


@pytest.mark.parametrize("answer", ["y", "n", "", EOFError(), "noninteractive", "denied", "again"])
def test_rejected_refresh_prompt_and_resume(expired_token, api, monkeypatch, capsys, answer):
    original = expired_token.read_bytes()
    worker_call = deadline.worker_call
    monkeypatch.setattr(deadline, "worker_call", lambda payload: worker_call(payload, WORKER))
    authorize = Mock(side_effect=SyncError("Authorization failed") if answer == "denied" else None)
    monkeypatch.setattr(cli, "authorize", authorize)

    def connect(path):
        if authorize.called and answer != "again":
            return api
        return auth.load_credentials(path)

    monkeypatch.setattr(cli, "connect", Mock(side_effect=connect))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: answer != "noninteractive")
    monkeypatch.setattr(cli.sys.stderr, "isatty", lambda: True)
    reply = "y" if answer in {"denied", "again"} else answer
    read = Mock(side_effect=reply) if isinstance(reply, Exception) else Mock(return_value=reply)
    monkeypatch.setattr("builtins.input", read)
    assert cli.main(
        ["list-email", "--contact", "c123", "--token", str(expired_token), "--auth-timeout", "5"]
    ) == (0 if answer == "y" else 1)
    output = capsys.readouterr()
    assert "expired or been revoked" in output.err
    assert "lacks required scopes" not in output.err
    assert "Google API read failed" not in output.err
    assert str(expired_token) in output.err
    if answer == "noninteractive":
        read.assert_not_called()
        assert "Reauthorize now" not in output.err
    else:
        read.assert_called_once()
        assert "Reauthorize now in your browser? [y/N]" in output.err
    if answer in {"y", "denied", "again"}:
        authorize.assert_called_once_with(
            auth.default_credentials_path(), expired_token, open_browser=True, timeout_seconds=5
        )
    else:
        authorize.assert_not_called()
    if answer == "y":
        assert "Email addresses:" in output.out
    assert expired_token.read_bytes() == original


@pytest.mark.parametrize(
    "error",
    [
        RefreshError("invalid_grant", {"error": "invalid_grant"}, retryable=True),
        RefreshError("invalid_client", {"error": "invalid_client"}),
        RefreshError("temporarily_unavailable", {"error": "temporarily_unavailable"}),
        RefreshError("invalid_grant in message only"),
        ValueError("invalid_grant"),
        socket.gaierror(-2, "synthetic DNS failure"),
        ConnectionError("synthetic disconnect"),
    ],
)
def test_other_failures_do_not_offer_browser(error, expired_token, monkeypatch):
    def connect(path):
        return deadline.check_worker_result(read_worker.error_reply(error))

    monkeypatch.setattr(cli, "connect", connect)
    authorize = Mock()
    monkeypatch.setattr(cli, "authorize", authorize)
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("Must not prompt"))
    with pytest.raises((SyncError, ConnectionError)):
        cli.connect_with_authorization(expired_token)
    authorize.assert_not_called()
