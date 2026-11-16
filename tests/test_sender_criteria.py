"""Address-criteria grouping is presentation only (#7)."""

import pytest

from contacts_cli import cli


@pytest.mark.parametrize("apply", [False, True])
def test_grouped_preview_preserves_all_additions(api, server, monkeypatch, capsys, apply):
    query = "from:new@example.com OR subject:delivery"
    server.search_results[query] = {"m2", "m4"}
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert (
        cli.main(
            ["sender-sync", "--contact", "c123", f"--search={query}"]
            + (["--apply"] if apply else [])
        )
        == 0
    )
    output = capsys.readouterr().out
    assert ("Adding: 2 entries" if apply else "Proposed additions: 2 entries") in output
    assert "Matching address criteria: 1 address" in output
    assert "Other senders: 1 address" in output
    assert "1. new@example.com — New sender" in output
    assert "2. trash@example.com" in output
    assert "Will add both groups: 2 addresses." in output
    assert "Both groups are included." not in output
    assert server.writes == int(apply)
    if apply:
        assert {e["value"] for e in server.person["emailAddresses"]} >= {
            "new@example.com",
            "trash@example.com",
            "Existing@Example.com",
        }


@pytest.mark.parametrize(
    "query,matching,other",
    [
        ("to:example.com", 2, 0),
        ("from:elsewhere.example.com OR subject:delivery", 0, 2),
        ("from:me", None, None),
        ("subject:delivery", None, None),
        ("-from:new@example.com", None, None),
    ],
)
def test_group_empty_and_fallback(api, server, monkeypatch, capsys, query, matching, other):
    server.search_results[query] = {"m2", "m4"}
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(["sender-sync", "--contact", "c123", f"--search={query}"]) == 0
    output = capsys.readouterr().out
    if matching is None:
        assert "Matching address criteria:" not in output
        assert "Other senders:" not in output
        assert (
            "Proposed additions: 2 entries\n"
            "Ungrouped: no full addresses or domains in from:/to: criteria.\n\n"
            "  1. new@example.com"
        ) in output
    else:
        assert "Ungrouped:" not in output
        assert f"Matching address criteria: {matching} address" in output
        assert f"Other senders: {other} address" in output
    assert server.writes == 0


@pytest.mark.parametrize(
    "query,addresses,domains",
    [
        ("from:One@Example.com to:example.org", {"one@example.com"}, {"example.org"}),
        ('from:"one@example.com"', {"one@example.com"}, set()),
        (
            "from:(one@example.com OR two@example.com)",
            {"one@example.com", "two@example.com"},
            set(),
        ),
        ("{from:example.com to:example.org}", set(), {"example.com", "example.org"}),
        ("from:{example.com example.org}", set(), {"example.com", "example.org"}),
        (
            "-(from:bad.example.com OR to:bad.example.org) from:good.example.com",
            set(),
            {"good.example.com"},
        ),
        ("NOT from:bad.example.com from:good.example.com", set(), {"good.example.com"}),
        ('subject:"from:bad.example.com" to:good.example.com', set(), {"good.example.com"}),
        ("subject:(from:bad.example.com) from:good.example.com", set(), {"good.example.com"}),
        ("from:Jane to:me cc:example.com", set(), set()),
        ("from:*.example.com from:one@example.com", {"one@example.com"}, set()),
        ("from:(example.com Jane)", set(), set()),
        ("from:(example.com -bad.example.com)", set(), set()),
        ("from:example.com -to:example.org", set(), {"example.com"}),
        ("from:example.com to:example.com", set(), {"example.com"}),
        ("from:(example.com", set(), set()),
        ('from:"example.com', set(), set()),
        ("from:example.com)", set(), set()),
        ("from:(((" * 40, set(), set()),
    ],
)
def test_extract(query, addresses, domains):
    from contacts_cli.sender_criteria import extract_search_criteria

    criteria = extract_search_criteria(query)
    assert criteria.addresses == frozenset(addresses)
    assert criteria.domains == frozenset(domains)


@pytest.mark.parametrize(
    "address,expected",
    [
        ("PERSON@EXAMPLE.COM", True),
        ("person@mail.example.com", True),
        ("person@notexample.com", False),
        ("person@example.com.evil.org", False),
        ("example.com@elsewhere.org", False),
        ("Exact@other.org", True),
        ("exact+tag@other.org", False),
        ("ex.act@other.org", False),
    ],
)
def test_shared_matching(address, expected):
    from contacts_cli.sender_criteria import AddressCriteria

    criteria = AddressCriteria(frozenset({"exact@other.org"}), frozenset({"example.com"}))
    assert criteria.matches(address) is expected


def test_fixture_grouping_inputs_independently(server):
    from urllib.parse import urlencode

    from .test_fixture_contract import fetch

    query = "from:new@example.com OR subject:delivery"
    server.search_results[query] = {"m2", "m4"}
    _, page = fetch(
        server,
        "/gmail/v1/users/me/messages?"
        + urlencode(
            {
                "q": f"({query})",
                "includeSpamTrash": "true",
            }
        ),
    )
    assert [item["id"] for item in page["messages"]] == ["m2", "m4"]
    for identity, expected in [("m2", "New sender <new@example.com>"), ("m4", "trash@example.com")]:
        _, message = fetch(
            server, f"/gmail/v1/users/me/messages/{identity}?format=metadata&metadataHeaders=From"
        )
        assert message["payload"]["headers"][0]["value"] == expected


def test_no_additions_keeps_simple_noop(api, server, monkeypatch, capsys):
    query = "from:example.com"
    server.search_results[query] = set()
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(["sender-sync", "--contact", "c123", "--search", query, "--apply"]) == 0
    output = capsys.readouterr().out
    assert "Ungrouped:" not in output
    assert "Adding: 0 entries" in output
    assert "Other senders:" not in output
    assert server.writes == 0


def test_partition_reorders_display_without_dropping_entries():
    from contacts_cli.sender_criteria import AddressCriteria

    first = {"value": "one@elsewhere.org", "type": "One"}
    second = {"value": "two@example.com", "type": "Two"}
    third = {"value": "three@example.com"}
    entries = [first, second, third]
    matching, other = AddressCriteria(domains=frozenset({"example.com"})).partition(entries)
    assert matching == [second, third]
    assert other == [first]
    assert entries == [first, second, third]


def test_grouped_preview_renumbers_after_partition(api, server, monkeypatch, capsys):
    query = "to:trash@example.com OR subject:delivery"
    server.search_results[query] = {"m2", "m4"}
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(["sender-sync", "--contact", "c123", "--search", query]) == 0
    output = capsys.readouterr().out
    assert output.index("1. trash@example.com") < output.index("2. new@example.com")
    assert server.writes == 0


def test_label_preview_has_no_ungrouped_note(api, monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(["sender-sync", "--contact", "c123", "--label", "Example/Delivery"]) == 0
    assert "Ungrouped:" not in capsys.readouterr().out
