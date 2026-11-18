"""Offline process/loopback regression checks for the production persistent reader."""

import base64
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from contacts_cli.persistent_reader import PersistentReader
from contacts_cli.read_worker import ReadSession

WORKER = [sys.executable, str(Path(__file__).parent / "fixtures/persistent_reader_worker.py")]


def body(reply):
    return json.loads(base64.b64decode(reply["content"]))


@pytest.fixture
def reader():
    with PersistentReader(WORKER) as client:
        yield client
    assert client.process is None and client.closed


def assert_reaped(process):
    assert process.poll() is not None
    assert all(pipe.closed for pipe in (process.stdin, process.stdout, process.stderr))


def test_fixture_protocol_and_http_independently():
    packets = [{"id": i, "payload": {"mode": "success", "timeout": 2}} for i in (1, 2)]
    result = subprocess.run(
        WORKER,
        input="".join(json.dumps(p) + "\n" for p in packets),
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2]
    assert [body(r["result"])["connections"] for r in replies] == [1, 1]
    assert body(replies[0]["result"])["authorization"] == "Bearer synthetic"


def test_reuse_credentials_and_close(reader):
    first = body(reader.request({"token": "first"}))
    process = reader.process
    second = body(reader.request({"token": "second"}))
    assert first["pid"] == second["pid"] == process.pid
    assert first["connections"] == second["connections"] == 1
    assert second["authorization"] == "Bearer second"
    reader.close()
    reader.close()
    assert_reaped(process)
    with pytest.raises(RuntimeError, match="closed"):
        reader.request({})


@pytest.mark.parametrize("mode", ["stall", "stubborn", "dns", "slow-body", "partial"])
def test_deadline_and_restart(reader, mode, tmp_path):
    reader.request({})  # Warm worker: test blocking operation, not just startup.
    process = reader.process
    marker = tmp_path / "entered"
    start = time.monotonic()
    with pytest.raises((TimeoutError, RuntimeError)):
        reader.request({"mode": mode, "marker": str(marker)}, seconds=0.4)
    assert 0.3 <= time.monotonic() - start < 1.5
    assert marker.read_text() == (mode + "-entered" if mode in {"dns", "slow-body"} else mode)
    assert_reaped(process)
    assert body(reader.request({}))["pid"] != process.pid


@pytest.mark.parametrize("mode", ["crash", "malformed", "wrong-id"])
def test_bad_worker_invalidated(reader, mode):
    reader.request({})
    process = reader.process
    with pytest.raises((RuntimeError, ValueError)):
        reader.request({"mode": mode})
    assert_reaped(process)
    assert body(reader.request({}))["connections"] == 1


def test_new_budget_for_each_read_and_drain_stderr(reader):
    reader.request({})
    for _ in range(4):
        assert body(reader.request({"mode": "delay"}, seconds=0.4))["connections"] == 1
    assert body(reader.request({"mode": "stderr"}))["connections"] == 1


def test_blocked_input_deadline():
    with PersistentReader(WORKER + ["--no-input"]) as client:
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            client.request({"padding": "x" * 1000000}, seconds=0.3)
        assert time.monotonic() - start < 1.5
        assert client.process is None


def test_interrupt_cleans_worker(reader):
    reader.request({})
    process = reader.process
    old = signal.signal(signal.SIGALRM, lambda *args: os.kill(os.getpid(), signal.SIGINT))
    try:
        signal.setitimer(signal.ITIMER_REAL, 0.2)
        with pytest.raises(KeyboardInterrupt):
            reader.request({"mode": "stall"})
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)
    assert_reaped(process)
    assert body(reader.request({}))["pid"] != process.pid


def test_write_guard_precedes_transport():
    def forbidden(**kwargs):
        pytest.fail("write reached transport")

    with pytest.raises(ValueError, match="Only reads"):
        ReadSession(forbidden).perform({"action": "read", "method": "PATCH", "headers": {}})
