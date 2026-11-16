"""Failure-only email snapshots and bounded retention are local diagnostics."""

import json
import os

import pytest

from contacts_cli import cli, error_logs
from contacts_cli.core import Scan, make_plan, update_body
from contacts_cli.errors import SyncError, WriteUnverified


@pytest.mark.parametrize("stage", ["update response", "independent readback"])
def test_records_exact_snapshots_and_stage(api, server, stage, capsys):
    plan = make_plan(server.person, Scan(1, ("new@example.com",)))
    body = update_body(plan)
    calls = 0

    def verify(saved):
        nonlocal calls
        calls += 1
        if calls == (1 if stage == "update response" else 2):
            raise SyncError("Synthetic mismatch")

    with pytest.raises(WriteUnverified):
        api.apply_email_change(plan.person, body, verify)
    files = list(error_logs.log_directory().glob("verification-*.json"))
    assert len(files) == 1
    record = json.loads(files[0].read_text())
    assert record["stage"] == stage
    assert record["before"] == plan.person["emailAddresses"]
    assert record["expected"] == body["emailAddresses"]
    assert record["saved"] == server.person["emailAddresses"]
    assert record["mismatch"] == "Synthetic mismatch"
    assert "phoneNumbers" not in record
    assert files[0].stat().st_mode & 0o777 == 0o600
    assert str(files[0]) in capsys.readouterr().err


def test_cli_failure_logged_success_not_logged(api, server, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    args = ["sender-sync", "--label", "Example/Delivery", "--contact", "c123", "--apply"]
    server.lose_additions = True
    assert cli.main(args) == 3
    path = next(error_logs.log_directory().glob("verification-*.json"))
    assert json.loads(path.read_text())["command"] == "sender-sync"
    server.lose_additions = False
    assert cli.main(args) == 0
    assert list(error_logs.log_directory().glob("verification-*.json")) == [path]


def test_retains_twenty_verification_logs_only(api, server):
    folder = error_logs.log_directory()
    folder.mkdir(parents=True, exist_ok=True)
    old = []
    for i in range(22):
        path = folder / f"verification-old-{i:02}.json"
        path.write_text("{}")
        os.utime(path, (i + 1, i + 1))
        old.append(path)
    http = folder / "error-old.json"
    http.write_text("keep HTTP")
    other = folder / "notes.json"
    other.write_text("keep unrelated")
    plan = make_plan(server.person, Scan(1, ("new@example.com",)))

    def fail(saved):
        raise SyncError("Synthetic mismatch")

    with pytest.raises(WriteUnverified):
        api.apply_email_change(plan.person, update_body(plan), fail)
    remaining = list(folder.glob("verification-*.json"))
    assert len(remaining) == 20
    assert all(not path.exists() for path in old[:3])
    assert all(path.exists() for path in old[3:])
    assert http.read_text() == "keep HTTP"
    assert other.read_text() == "keep unrelated"


def test_storage_failure_preserves_unverified_error(api, server, monkeypatch, tmp_path, capsys):
    path = tmp_path / "file"
    path.write_text("not directory")
    monkeypatch.setenv("CONTACTS_CLI_ERROR_LOG_DIR", str(path))
    plan = make_plan(server.person, Scan(1, ("new@example.com",)))

    def fail(saved):
        raise SyncError("Original mismatch")

    with pytest.raises(WriteUnverified, match="Original mismatch"):
        api.apply_email_change(plan.person, update_body(plan), fail)
    assert "Verification details could not be saved" in capsys.readouterr().err
    assert server.writes == 1


def test_failed_readback_does_not_log_stale_response(api, server):
    plan = make_plan(server.person, Scan(1, ("new@example.com",)))
    server.fail_verification = True
    with pytest.raises(WriteUnverified):
        api.apply(plan)
    record = json.loads(next(error_logs.log_directory().glob("verification-*.json")).read_text())
    assert record["stage"] == "independent readback"
    assert record["saved"] is None
