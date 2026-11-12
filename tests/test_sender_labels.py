"""From display names become custom email labels; final progress is never throttled."""

import io
from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.progress import ScanProgress

from .test_timestamps import undecorated

ARGS = ["sender-sync", "--label", "Example/Delivery", "--contact", "people/c123"]


def test_display_name_preview_and_saved_label(api, server, monkeypatch, capsys):
    before = deepcopy(server.person)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--apply"]) == 0
    assert "  + new@example.com — New sender" in capsys.readouterr().out
    added = {entry["value"]: entry for entry in server.person["emailAddresses"][2:]}
    assert added["new@example.com"] == {"value": "new@example.com", "type": "New sender"}
    assert added["spam@example.com"] == {"value": "spam@example.com"}
    assert server.person["emailAddresses"][:2] == before["emailAddresses"]


@pytest.mark.parametrize("terminal", [True, False])
def test_completion_forces_last_counter_before_finished(terminal):
    class Stream(io.StringIO):
        def isatty(self):
            return terminal

    stream = Stream()
    with ScanProgress(stream, lambda: 0.0) as progress:
        progress("Searching senders", 8, 8)
        progress("Searching senders", 9, 9)
        assert "9 inspected" not in stream.getvalue()
        progress("Search finished", 9, 9)
    assert stream.getvalue().endswith(
        "Searching senders: 9 inspected, 9 new senders\nSearch finished.\n"
    )


def test_section_order_on_combined_output(api, monkeypatch):
    import sys

    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", stream)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS) == 0
    output = undecorated(stream.getvalue())
    assert output.startswith(
        "Reading contact…\nContact: 'name: Example Delivery' (people/c123)\n\n"
        "Reading sending addresses…\nFinding label…\n"
        "Label: 'Example/Delivery' (including Spam and Trash)\n\n"
        "Searching senders:"
    )
    assert (
        "Searching senders: 3 inspected, 3 new senders\nSearch finished.\n"
        "Existing email entries: 2\n\n"
        "Proposed additions: 3\n  + new@example.com — New sender\n"
    ) in output


@pytest.mark.parametrize(
    "header,label",
    [
        ('"Delivery, Example" <new@example.com>', "Delivery, Example"),
        ("=?UTF-8?B?Sm9zw6k=?= <new@example.com>", "José"),
        ("New\r\n Sender <new@example.com>", "New Sender"),
        ("new@example.com (Comment)", ""),
        ("new@example.com", ""),
    ],
)
def test_parsed_display_names(header, label):
    from contacts_cli.core import parse_from_details

    assert parse_from_details([header]) == (("new@example.com", label),)


def test_encoded_control_in_label_is_rejected():
    from contacts_cli.core import parse_from_details
    from contacts_cli.errors import SyncError

    with pytest.raises(SyncError):
        parse_from_details(["=?UTF-8?Q?Bad=1B=5B31m?= <new@example.com>"])


@pytest.mark.parametrize("drop_at", ["response", "readback"])
def test_missing_new_label_is_unverified(api, server, monkeypatch, capsys, drop_at):
    import json

    original = server.request

    def dropping(uri, method="GET", **kwargs):
        response, content = original(uri, method=method, **kwargs)
        if server.writes and (
            drop_at == "response"
            and method == "PATCH"
            or drop_at == "readback"
            and "people:batchGet" in uri
        ):
            body = json.loads(content)
            person = body if method == "PATCH" else body["responses"][0]["person"]
            for entry in person["emailAddresses"]:
                if entry["value"] == "new@example.com":
                    entry.pop("type", None)
            content = json.dumps(body).encode()
        return response, content

    monkeypatch.setattr(server, "request", dropping)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--apply"]) == 3
    assert "email label was not preserved" in capsys.readouterr().err
    assert server.writes == 1


def test_fixture_persists_custom_email_label_independently(server):
    from tests.test_fixture_contract import fetch

    body = {
        "metadata": {"sources": [{"etag": "source-v1"}]},
        "emailAddresses": [{"value": "new@example.com", "type": "Notifications"}],
    }
    status, result = fetch(
        server, "/v1/people/c123:updateContact?updatePersonFields=emailAddresses", "PATCH", body
    )
    assert status == 200 and result["emailAddresses"] == body["emailAddresses"]
    status, result = fetch(
        server,
        "/v1/people:batchGet?resourceNames=people/c123&personFields=emailAddresses&sources=READ_SOURCE_TYPE_CONTACT",
    )
    assert status == 200
    assert result["responses"][0]["person"]["emailAddresses"] == body["emailAddresses"]
