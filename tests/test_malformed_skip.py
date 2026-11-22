"""Malformed messages are skipped, with private evidence and bounded pagination."""

import json
from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.error_logs import log_directory

from .test_fixture_contract import fetch


def mailbox(server, values):
    template = deepcopy(server.mailbox["messages"][0])
    server.mailbox["messages"] = []
    for i, value in enumerate(values):
        message = deepcopy(template)
        message["id"] = f"bad-test-{i}"
        message["payload"]["headers"] = [] if value is None else [{"name": "From", "value": value}]
        server.mailbox["messages"].append(message)


def test_pagination_fixture_contract(server):
    mailbox(server, ["broken", "next@example.com"])
    path = "/gmail/v1/users/me/messages?maxResults=1&includeSpamTrash=true&labelIds=Label_1"
    _, first = fetch(server, path)
    assert first["messages"][0]["id"] == "bad-test-0"
    _, second = fetch(server, path + "&pageToken=" + first["nextPageToken"])
    assert second["messages"][0]["id"] == "bad-test-1"
    assert "nextPageToken" not in second


@pytest.mark.parametrize("search", [False, True])
def test_skip_then_continue_and_apply(server, api, monkeypatch, capsys, search):
    mailbox(server, ['"Example" <Example.com>', "one@example.com", None, "two@example.com"])
    if search:
        server.search_results["subject:example"] = {m["id"] for m in server.mailbox["messages"]}
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    source = ["--search", "subject:example"] if search else ["--label", "Example/Delivery"]
    assert cli.main(["sender-sync", "--contact", "c123", *source, "--apply"]) == 0
    output = capsys.readouterr()
    assert "Skipped message bad-test-0" in output.err
    assert "2 skipped messages" in output.err
    assert "Saved and verified 2 additions" in output.out
    reads = [c for c in server.calls if "/messages/" in c[1]]
    assert len(reads) == 4
    records = [json.loads(p.read_text()) for p in log_directory().glob("malformed-*.json")]
    assert len(records) == 2
    assert records[0]["reason"]
    assert {r["message"]["id"] for r in records} == {"bad-test-0", "bad-test-2"}
    assert server.writes == 1


def test_all_bad_finishes_without_write(server, api, monkeypatch, capsys):
    mailbox(server, ["broken", None, "also broken"])
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert (
        cli.main(["sender-sync", "--contact", "c123", "--label", "Example/Delivery", "--apply"])
        == 0
    )
    assert server.writes == 0
    assert "3 skipped messages" in capsys.readouterr().err


def test_log_available_metadata_only(tmp_path):
    from contacts_cli.error_logs import save_malformed_message
    from contacts_cli.errors import SyncError

    message = {
        "id": "synthetic",
        "threadId": "thread",
        "labelIds": ["Label_1"],
        "snippet": "PRIVATE BODY",
        "payload": {
            "headers": [{"name": "From", "value": "broken"}],
            "body": {"data": "PRIVATE BODY"},
        },
    }
    path = save_malformed_message(message, SyncError("invalid header"))
    record = json.loads(path.read_text())
    assert record["message"]["headers"] == message["payload"]["headers"]
    assert record["message"]["threadId"] == "thread"
    assert "PRIVATE BODY" not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600


def test_logging_failure_does_not_block_skip(server, api, monkeypatch, tmp_path):
    mailbox(server, ["broken", "valid@example.com"])
    blocked = tmp_path / "file"
    blocked.write_text("not a directory")
    monkeypatch.setenv("CONTACTS_CLI_ERROR_LOG_DIR", str(blocked))
    scan = api.scan("Example/Delivery")
    assert scan.senders == ("valid@example.com",)
    assert "could not be saved" in scan.problems[0]


def test_repeated_page_token_stops_without_write(server, api, monkeypatch):
    mailbox(server, ["broken", "also broken", None])
    server.repeat_token = True
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert (
        cli.main(["sender-sync", "--contact", "c123", "--label", "Example/Delivery", "--apply"])
        == 1
    )
    assert server.writes == 0
    assert len([c for c in server.calls if c[1].endswith("/messages")]) == 2


def test_error_after_skip_preserves_log_and_blocks_write(server, api, monkeypatch):
    mailbox(server, ["broken", "one@example.com", "two@example.com"])
    server.missing_message = "bad-test-2"
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert (
        cli.main(["sender-sync", "--contact", "c123", "--label", "Example/Delivery", "--apply"])
        == 1
    )
    assert server.writes == 0
    assert len(list(log_directory().glob("malformed-*.json"))) == 1


def test_final_bad_message_preview_only(server, api, monkeypatch):
    mailbox(server, ["one@example.com", '"Example" <Example.com>'])
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(["sender-sync", "--contact", "c123", "--label", "Example/Delivery"]) == 0
    assert server.writes == 0
    record = json.loads(next(log_directory().glob("malformed-*.json")).read_text())
    assert "no domain" in record["cause"]


def test_repeated_skipped_id_with_new_token_stops(server, api, monkeypatch):
    import httplib2

    mailbox(server, ["broken", "valid@example.com"])
    original = server.request
    count = 0

    def repeated(uri, *args, **kwargs):
        nonlocal count
        if "/messages?" in uri:
            count += 1
            return httplib2.Response({"status": "200"}), json.dumps(
                {"messages": [{"id": "bad-test-0"}], "nextPageToken": str(count)}
            ).encode()
        return original(uri, *args, **kwargs)

    monkeypatch.setattr(server, "request", repeated)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert (
        cli.main(["sender-sync", "--contact", "c123", "--label", "Example/Delivery", "--apply"])
        == 1
    )
    assert count == 2
    assert server.writes == 0
