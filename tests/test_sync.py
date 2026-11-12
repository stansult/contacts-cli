from copy import deepcopy
from unittest.mock import Mock

import httplib2
import pytest
from googleapiclient.errors import HttpError

from contacts_cli import cli
from contacts_cli.api import execute
from contacts_cli.core import make_plan
from contacts_cli.errors import SyncError, WriteUnverified

ARGS = ["--label", "Example/Delivery", "--contact", "people/c123"]


def test_preview_reads_all_pages_and_writes_nothing(api, server, monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect", lambda _: api)
    original = deepcopy(server.person)
    assert cli.main(ARGS) == 0
    out = capsys.readouterr().out
    assert "Scanned messages: 5" in out
    assert "Unique senders: 4" in out
    assert "Proposed additions: 3" in out
    assert "+ new@example.com" in out
    assert "+ spam@example.com" in out
    assert "+ trash@example.com" in out
    assert "unrelated@example.com" not in out
    assert server.writes == 0
    assert all(method == "GET" for method, *_ in server.calls)
    assert server.person == original
    assert len([call for call in server.calls if call[1].endswith("/messages")]) == 3


def test_apply_preserves_contact_and_rerun_is_noop(api, server, monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect", lambda _: api)
    original = deepcopy(server.person)
    assert cli.main(ARGS + ["--apply"]) == 0
    assert server.writes == 1
    assert server.batch_reads == 3  # original, pre-write, independent verification
    assert server.person["emailAddresses"][:2] == original["emailAddresses"]
    for field in ["phoneNumbers", "biographies", "names", "userDefined", "memberships"]:
        assert server.person[field] == original[field]
    patch = next(call for call in server.calls if call[0] == "PATCH")
    assert patch[2]["updatePersonFields"] == ["emailAddresses"]
    assert patch[3]["metadata"]["sources"][0]["etag"] == "source-v1"
    assert set(patch[3]) == {"resourceName", "metadata", "emailAddresses"}
    assert cli.main(ARGS + ["--apply"]) == 0
    assert server.writes == 1
    assert "No additions needed" in capsys.readouterr().out


def test_more_than_100_contact_emails_are_compared(api, server):
    server.person["emailAddresses"] = [{"value": f"old{i}@example.com"} for i in range(149)]
    server.person["emailAddresses"].append({"value": "new@example.com", "type": "Custom"})
    plan = make_plan(api.get_contact("people/c123"), api.scan("Example/Delivery"))
    assert "new@example.com" not in plan.additions
    assert api.apply(plan)
    assert len(server.person["emailAddresses"]) == 153
    assert server.person["emailAddresses"][149]["type"] == "Custom"


def test_invalid_header_prevents_any_apply(api, server, monkeypatch, capsys):
    server.mailbox["messages"][0]["payload"]["headers"] = [{"name": "From", "value": "broken"}]
    monkeypatch.setattr(cli, "connect", lambda _: api)
    assert cli.main(ARGS + ["--apply"]) == 1
    assert "Message m1" in capsys.readouterr().err
    assert server.writes == 0


@pytest.mark.parametrize(
    "fault", ["missing_message", "repeat_token", "batch_status", "concurrent_edit"]
)
def test_incomplete_scan_or_contact_change_prevents_write(api, server, monkeypatch, fault):
    setattr(server, fault, {"missing_message": "m4", "batch_status": 7}.get(fault, True))
    monkeypatch.setattr(cli, "connect", lambda _: api)
    assert cli.main(ARGS + ["--apply"]) == 1
    assert server.writes == 0


def test_api_conflict_is_not_retried(api, server, monkeypatch):
    server.reject_write = True
    monkeypatch.setattr(cli, "connect", lambda _: api)
    assert cli.main(ARGS + ["--apply"]) == 1
    assert len([call for call in server.calls if call[0] == "PATCH"]) == 1
    assert server.writes == 0


@pytest.mark.parametrize("fault", ["lose_additions", "fail_verification"])
def test_submitted_but_unverified_is_distinct(api, server, monkeypatch, capsys, fault):
    setattr(server, fault, True)
    monkeypatch.setattr(cli, "connect", lambda _: api)
    assert cli.main(ARGS + ["--apply"]) == 3
    assert "Unverified update" in capsys.readouterr().err
    assert server.writes == 1


def test_empty_label_no_update(api, server, monkeypatch):
    server.mailbox["messages"] = []
    monkeypatch.setattr(cli, "connect", lambda _: api)
    assert cli.main(ARGS + ["--apply"]) == 0
    assert server.writes == 0


def test_unknown_label_no_update(api, server):
    with pytest.raises(SyncError, match="exactly one"):
        api.scan("example/delivery")
    assert server.writes == 0


def test_lost_label_is_detected(api, server, monkeypatch):
    request = server.request

    def changed(uri, *args, **kwargs):
        if "/messages/m2?" in uri:
            server.mailbox["messages"][1]["labelIds"] = []
        return request(uri, *args, **kwargs)

    monkeypatch.setattr(server, "request", changed)
    with pytest.raises(SyncError, match="lost its label"):
        api.scan("Example/Delivery")


def test_read_retries_but_write_outcome_unknown_without_retry():
    request = Mock()
    request.execute.side_effect = OSError("synthetic timeout")
    with pytest.raises(SyncError):
        execute(request)
    request.execute.assert_called_once_with(num_retries=3)
    request.reset_mock()
    with pytest.raises(WriteUnverified):
        execute(request, write=True)
    request.execute.assert_called_once_with(num_retries=0)


def test_server_error_write_outcome_unknown():
    request = Mock()
    request.execute.side_effect = HttpError(httplib2.Response({"status": "503"}), b"{}")
    with pytest.raises(WriteUnverified):
        execute(request, write=True)
    request.execute.assert_called_once_with(num_retries=0)


def test_bad_contact_does_not_connect(monkeypatch):
    connection = Mock()
    monkeypatch.setattr(cli, "connect", connection)
    assert cli.main(["--label", "Example", "--contact", "bad"]) == 1
    connection.assert_not_called()


def test_auth_and_sync_cannot_be_combined():
    with pytest.raises(SystemExit) as exc:
        cli.main(ARGS + ["--authorize", "--credentials", "/tmp/example.json"])
    assert exc.value.code == 2


def test_oversize_existing_contact_with_no_additions_is_noop(api, server, monkeypatch):
    server.person["biographies"][0]["value"] = "x" * (128 * 1024)
    server.mailbox["messages"] = []
    monkeypatch.setattr(cli, "connect", lambda _: api)
    assert cli.main(ARGS + ["--apply"]) == 0
    assert server.writes == 0


def test_malformed_update_response_is_unverified():
    request = Mock()
    request.execute.side_effect = ValueError("synthetic invalid JSON response")
    with pytest.raises(WriteUnverified):
        execute(request, write=True)
