"""Exclude configured Gmail sending identities without changing authorization."""

import json

import pytest

from contacts_cli import cli

ARGS = ["sender-sync", "--label", "Example/Delivery", "--contact", "people/c123"]


def test_fixture_send_as_contract(server):
    from tests.test_fixture_contract import fetch

    status, body = fetch(server, "/gmail/v1/users/me/settings/sendAs")
    assert status == 200
    assert body == {
        "sendAs": [
            {"sendAsEmail": "me@example.com", "isPrimary": True},
            {"sendAsEmail": "alias@example.com", "isPrimary": False},
        ]
    }
    server.send_as_status = 403
    assert fetch(server, "/gmail/v1/users/me/settings/sendAs")[0] == 403


def test_primary_and_alias_excluded_from_search_and_write(api, server, monkeypatch):
    server.mailbox["messages"][1]["payload"]["headers"][0]["value"] = "Me <ME@example.com>"
    server.mailbox["messages"][2]["payload"]["headers"][0]["value"] = "Alias <alias@example.com>"
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--apply"]) == 0
    values = {entry["value"].lower() for entry in server.person["emailAddresses"]}
    assert "me@example.com" not in values and "alias@example.com" not in values
    assert {"spam@example.com", "trash@example.com"} <= values
    alias_calls = [call for call in server.calls if call[1].endswith("/settings/sendAs")]
    assert len(alias_calls) == 1
    assert alias_calls[0][2]["fields"] == ["sendAs(sendAsEmail,isPrimary)"]
    for call in server.calls:
        if call[1].endswith("/messages"):
            assert '-from:"me@example.com"' in call[2]["q"][0]
            assert '-from:"alias@example.com"' in call[2]["q"][0]


def test_redundant_label_omitted_from_preview_and_write(api, server, monkeypatch, capsys):
    server.mailbox["messages"][1]["payload"]["headers"][0]["value"] = (
        '" NEW@example.com " <new@example.com>'
    )
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--apply"]) == 0
    output = capsys.readouterr().out
    assert "  1. new@example.com\n" in output
    assert "Inspected messages:" not in output and "New unique senders:" not in output
    assert next(
        item for item in server.person["emailAddresses"] if item["value"] == "new@example.com"
    ) == {"value": "new@example.com"}


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"sendAs": []},
        {"sendAs": None},
        {"sendAs": [None]},
        {"sendAs": [{"sendAsEmail": "me@example.com"}]},
        {"sendAs": [{"isPrimary": True, "sendAsEmail": ""}]},
        {"sendAs": [{"isPrimary": True, "sendAsEmail": 'bad"@example.com'}]},
    ],
)
def test_incomplete_sending_addresses_stop_before_search(api, server, monkeypatch, response):
    server.send_as = response
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--apply"]) == 1
    assert server.writes == 0
    assert not any(call[1].endswith("/messages") for call in server.calls)


def test_send_as_denial_stops_without_reauthorization_or_write(api, server, monkeypatch):
    server.send_as_status = 403
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    monkeypatch.setattr(cli, "authorize", lambda *a, **kw: pytest.fail("Unexpected authorization"))
    assert cli.main(ARGS + ["--apply"]) == 1
    assert server.writes == 0


def test_returned_own_sender_is_never_added(api, server, monkeypatch):
    import httplib2

    server.mailbox["messages"][1]["payload"]["headers"][0]["value"] = "Alias <alias@example.com>"
    original = server.request

    def ignored_query(uri, *args, **kwargs):
        if "/messages?" in uri:
            return httplib2.Response({"status": "200"}), json.dumps(
                {"messages": [{"id": "m2"}]}
            ).encode()
        return original(uri, *args, **kwargs)

    monkeypatch.setattr(server, "request", ignored_query)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--apply"]) == 1
    assert server.writes == 0
