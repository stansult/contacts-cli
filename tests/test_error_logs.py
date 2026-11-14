"""Error-response logging preserves evidence without serializing requests."""

import base64
import json
from unittest.mock import Mock

import httplib2
import pytest
from googleapiclient.errors import HttpError
from googleapiclient.http import HttpRequest

from contacts_cli import cli, error_logs
from contacts_cli.api import execute
from contacts_cli.errors import SyncError, WriteUnverified


@pytest.mark.parametrize("status", [400, 429, 503])
@pytest.mark.parametrize(
    "body",
    [
        b'{"error":{"reason":"rateLimitExceeded","details":[1,2]}}',
        b"<html>Unavailable</html>",
        b"\xff\x00",
    ],
)
def test_http_response_logged_exactly(status, body, capsys):
    http = Mock()
    http.request.return_value = (httplib2.Response({"status": status}), body)
    request = HttpRequest(
        http,
        lambda *a: None,
        "https://example.com/private?token=SECRET",
        method="POST",
        body='{"contact":"PRIVATE"}',
        headers={"Authorization": "Bearer SECRET"},
        methodId="people.people.createContact",
    )
    with pytest.raises(WriteUnverified if status == 503 else SyncError):
        execute(request, write=True, operation="creation")
    files = list(error_logs.log_directory().glob("*.json"))
    assert len(files) == 1
    record = json.loads(files[0].read_text())
    assert record["http_status"] == status
    assert record["operation"] == "people.people.createContact"
    restored = (
        record["response_body"].encode("utf-8")
        if record["response_body_encoding"] == "utf-8"
        else base64.b64decode(record["response_body"])
    )
    assert restored == body
    assert "SECRET" not in files[0].read_text() and "PRIVATE" not in files[0].read_text()
    assert files[0].stat().st_mode & 0o777 == 0o600
    assert str(files[0]) in capsys.readouterr().err
    assert http.request.call_count == 1


def test_cli_command_context_and_unique_files(api, server, monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    server.create_status = 429
    for _ in range(2):
        assert cli.main(["add-contacts", "--name", "Example", "--apply"]) == 1
    records = [json.loads(p.read_text()) for p in error_logs.log_directory().glob("*.json")]
    assert len(records) == 2
    assert all(r["command"] == "add-contact" for r in records)
    assert error_logs.COMMAND.get() is None
    assert capsys.readouterr().err.count("Error details saved to:") == 2


def test_read_error_is_logged_without_changing_exception():
    request = Mock(methodId="people.people.getBatchGet")
    request.execute.side_effect = HttpError(httplib2.Response({"status": 403}), b"{}")
    with pytest.raises(SyncError, match="HTTP 403"):
        execute(request)
    record = json.loads(next(error_logs.log_directory().glob("*.json")).read_text())
    assert record["write"] is False
    request.execute.assert_called_once_with(num_retries=3)


def test_log_failure_does_not_hide_original_error(monkeypatch, tmp_path, capsys):
    path = tmp_path / "file"
    path.write_text("not a directory")
    monkeypatch.setenv("CONTACTS_CLI_ERROR_LOG_DIR", str(path))
    request = Mock(methodId="people.people.createContact")
    request.execute.side_effect = HttpError(httplib2.Response({"status": 429}), b"{}")
    with pytest.raises(SyncError, match="HTTP 429"):
        execute(request, write=True)
    assert "could not be saved locally" in capsys.readouterr().err
    assert path.read_text() == "not a directory"


def test_success_does_not_create_logs():
    request = Mock()
    request.execute.return_value = {"ok": True}
    assert execute(request) == {"ok": True}
    assert not error_logs.log_directory().exists()
