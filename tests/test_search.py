"""Sender exclusions: request volume, bounded progress, and write safety (#2)."""

from copy import deepcopy

import pytest

from contacts_cli import cli

from .test_timestamps import undecorated

ARGS = ["sender-sync", "--label", "Example/Delivery", "--contact", "people/c123"]


def test_many_messages_few_senders_needs_only_two_header_reads(api, server, monkeypatch, capsys):
    template = deepcopy(server.mailbox["messages"][0])
    server.mailbox["messages"] = []
    for index in range(1000):
        message = deepcopy(template)
        message["id"] = f"message-{index}"
        address = ("existing@example.com", "one@example.com", "two@example.com")[index % 3]
        message["payload"]["headers"][0]["value"] = address
        server.mailbox["messages"].append(message)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS) == 0
    header_reads = [call for call in server.calls if "/messages/" in call[1]]
    searches = [call for call in server.calls if call[1].endswith("/messages")]
    assert len(header_reads) == 2
    assert len(searches) == 3
    for call in searches:
        assert call[2]["maxResults"] == ["1"]
        assert call[2]["labelIds"] == ["Label_1"]
        assert call[2]["includeSpamTrash"] == ["true"]
        assert "pageToken" not in call[2]
        assert '-from:"existing@example.com"' in call[2]["q"][0]
    assert "one@example.com" not in searches[0][2]["q"][0]
    assert "one@example.com" in searches[1][2]["q"][0]
    assert "two@example.com" in searches[2][2]["q"][0]
    output = capsys.readouterr()
    assert "Inspected messages:" not in output.out
    assert "New unique senders:" not in output.out
    assert "Searching senders: 2 inspected, 2 new senders\nSearch finished." in undecorated(
        output.err
    )
    assert server.writes == 0


def test_all_known_senders_requires_no_header_reads(api, server, monkeypatch, capsys):
    server.person["emailAddresses"] = [
        {"value": address}
        for address in (
            " EXISTING@example.com ",
            "new@example.com",
            "trash@example.com",
            "spam@example.com",
        )
    ]
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--apply"]) == 0
    assert not any("/messages/" in call[1] for call in server.calls)
    assert len([call for call in server.calls if call[1].endswith("/messages")]) == 1
    assert "Searching senders: 0 inspected, 0 new senders" in capsys.readouterr().err
    assert server.writes == 0


def test_query_preserves_dot_plus_variants_and_case_dedup(api, server, monkeypatch, capsys):
    server.person["emailAddresses"] = [{"value": "a.b@example.com"}]
    addresses = ["ab@example.com", "a.b+tag@example.com", "AB@EXAMPLE.COM"]
    server.mailbox["messages"] = server.mailbox["messages"][:3]
    for message, address in zip(server.mailbox["messages"], addresses, strict=True):
        message["payload"]["headers"][0]["value"] = address
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS) == 0
    output = capsys.readouterr().out
    assert "Proposed additions: 2" in output
    assert "  2. ab@example.com" in output and "  1. a.b+tag@example.com" in output
    assert len([call for call in server.calls if "/messages/" in call[1]]) == 2


def test_all_unique_senders_requires_one_search_per_sender_plus_final(api, server):
    server.mailbox["messages"] = server.mailbox["messages"][:5]
    for index, message in enumerate(server.mailbox["messages"]):
        message["payload"]["headers"][0]["value"] = f"sender{index}@example.com"
    scan = api.scan("Example/Delivery")
    assert scan.messages == 5 and len(scan.senders) == 5
    assert len([call for call in server.calls if call[1].endswith("/messages")]) == 6
    assert len([call for call in server.calls if "/messages/" in call[1]]) == 5


def test_repeated_message_stops_before_refetch_or_write(api, server, monkeypatch, capsys):
    import json

    import httplib2

    original = server.request
    searches = 0

    def repeated(uri, *args, **kwargs):
        nonlocal searches
        if "/messages?" in uri:
            searches += 1
            return httplib2.Response({"status": "200"}), json.dumps(
                {"messages": [{"id": "m2"}]}
            ).encode()
        return original(uri, *args, **kwargs)

    monkeypatch.setattr(server, "request", repeated)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--apply"]) == 1
    assert searches == 2
    assert len([call for call in server.calls if "/messages/" in call[1]]) == 1
    assert "repeated a message" in capsys.readouterr().err
    assert server.writes == 0


