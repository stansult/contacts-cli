"""Current Gmail filter criteria feed the shared sender grouping (#9)."""

import sys
from copy import deepcopy

import pytest
from googleapiclient.errors import HttpError

from contacts_cli import cli
from contacts_cli.errors import SyncError

ARGS = ["sender-sync", "--contact", "c123", "--label", "Example/Delivery"]


def rule(criteria, label="Label_1"):
    return {"id": "filter-example", "action": {"addLabelIds": [label]}, "criteria": criteria}


def configure(api, server, monkeypatch, criteria=None, *, tty=False, answers=()):
    server.filters_response = {"filter": [rule(criteria or {"from": "new@example.com"})]}
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *args: api)
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: tty)
    replies = iter(answers)
    monkeypatch.setattr("builtins.input", lambda: next(replies))


@pytest.mark.parametrize("status", [200, 403])
def test_filter_transport_contract(server, status):
    response = {"filter": [rule({"from": "new@example.com"}, "Label_2")]}
    server.filters_response = deepcopy(response)
    server.filters_status = status
    gmail, _ = server.clients()
    request = gmail.users().settings().filters().list(userId="me")
    if status == 200:
        assert request.execute() == response
    else:
        with pytest.raises(HttpError) as error:
            request.execute()
        assert error.value.resp.status == status
    method, path, _, body = server.calls[-1]
    assert method == "GET" and path.endswith("/settings/filters") and body is None
    assert server.writes == 0


def test_unions_only_selected_label_positive_criteria(api, server):
    server.filters_response = {
        "filter": [
            rule({"from": "{ONE@example.com example.org}", "to": "recipient@example.net"}),
            rule(
                {
                    "query": "from:two@example.com OR to:sub.example.org OR subject:other",
                    "negatedQuery": "from:ignored.example",
                }
            ),
            rule({"from": "unrelated@example.com"}, "Label_2"),
            rule({"subject": "from:ignored.example", "from": "partial"}),
        ]
    }
    criteria = api.label_address_criteria("Label_1")
    assert criteria.addresses == frozenset(
        {"one@example.com", "two@example.com", "recipient@example.net"}
    )
    assert criteria.domains == frozenset({"example.org", "sub.example.org"})


@pytest.mark.parametrize(
    "criteria",
    [
        {},
        {"from": "partial"},
        {"from": "-x@example.com"},
        {"query": "-from:example.com"},
        {"from": "(bad@example.com"},
    ],
)
def test_no_supported_criteria(api, server, criteria):
    server.filters_response = {"filter": [rule(criteria)]}
    assert not api.label_address_criteria("Label_1")


@pytest.mark.parametrize(
    "response",
    [
        None,
        {"filter": None},
        {"filter": [None]},
        {"filter": [{"action": None}]},
        {"filter": [{"action": {"addLabelIds": "Label_1"}}]},
        {"filter": [rule({"from": None})]},
    ],
)
def test_malformed_filters_rejected(api, server, response):
    server.filters_response = response
    with pytest.raises(SyncError, match="filter"):
        api.label_address_criteria("Label_1")


@pytest.mark.parametrize(
    "flags,count",
    [([], 0), (["--apply"], 3), (["--exclude-other"], 0), (["--exclude-other", "--apply"], 1)],
)
def test_label_grouping_reuses_selection(api, server, monkeypatch, capsys, flags, count):
    configure(api, server, monkeypatch)
    original = deepcopy(server.person["emailAddresses"])
    assert cli.main(ARGS + flags) == 0
    captured = capsys.readouterr()
    output = captured.out
    assert "Matching address criteria: 1 address" in output
    assert "Other senders" in output
    assert "Reading label filters" in captured.err
    assert len(server.person["emailAddresses"]) == len(original) + count
    assert server.person["emailAddresses"][: len(original)] == original
    if count == 1:
        assert server.person["emailAddresses"][-1]["value"] == "new@example.com"


def test_interactive_case_choice_and_exclusion(api, server, monkeypatch, capsys):
    configure(api, server, monkeypatch, tty=True, answers=["y", "y", "y"])
    assert cli.main([*ARGS[:-1], "example/delivery"]) == 0
    assert "Exclude Other senders?" in capsys.readouterr().err
    assert server.person["emailAddresses"][-1]["value"] == "new@example.com"
    assert len(server.person["emailAddresses"]) == 3


@pytest.mark.parametrize(
    "filters",
    [
        {},
        {"filter": []},
        {"filter": [rule({"subject": "delivery"})]},
        {"filter": [rule({"from": "new@example.com"}, "Label_2")]},
    ],
)
@pytest.mark.parametrize("flag", [False, True])
def test_fallback_or_explicit_exclusion_error(api, server, monkeypatch, capsys, filters, flag):
    configure(api, server, monkeypatch)
    server.filters_response = filters
    assert cli.main(ARGS + (["--exclude-other"] if flag else [])) == int(flag)
    output = capsys.readouterr()
    assert (
        ("--exclude-other" in output.err)
        if flag
        else ("Ungrouped: no usable address criteria in label filters." in output.out)
    )
    assert server.writes == 0
    assert any(path.endswith("/settings/filters") for _, path, _, _ in server.calls)
    if flag:
        assert not any(path.endswith("/messages") for _, path, _, _ in server.calls)


def test_filter_read_failure_stops_before_search(api, server, monkeypatch):
    configure(api, server, monkeypatch)
    server.filters_status = 403
    assert cli.main(ARGS + ["--apply"]) == 1
    assert server.writes == 0
    assert not any(path.endswith("/messages") for _, path, _, _ in server.calls)


def test_search_does_not_read_filters(api, server, monkeypatch):
    configure(api, server, monkeypatch)
    query = "from:new@example.com"
    server.search_results[query] = {"m2"}
    assert cli.main(["sender-sync", "--contact", "c123", "--search", query]) == 0
    assert not any(path.endswith("/settings/filters") for _, path, _, _ in server.calls)


def test_case_choice_uses_resolved_label_id(api, server, monkeypatch):
    configure(api, server, monkeypatch, tty=True, answers=["2", "y", "y"])
    server.mailbox["labels"] = [
        {"id": "Label_2", "name": "EXAMPLE/DELIVERY"},
        {"id": "Label_1", "name": "Example/Delivery"},
    ]
    server.filters_response["filter"].append(rule({"from": "spam@example.com"}, "Label_2"))
    assert cli.main([*ARGS[:-1], "example/delivery"]) == 0
    assert len(server.person["emailAddresses"]) == 3
    assert server.person["emailAddresses"][-1]["value"] == "new@example.com"
