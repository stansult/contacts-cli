"""A read deadline includes worker startup, DNS, response waits, and retry backoff."""

import json
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import httplib2
import pytest
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.http import HttpRequest

from contacts_cli import deadline
from contacts_cli.api import execute
from contacts_cli.errors import SyncError


@pytest.fixture(autouse=True)
def close_transports(monkeypatch):
    transports = []
    original = deadline.DeadlineHTTP.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        transports.append(self)

    monkeypatch.setattr(deadline.DeadlineHTTP, "__init__", init)
    yield
    for transport in transports:
        transport.close()


WORKER = [sys.executable, str(Path(__file__).parent / "fixtures" / "deadline_worker.py")]


def credentials():
    return Credentials(
        token="synthetic",
        refresh_token="synthetic",
        token_uri="https://example.invalid/token",
        client_id="synthetic",
        client_secret="synthetic",
    )


def request(mode):
    transport = deadline.DeadlineHTTP(
        AuthorizedHttp(credentials()), worker_command=WORKER + ["--persistent"]
    )
    return HttpRequest(
        transport,
        lambda resp, content: json.loads(content),
        f"https://example.invalid/{mode}",
        methodId="gmail.users.labels.list",
    )


@pytest.mark.parametrize("mode", ["dns-stall", "response-stall", "backoff"])
def test_read_stalls_are_bounded(mode, monkeypatch):
    monkeypatch.setattr(deadline, "READ_TIMEOUT_SECONDS", 0.8)
    req = request(mode)
    req._rand = lambda: 10
    started = time.monotonic()
    with pytest.raises(SyncError, match="timed out"):
        execute(req)
    assert time.monotonic() - started < 1.5


def test_success_and_credentials_roundtrip():
    req = request("success")
    assert execute(req) == {"ok": True}
    assert req.http.credentials.token == "synthetic-refreshed"


def test_dns_failure_is_not_retried(monkeypatch):
    req = request("dns-error")
    req._sleep = Mock(side_effect=AssertionError("DNS must not retry"))
    with pytest.raises(SyncError, match="resolve"):
        execute(req)
    req._sleep.assert_not_called()


def test_write_stays_in_parent():
    parent = Mock()
    parent.request.return_value = (httplib2.Response({"status": "200"}), b"{}")
    transport = deadline.DeadlineHTTP(parent, worker_command=["must-not-run"])
    req = HttpRequest(transport, lambda r, c: {}, "https://example.invalid", method="PATCH")
    assert execute(req, write=True) == {}
    parent.request.assert_called_once()


@pytest.fixture
def workers(monkeypatch):
    original = deadline.subprocess.Popen
    children = []

    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(deadline.subprocess, "Popen", spawn)
    yield children
    for child in children:
        assert child.poll() is not None
        assert all(pipe.closed for pipe in (child.stdin, child.stdout, child.stderr))


@pytest.mark.parametrize("mode", ["dns-stall", "response-stall", "stubborn", "slow-body"])
def test_real_worker_cleanup_and_fixture_reaches_stall(mode, monkeypatch, tmp_path, workers):
    monkeypatch.setattr(deadline, "READ_TIMEOUT_SECONDS", 3)
    marker = tmp_path / "entered"
    monkeypatch.setenv("DEADLINE_TEST_MARKER", str(marker))
    with pytest.raises(SyncError, match="timed out"):
        execute(request(mode))
    assert int(marker.read_text()) == workers[0].pid
    assert len(workers) == 1