def test_no_new_sender_stops_instead_of_looping(api, server, monkeypatch, capsys):
    import json

    import httplib2

    original = server.request

    def stale(uri, *args, **kwargs):
        if "/messages?" in uri:
            return httplib2.Response({"status": "200"}), json.dumps(
                {"messages": [{"id": "m1"}]}
            ).encode()
        return original(uri, *args, **kwargs)

    monkeypatch.setattr(server, "request", stale)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--apply"]) == 1
    assert "no new sender" in capsys.readouterr().err
    assert server.writes == 0


@pytest.mark.parametrize(
    "page",
    [
        [],
        {"messages": None},
        {"messages": {}},
        {"messages": [None]},
        {"messages": [{}]},
        {"messages": [{"id": 123}]},
        {"messages": [{"id": "m2"}, {"id": "m4"}]},
        {"messages": [], "nextPageToken": "more"},
    ],
)
def test_incomplete_search_response_blocks_apply(api, server, monkeypatch, capsys, page):
    import json

    import httplib2

    original = server.request

    def malformed(uri, *args, **kwargs):
        if "/messages?" in uri:
            return httplib2.Response({"status": "200"}), json.dumps(page).encode()
        return original(uri, *args, **kwargs)

    monkeypatch.setattr(server, "request", malformed)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--apply"]) == 1
    assert "Error:" in capsys.readouterr().err
    assert server.writes == 0
    assert not any("/messages/" in call[1] for call in server.calls)


@pytest.mark.parametrize(
    "address",
    [
        'bad@example.com" OR from:other@example.com',
        "line\nbreak@example.com",
        '"quoted local"@example.com',
        "user/name@example.com",
    ],
)
def test_unsafe_existing_address_never_enters_query(api, server, monkeypatch, capsys, address):
    server.person["emailAddresses"] = [{"value": address}]
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--apply"]) == 1
    error = capsys.readouterr().err
    assert "unsupported syntax" in error and address not in error
    assert not any("/gmail/" in call[1] for call in server.calls)
    assert server.writes == 0


def test_unsupported_new_address_blocks_apply(api, server, monkeypatch, capsys):
    server.mailbox["messages"][1]["payload"]["headers"][0]["value"] = "user/name@example.com"
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--apply"]) == 1
    assert "unsupported syntax" in capsys.readouterr().err
    assert server.writes == 0


@pytest.mark.parametrize("initial", [True, False])
def test_query_limit_blocks_apply_before_sending_oversized_query(
    api, server, monkeypatch, capsys, initial
):
    from urllib.parse import quote

    from contacts_cli import api as api_module

    if initial:
        server.person["emailAddresses"] = [{"value": f"sender{i}@example.com"} for i in range(300)]
    else:
        query = api_module.exclusion_query(
            {entry["value"].lower() for entry in server.person["emailAddresses"]}
            | {entry["sendAsEmail"] for entry in server.send_as["sendAs"]}
        )
        monkeypatch.setattr(api_module, "MAX_QUERY_BYTES", len(quote(query, safe="")))
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--apply"]) == 1
    assert "exceeds the local" in capsys.readouterr().err
    searches = [call for call in server.calls if call[1].endswith("/messages")]
    assert len(searches) == (0 if initial else 1)
    assert server.writes == 0


def test_http_query_error_after_discovery_does_not_apply_partial_results(api, server, monkeypatch):
    import httplib2

    original = server.request
    searches = 0

    def rejected(uri, *args, **kwargs):
        nonlocal searches
        if "/messages?" in uri:
            searches += 1
            if searches == 2:
                return httplib2.Response({"status": "400"}), b"{}"
        return original(uri, *args, **kwargs)

    monkeypatch.setattr(server, "request", rejected)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--apply"]) == 1
    assert searches == 2
    assert server.writes == 0


def test_stops_at_invalid_header_and_marks_metrics_incomplete(api, server, monkeypatch):
    import json

    from contacts_cli.metrics import default_path

    server.mailbox["messages"][1]["payload"]["headers"] = []
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--apply"]) == 1
    row = json.loads(default_path().read_text())
    assert not row["scan_complete"]
    assert row["counts"]["messages"] == 1 and row["counts"]["invalid_headers"] == 1
    assert row["outcome"] == "failed"
    assert server.writes == 0
