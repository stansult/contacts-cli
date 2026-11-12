"""Offline checks for the documented aggregate-only metrics contract."""

import io
import json

import httplib2
import pytest
from googleapiclient.http import HttpRequest

from contacts_cli import cli, metrics
from contacts_cli.api import execute

ARGS = ["sender-sync", "--label", "Example/Delivery", "--contact", "people/c123"]


def records():
    return [json.loads(line) for line in metrics.default_path().read_text().splitlines()]


def test_preview_metrics_counts_and_privacy(api, server, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS) == 0
    row = records()[0]
    assert row["outcome"] == "preview" and row["scan_complete"]
    assert row["algorithm"] == "sender-exclusion-v1"
    assert row["counts"] == {
        "messages": 3,
        "senders": 3,
        "invalid_headers": 0,
        "existing_entries": 2,
        "additions": 3,
    }
    assert {key: value["calls"] for key, value in row["api"].items()} == {
        "contact_reads": 1,
        "labels": 1,
        "sending_addresses": 1,
        "message_list": 4,
        "headers": 3,
    }
    assert sum(item["attempts"] for item in row["api"].values()) == len(server.calls)
    assert all(item["retries"] == 0 and item["seconds"] >= 0 for item in row["api"].values())
    text = metrics.default_path().read_text()
    for private in ("Example/Delivery", "people/c123", "example.com", "https://", "source-v1"):
        assert private not in text
    assert metrics.default_path().stat().st_mode & 0o777 == 0o600


def test_applied_and_noop_are_separate(api, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--apply"]) == 0
    assert cli.main(ARGS) == 0
    first, second = records()
    assert first["outcome"] == "applied"
    assert first["api"]["contact_writes"]["attempts"] == 1
    assert second["outcome"] == "no_changes"
    assert "contact_writes" not in second["api"]


def test_interrupt_records_partial_scan(api, server, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    original = server.request
    reads = 0

    def interrupt(uri, *args, **kwargs):
        nonlocal reads
        if "/messages/" in uri:
            reads += 1
            if reads == 2:
                raise KeyboardInterrupt
        return original(uri, *args, **kwargs)

    monkeypatch.setattr(server, "request", interrupt)
    assert cli.main(ARGS) == 130
    row = records()[0]
    assert reads == 2
    assert row["outcome"] == "interrupted" and not row["scan_complete"]
    assert row["counts"]["messages"] == 1
    assert row["api"]["headers"]["attempts"] == 2
    assert server.writes == 0


@pytest.mark.parametrize("write,expected_attempts", [(False, 2), (True, 1)])
def test_retry_counter_preserves_retry_policy(write, expected_attempts):
    from contacts_cli.errors import WriteUnverified

    class Transport:
        calls = 0

        def request(self, *args, **kwargs):
            self.calls += 1
            status = 503 if self.calls == 1 else 200
            return httplib2.Response({"status": str(status)}), b"{}"

    transport = Transport()
    request = HttpRequest(transport, lambda resp, content: {}, "https://example.com")
    request._sleep = lambda seconds: None
    current = metrics.RunMetrics()
    token = metrics.ACTIVE.set(current)
    try:
        if write:
            with pytest.raises(WriteUnverified):
                execute(request, write=True)
        else:
            assert execute(request) == {}
    finally:
        metrics.ACTIVE.reset(token)
    assert transport.calls == expected_attempts
    assert current.record["api"]["other"]["attempts"] == expected_attempts
    assert current.record["api"]["other"]["retries"] == expected_attempts - 1


def test_storage_failure_does_not_change_result(api, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    blocked = tmp_path / "file"
    blocked.write_text("synthetic")
    monkeypatch.setenv("CONTACTS_CLI_METRICS_DIR", str(blocked))
    assert cli.main(ARGS) == 0
    assert "metrics could not be saved" in capsys.readouterr().err


def test_failed_run_and_summary(api, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS) == 0
    assert cli.main(["sender-sync", "--label", "private-label", "--contact", "bad-id"]) == 1
    rows = records()
    assert rows[1]["outcome"] == "failed" and rows[1]["api"] == {}
    assert "private-label" not in metrics.default_path().read_text()
    with metrics.default_path().open("a") as output:
        output.write('{"truncated":\n')
    stream = io.StringIO()
    metrics.summarize(metrics.default_path(), stream)
    summary = stream.getvalue()
    assert "preview | 1 |" in summary and "failed | 1 |" in summary
    assert "Skipped 1" in summary


def test_count_allowlist_and_timer(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(metrics.time, "monotonic", lambda: now[0])
    current = metrics.RunMetrics()
    token = metrics.ACTIVE.set(current)
    try:
        metrics.counts(messages=2, label="private", additions="private")
    finally:
        metrics.ACTIVE.reset(token)
    now[0] = 14.0
    current.finish(130)
    assert records()[0]["elapsed_seconds"] == 4.0
    assert records()[0]["counts"] == {"messages": 2}
