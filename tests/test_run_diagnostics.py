"""Opt-in sender-sync diagnostics reach disk before a stalled transport returns."""

import json

import pytest

from contacts_cli import cli, error_logs


def events():
    paths = list(error_logs.log_directory().glob("run-*.jsonl"))
    assert len(paths) == 1
    return paths[0], [json.loads(line) for line in paths[0].read_text().splitlines()]


@pytest.mark.parametrize(
    "failure,code", [(TimeoutError("timed out"), 1), (KeyboardInterrupt(), 130), (None, 0)]
)
def test_same_command_records_live_attempt_and_exit(
    api, server, monkeypatch, capsys, failure, code
):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    original = server.request
    observed = []

    def request(uri, method="GET", **kwargs):
        if "/messages?" in uri:
            path, rows = events()
            assert rows[-1]["event"] == "attempt_start"
            assert rows[-1]["operation"] == "gmail.users.messages.list"
            assert rows[-1]["attempt"] == (len(observed) + 1 if failure is not None else 1)
            assert path.stat().st_mode & 0o777 == 0o600
            observed.append(rows[-1])
            if failure is not None:
                raise failure
        return original(uri, method=method, **kwargs)

    monkeypatch.setattr(server, "request", request)
    # Suppress retry backoff only; preserve the real client's retry behavior.
    monkeypatch.setattr("googleapiclient.http.time.sleep", lambda seconds: None)
    assert (
        cli.main(
            ["sender-sync", "--diagnostics", "--label", "Example/Delivery", "--contact", "c123"]
        )
        == code
    )
    path, rows = events()
    assert rows[0]["event"] == "command_start" and rows[0]["pid"] > 0
    assert rows[-1]["event"] == "command_exit" and rows[-1]["exit_code"] == code
    assert observed
    if isinstance(failure, TimeoutError):
        errors = [r for r in rows if r["event"] == "attempt_error"]
        assert len(errors) == 4
        assert all(r["exceptions"][0]["type"] == "TimeoutError" for r in errors)
        assert errors[-1]["exceptions"][0]["message"] == "timed out"
        assert errors[-1]["exceptions"][0]["frames"]
        final = [r for r in rows if r["event"] == "request_error"][-1]
        assert final["attempts"] == 4 and final["retries"] == 3
    assert all(r["elapsed_seconds"] >= 0 for r in rows)
    output = capsys.readouterr().err
    assert str(path) in output and f"Run finished (exit code {code})" in output
    assert error_logs.TRACE.get() is None
    text = path.read_text()
    assert "Example/Delivery" not in text and "people/c123" not in text


def test_diagnostic_storage_failure_preserves_command(api, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    blocked = tmp_path / "blocked"
    blocked.write_text("file")
    monkeypatch.setenv("CONTACTS_CLI_ERROR_LOG_DIR", str(blocked))
    assert (
        cli.main(
            ["sender-sync", "--diagnostics", "--label", "Example/Delivery", "--contact", "c123"]
        )
        == 0
    )
    assert "Run diagnostics could not be saved" in capsys.readouterr().err


def test_retention_preserves_other_log_types(api, monkeypatch):
    import os

    folder = error_logs.log_directory()
    folder.mkdir(parents=True)
    old = []
    for number in range(22):
        path = folder / f"run-old-{number:02}.jsonl"
        path.write_text("{}\n")
        os.utime(path, (number + 1, number + 1))
        old.append(path)
    unrelated = folder / "error-old.json"
    unrelated.write_text("keep")
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert (
        cli.main(
            ["sender-sync", "--diagnostics", "--label", "Example/Delivery", "--contact", "c123"]
        )
        == 0
    )
    assert len(list(folder.glob("run-*.jsonl"))) == 20
    assert all(not p.exists() for p in old[:3])
    assert all(p.exists() for p in old[3:])
    assert unrelated.read_text() == "keep"


def test_exception_chain_has_frames_without_secrets():
    try:
        try:
            raise TimeoutError("request https://example.com/?access_token=SECRET timed out")
        except TimeoutError as cause:
            raise OSError("Authorization: Bearer SECRET") from cause
    except OSError as error:
        details = error_logs.exception_details(error)
    assert [item["type"] for item in details] == ["OSError", "TimeoutError"]
    assert all(item["frames"] for item in details)
    assert "SECRET" not in json.dumps(details)
    assert "https://" not in json.dumps(details)


def test_http_exception_does_not_duplicate_response_body():
    import httplib2
    from googleapiclient.errors import HttpError

    error = HttpError(httplib2.Response({"status": 403}), b'{"error":{"message":"PRIVATE"}}')
    details = error_logs.exception_details(error)
    assert "PRIVATE" not in json.dumps(details)
    assert "403" in details[0]["message"]


def test_default_run_has_no_trace(api, monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(["sender-sync", "--label", "Example/Delivery", "--contact", "c123"]) == 0
    assert not list(error_logs.log_directory().glob("run-*.jsonl"))
    output = capsys.readouterr().err
    assert "diagnostics" not in output.lower()
    assert "Run finished" not in output
