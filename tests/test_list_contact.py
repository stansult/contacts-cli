"""Read-only contact lookup shares the label resolver's exact matching rules."""

from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.errors import SyncError

from .test_contact_resolution import setup


@pytest.mark.parametrize(
    "query,count",
    [
        ("Jane Example", 1),
        (" jane   EXAMPLE ", 1),
        ("Jane", 0),
        ("jane@example.COM", 1),
        ("example.com", 0),
        ("12025550142", 1),
        ("+1-202-555-0142 x42", 1),
        ("+12025550142 x43", 0),
        ("5550142", 0),
        ("c123", 1),
        ("people/c123", 1),
        ("https://contacts.google.com/person/c123", 1),
        ("c999999", 0),
    ],
)
def test_exact_lookup(query, count, api, server, monkeypatch, capsys):
    _, _, baseline = setup(api, server, monkeypatch)
    before = deepcopy(server.person)
    assert cli.main(["list-contact", "--search", query]) == 0
    output = capsys.readouterr().out
    assert f"Matching contacts: {count} contact" in output
    if count:
        assert "1. Jane Example (c123)" in output
        assert "Email: Jane@example.com" in output
        assert "Phone: +1 (202) 555-0142 ext. 42" in output
    assert server.writes == baseline
    assert server.person == before


def test_plural_multiple_matches_no_prompt(api, server, monkeypatch, capsys):
    other, _, baseline = setup(api, server, monkeypatch)
    other["names"] = [{"displayName": "Jane Example"}]
    assert cli.main(["list-contacts", "--search", "Jane Example"]) == 0
    output = capsys.readouterr().out
    assert "Matching contacts: 2 contacts" in output
    assert "1. Jane Example (c123)" in output
    assert "2. Jane Example (c456)" in output
    assert "Selection:" not in output
    assert server.writes == baseline


def test_id_avoids_account_scan(api, server, monkeypatch):
    _, _, baseline = setup(api, server, monkeypatch)
    monkeypatch.setattr(
        "contacts_cli.contact_listing.read_match_contacts",
        lambda *a: pytest.fail("ID lookup must not scan the account"),
    )
    assert cli.main(["list-contact", "--search", "c123"]) == 0
    assert server.writes == baseline


@pytest.mark.parametrize("query", ["", "  ", "Jane\nExample", "https://example.com/person/c123"])
def test_invalid_search_before_authorization(query, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("authorization"))
    assert cli.main(["list-contact", "--search", query]) == 1


def test_read_failure_does_not_show_empty_success(api, server, monkeypatch, capsys):
    _, _, baseline = setup(api, server, monkeypatch)

    def fail(*a):
        raise SyncError("Read failed")

    monkeypatch.setattr("contacts_cli.contact_listing.read_match_contacts", fail)
    assert cli.main(["list-contact", "--search", "Jane Example"]) == 1
    assert "Matching contacts:" not in capsys.readouterr().out
    assert server.writes == baseline


def test_later_page_match(api, server, monkeypatch, capsys):
    _, _, baseline = setup(api, server, monkeypatch)
    later = deepcopy(server.person)
    later["resourceName"] = "people/c789"
    later["names"] = [{"displayName": "Later Example"}]
    server.created["people/c789"] = later
    assert cli.main(["list-contact", "--search", "Later Example"]) == 0
    assert "1. Later Example (c789)" in capsys.readouterr().out
    assert server.writes == baseline


@pytest.mark.parametrize(
    "value,canonical,shown",
    [
        ("+12025550142", "+12025550142", False),
        ("(202) 555-0142", "+12025550142", True),
        ("+12025550142", None, False),
    ],
)
def test_redundant_canonical_phone_hidden(value, canonical, shown):
    from contacts_cli.contact_listing import contact_row

    phone = {"value": value, "type": "mobile"}
    if canonical is not None:
        phone["canonicalForm"] = canonical
    person = {"resourceName": "people/c123", "phoneNumbers": [phone]}
    before = deepcopy(person)
    output = contact_row(person)
    assert f"Phone: {value} — mobile" in output
    assert ("Canonical form:" in output) is shown
    assert person == before
