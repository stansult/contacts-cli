"""Explicit per-run exclusions extend automatic exclusions without removing entries."""

import json
from copy import deepcopy

import httplib2
import pytest

from contacts_cli import cli

ARGS = ["sender-sync", "--label", "Example/Delivery", "--contact", "people/c123"]


@pytest.mark.parametrize("apply", [False, True])
def test_repeatable_exclusions_in_query_preview_and_write(api, server, monkeypatch, capsys, apply):
    original = deepcopy(server.person["emailAddresses"])
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    exclusions = [
        " NEW@example.com ",
        "new@example.com",
        "spam@example.com",
        "existing@example.com",
    ]
    args = ARGS + [item for value in exclusions for item in ("--exclude", value)]
    assert cli.main(args + (["--apply"] if apply else [])) == 0
    output = capsys.readouterr().out
    assert ("Adding: 1" if apply else "Proposed additions: 1") in output
    assert "  1. trash@example.com" in output
    assert "  1. new@example.com" not in output and "  2. spam@example.com" not in output
    for call in server.calls:
        if call[1].endswith("/messages"):
            query = call[2]["q"][0]
            assert query.count('-from:"new@example.com"') == 1
            assert '-from:"spam@example.com"' in query
            assert '-from:"me@example.com"' in query
    assert all(entry in server.person["emailAddresses"] for entry in original)
    if not apply:
        assert server.writes == 0
        assert server.person["emailAddresses"] == original
    else:
        added = [e["value"] for e in server.person["emailAddresses"] if e not in original]
        assert added == ["trash@example.com"]
    # Exclusions are not saved as defaults for a later invocation.
    assert cli.main(ARGS) == 0
    assert "  1. new@example.com" in capsys.readouterr().out


@pytest.mark.parametrize(
    "address",
    [
        "",
        "example.com",
        "*@example.com",
        "a@example.com,b@example.com",
        "Name <a@example.com>",
        "a@example.com OR from:b@example.com",
        "a@bad..example",
        "a" * 1025 + "@example.com",
    ],
)
def test_invalid_exclusion_before_authorization(monkeypatch, address):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("network"))
    with pytest.raises(SystemExit) as exc:
        cli.main(ARGS + ["--exclude", address])
    assert exc.value.code == 2


def test_returned_excluded_candidate_is_not_added(api, server, monkeypatch):
    original = server.request
    responses = iter([[{"id": "m2"}], []])

    def ignored_query(uri, *args, **kwargs):
        if "/messages?" in uri:
            return httplib2.Response({"status": "200"}), json.dumps(
                {"messages": next(responses)}
            ).encode()
        return original(uri, *args, **kwargs)

    monkeypatch.setattr(server, "request", ignored_query)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--exclude", "new@example.com", "--apply"]) == 1
    assert server.writes == 0
