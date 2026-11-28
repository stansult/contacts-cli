"""Compact contact resolution and label review explain inputs and selected actions."""

from copy import deepcopy

from contacts_cli import cli
from contacts_cli.contact_resolution import resolve_contacts

from .test_contact_resolution import setup


def test_compact_numbered_matches_and_summary(api, server, monkeypatch, tmp_path, capsys):
    setup(api, server, monkeypatch)
    server.person["organizations"] = [{"name": "Example Org"}]
    server.person["emailAddresses"].append({"value": "unrelated@example.com"})
    path = tmp_path / "contacts.txt"
    path.write_text("jane@example.com\nOther Example\nabsent@example.com\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "Test"]) == 0
    out = capsys.readouterr().out
    assert "Matched contacts: 2 contacts" in out
    row = next(line for line in out.splitlines() if "Jane Example (c123)" in line)
    assert row.startswith("  1.") and row.endswith(" — Example Org — jane@example.com")
    assert "unrelated@example.com" not in out and "+1 (202)" not in out
    assert "Matched '" not in out
    assert "Inputs reviewed: 3; matched: 2; unmatched: 1; skipped by choice: 0." in out
    assert "Proposed label additions: 'Test' — 2 contacts" in out
    assert "     Add: Test" not in out


def test_shared_label_confirmation(api, server, monkeypatch, tmp_path, capsys):
    setup(api, server, monkeypatch, ["all", "y"])
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc456\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "Test"]) == 0
    out = capsys.readouterr().out
    assert "Choose contacts to label:" in out
    assert "Add label 'Test' to 2 contacts?" in out


def test_differing_additions_keep_per_contact_details(api, server, monkeypatch, tmp_path, capsys):
    from .test_label_edit import group

    _, label, _ = setup(api, server, monkeypatch)
    group(server, "Second")
    server.person["memberships"] = [{"contactGroupMembership": {"contactGroupResourceName": label}}]
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc456\n")
    assert (
        cli.main(["add-label", "--contact-file", str(path), "--label", "Test", "--label", "Second"])
        == 0
    )
    out = capsys.readouterr().out
    assert "     Add: Second" in out and "     Add: Test, Second" in out


def test_later_match_explains_skipped_identifier(api, server, monkeypatch, tmp_path, capsys):
    other, _, _ = setup(api, server, monkeypatch, ["s"])
    other["names"] = deepcopy(server.person["names"])
    path = tmp_path / "contacts.txt"
    path.write_text("Jane Example\nother@example.com\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "Test", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "Multiple contacts match 'Jane Example': 2 contacts" in out
    assert "More matched contacts: 1 contact" in out
    assert (
        "#2 matched through 'other@example.com'; "
        "only the earlier identifier 'Jane Example' was skipped." in out
    )
    assert "Inputs reviewed: 2; matched: 1; unmatched: 0; skipped by choice: 1." in out


def test_repeated_contact_counts_inputs_separately(monkeypatch, capsys):
    person = {
        "resourceName": "people/c123",
        "names": [{"displayName": "Example Person"}],
        "emailAddresses": [{"value": "example@example.com"}],
    }
    monkeypatch.setattr("contacts_cli.contact_resolution.read_match_contacts", lambda api: [person])
    assert resolve_contacts(object(), ["Example Person", "example@example.com"]) == {
        "people/c123": 1
    }
    out = capsys.readouterr().out
    assert "Inputs reviewed: 2; matched: 2; unmatched: 0; skipped by choice: 0." in out
    assert "Contacts resolved: 1." in out