def test_interrupt_reaps_worker(monkeypatch, workers):
    def interrupted(self, *args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(deadline.PersistentReader, "_exchange", interrupted)
    with pytest.raises(KeyboardInterrupt):
        execute(request("response-stall"))
    assert len(workers) == 1


def test_http_error_body_preserved(monkeypatch, tmp_path, capsys):
    from contacts_cli import error_logs

    with pytest.raises(SyncError, match="HTTP 403"):
        execute(request("http-error"))
    files = list(error_logs.log_directory().glob("error-*.json"))
    assert (
        json.loads(files[0].read_text())["response_body"]
        == '{"error":{"message":"synthetic denial"}}'
    )


def test_long_get_remains_read():
    req = request("long-query")
    req.uri += "?q=" + "x" * 3000
    assert execute(req) == {"ok": True}


def test_refresh_deadline_and_roundtrip(monkeypatch, workers):
    original = deadline.worker_call
    monkeypatch.setattr(deadline, "worker_call", lambda payload: original(payload, WORKER))
    assert deadline.refresh_credentials(credentials()).token == "synthetic-refreshed"
    creds = credentials()
    creds._refresh_token = "stall-refresh"
    monkeypatch.setattr(deadline, "READ_TIMEOUT_SECONDS", 0.8)
    with pytest.raises(SyncError, match="Refreshing authorization timed out"):
        deadline.refresh_credentials(creds)


def test_read_cannot_submit_mutation():
    req = request("success")
    req.method = "PATCH"
    with pytest.raises(SyncError, match="attempted a write"):
        execute(req)


@pytest.mark.parametrize(
    "mode,status,kind",
    [("success", "200", None), ("http-error", "403", None), ("dns-error", None, "dns")],
)
def test_worker_fixture_contract(mode, status, kind):
    # Independently verify the transport fixture through the worker's wire protocol.
    payload = {
        "action": "read",
        "credentials": json.loads(credentials().to_json()),
        "uri": f"https://example.invalid/{mode}",
        "method": "GET",
        "body": None,
        "headers": {},
        "redirections": 5,
        "timeout": 1,
    }
    result = deadline.subprocess.run(
        WORKER, input=json.dumps(payload), text=True, capture_output=True, timeout=3, check=True
    )
    assert not result.stderr
    data = json.loads(result.stdout)
    if kind:
        assert data["error"]["kind"] == kind
        assert data["error"]["details"][0]["type"] == "gaierror"
    else:
        assert data["headers"]["status"] == status
        assert data["credentials"]["token"] == "synthetic-refreshed"


def test_timeout_diagnostics_and_metrics(monkeypatch):
    from contacts_cli import error_logs
    from contacts_cli.error_logs import TRACE, RunDiagnostics
    from contacts_cli.metrics import ACTIVE, RunMetrics

    metrics = RunMetrics()
    trace = RunDiagnostics("sender-sync", "synthetic")
    metric_token = ACTIVE.set(metrics)
    trace_token = TRACE.set(trace)
    monkeypatch.setattr(deadline, "READ_TIMEOUT_SECONDS", 0.8)
    try:
        with pytest.raises(SyncError, match="Reading Gmail labels timed out"):
            execute(request("response-stall"))
    finally:
        ACTIVE.reset(metric_token)
        TRACE.reset(trace_token)
        trace.finish(1)
    counters = metrics.record["api"]["labels"]
    assert counters["attempts"] == 1 and counters["retries"] == 0
    assert counters["seconds"] >= 0.8
    log = next(error_logs.log_directory().glob("run-*.jsonl")).read_text()
    assert "request_error" in log and "ReadTimeout" in log
    assert "read_deadline" in log
    assert "synthetic-refreshed" not in log
    assert "client_secret" not in log


def test_repeated_success_reuses_refreshed_token():
    req = request("success")
    assert execute(req) == {"ok": True}
    # The fixture checks the Authorization header, including on the next read.
    assert execute(req) == {"ok": True}


def test_retries_reuse_worker_and_fresh_operation_budget(monkeypatch):
    req = request("retry-once")
    req._sleep = lambda seconds: None
    assert execute(req) == {"ok": True}
    child = req.http.reader.process
    assert req.http.reader.sequence == 2
    assert child.poll() is None
    assert execute(req) == {"ok": True}
    assert req.http.reader.process is child
    assert req.http.reader.sequence == 3
    req.http.close()
    assert child.poll() is not None
    assert all(pipe.closed for pipe in (child.stdin, child.stdout, child.stderr))


def test_connection_retry_replaces_failed_worker(monkeypatch, tmp_path, workers):
    monkeypatch.setenv("CONNECTION_ATTEMPT_FILE", str(tmp_path / "attempt"))
    req = request("connection-once")
    req._sleep = lambda seconds: None
    assert execute(req) == {"ok": True}
    assert len(workers) == 2
    assert workers[0].poll() is not None
    assert workers[1].poll() is None
    req.http.close()


def test_backoff_timeout_discards_idle_worker(monkeypatch, workers):
    monkeypatch.setattr(deadline, "READ_TIMEOUT_SECONDS", 0.8)
    req = request("backoff")
    req._rand = lambda: 10
    with pytest.raises(SyncError, match="timed out"):
        execute(req)
    assert req.http.reader.process is None
    assert len(workers) == 1


def test_read_refresh_is_used_by_parent_write():
    req = request("success")
    assert execute(req) == {"ok": True}
    parent = req.http.http
    parent.http.request = Mock(return_value=(httplib2.Response({"status": "200"}), b"{}"))
    write = HttpRequest(req.http, lambda r, c: {}, "https://example.invalid", method="PATCH")
    execute(write, write=True)
    assert (
        parent.http.request.call_args.kwargs["headers"]["authorization"]
        == "Bearer synthetic-refreshed"
    )
    assert req.http.reader.sequence == 1


def test_dns_details_preserved_in_diagnostics():
    from contacts_cli.error_logs import TRACE, RunDiagnostics

    trace = RunDiagnostics("sender-sync", "synthetic")
    token = TRACE.set(trace)
    try:
        with pytest.raises(SyncError, match="resolve"):
            execute(request("dns-error"))
    finally:
        TRACE.reset(token)
        trace.finish(1)
    from contacts_cli import error_logs

    text = next(error_logs.log_directory().glob("run-*.jsonl")).read_text()
    assert "read_worker_error" in text and "gaierror" in text
    assert "synthetic-refreshed" not in text


@pytest.mark.parametrize(
    "failure", [None, SyncError("synthetic"), KeyboardInterrupt(), RuntimeError("synthetic")]
)
def test_cli_closes_worker_on_every_exit_and_repeated_invocation(monkeypatch, failure):
    from types import SimpleNamespace

    from contacts_cli import cli
    from contacts_cli.api import GoogleAPI

    children = []
    transports = []

    def connect(*args):
        req = request("success")
        transports.append(req.http)
        return GoogleAPI(SimpleNamespace(_http=req.http), None)

    def run(args, api, heading):
        req = HttpRequest(api.gmail._http, lambda r, c: {}, "https://example.invalid/success")
        execute(req)
        children.append(req.http.reader.process)
        if failure is not None:
            raise failure
        return 0

    monkeypatch.setattr(cli, "connect_with_authorization", connect)
    monkeypatch.setattr(cli, "run_field_lists", run)
    for _ in range(2):
        if isinstance(failure, RuntimeError):
            with pytest.raises(RuntimeError, match="synthetic"):
                cli.main(["list-email", "--contact", "c123"])
        else:
            code = cli.main(["list-email", "--contact", "c123"])
            assert code == (130 if isinstance(failure, KeyboardInterrupt) else 1 if failure else 0)
        assert children[-1].poll() is not None
        assert all(p.closed for p in (children[-1].stdin, children[-1].stdout, children[-1].stderr))
        assert transports[-1].closed
    assert children[0].pid != children[1].pid


def test_retry_fixture_contract():
    payload = {
        "action": "read",
        "credentials": json.loads(credentials().to_json()),
        "uri": "https://example.invalid/retry-once",
        "method": "GET",
        "body": None,
        "headers": {},
        "redirections": 5,
        "timeout": 1,
    }
    packets = [{"id": number, "payload": payload} for number in (1, 2)]
    result = deadline.subprocess.run(
        WORKER + ["--persistent"],
        input="".join(json.dumps(packet) + "\n" for packet in packets),
        text=True,
        capture_output=True,
        timeout=3,
        check=True,
    )
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert [reply["id"] for reply in replies] == [1, 2]
    assert [reply["result"]["headers"]["status"] for reply in replies] == ["503", "200"]
    assert not result.stderr
