"""Single-target commands resolve conservatively before preview or mutation."""

from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.errors import SyncError

from .test_contact_resolution import setup

COMMANDS = [
    ("list-email", []),
    ("add-email", ["--add", "new@example.com"]),
    ("remove-email", ["--remove", "Jane@example.com"]),
    ("list-phone", []),
    ("remove-phone", ["--duplicates"]),
    ("format-phone", []),
    ("list-label", []),
    ("remove-label", ["--label", "Test"]),
    ("add-custom-field", ["--field", "Status", "Active"]),
    ("remove-custom-field", ["--key", "Status"]),
    ("duplicate", ["--no-photo"]),
    ("sender-sync", ["--search", "from:example.com"]),
]


@pytest.mark.parametrize("command,options", COMMANDS)
def test_command_resolution(command, options, api, server, monkeypatch):
    _, _, baseline = setup(api, server, monkeypatch)
    # Stop at the command's full read: prove routing resolves the name first, without
    # exercising unrelated preview logic already covered by command-specific suites.
    seen = []

    def read(resource, *args, **kwargs):
        seen.append(resource)
        raise SyncError("test reached command read")

    monkeypatch.setattr(api, "get_contact", read)
    assert cli.main([command, "--contact", "Jane Example", *options]) == 1
    assert seen == ["people/c123"]
    assert server.writes == baseline


@pytest.mark.parametrize("command,options", COMMANDS)
def test_missing_target_blocks_command(command, options, api, server, monkeypatch, capsys):
    _, _, baseline = setup(api, server, monkeypatch)
    monkeypatch.setattr(api, "get_contact", lambda *a: pytest.fail("command read"))
    assert cli.main([command, "--contact", "Missing Person", *options]) == (
        0 if command in {"format-phone", "list-email", "list-phone", "list-label"} else 1
    )
    output = capsys.readouterr()
    if command in {"format-phone", "list-email", "list-phone", "list-label"}:
        assert "Unmatched inputs" in output.out
    else:
        assert "No saved contact matches" in output.err
    assert server.writes == baseline


@pytest.mark.parametrize("identifier", ["Jane", "5550142", "2025550142 x42"])
def test_no_partial_matching(identifier, api, server, monkeypatch, capsys):
    setup(api, server, monkeypatch)
    assert cli.main(["list-email", "--contact", identifier]) == 0
    assert "Unmatched inputs" in capsys.readouterr().out


@pytest.mark.parametrize(
    "identifier",
    ["  jane   EXAMPLE ", "JANE@EXAMPLE.COM", "12025550142", "+1 202-555-0142 ext. 42"],
)
def test_supported_identifiers(identifier, api, server, monkeypatch, capsys):
    _, _, baseline = setup(api, server, monkeypatch)
    assert cli.main(["list-email", "--contact", identifier]) == 0
    assert "Jane@example.com" in capsys.readouterr().out
    assert server.writes == baseline


@pytest.mark.parametrize(
    "identifier", ["c123", "people/c123", "https://contacts.google.com/person/c123"]
)
def test_ids_avoid_account_scan(identifier, api, server, monkeypatch):
    setup(api, server, monkeypatch)
    assert cli.main(["list-email", "--contact", identifier]) == 0
    assert not any(path.endswith("/connections") for _, path, _, _ in server.calls)


@pytest.mark.parametrize(
    "answers,status,writes",
    [(["2"], 0, 1), (["q"], 0, 0), (None, 1, 0), (["all", "1-2", "3", "", "2"], 0, 1)],
)
def test_ambiguous_apply_selects_exactly_one(answers, status, writes, api, server, monkeypatch):
    other, _, baseline = setup(api, server, monkeypatch, answers)
    other["names"] = deepcopy(server.person["names"])
    before = deepcopy(server.person)
    assert (
        cli.main(["add-email", "--contact", "Jane Example", "--add", "new@example.com", "--apply"])
        == status
    )
    assert server.person == before
    assert server.writes == baseline + writes
    assert any(
        e["value"] == "new@example.com" for e in server.created["people/c456"]["emailAddresses"]
    ) == bool(writes)


def test_selection_is_not_write_approval(api, server, monkeypatch):
    other, _, baseline = setup(api, server, monkeypatch, ["2", "n"])
    other["names"] = deepcopy(server.person["names"])
    assert cli.main(["add-email", "--contact", "Jane Example", "--add", "new@example.com"]) == 0
    assert server.writes == baseline


@pytest.mark.parametrize(
    "identifier", ["", "  ", "bad\nname", "https://example.com/contact", "person/c123"]
)
def test_invalid_before_authorization(identifier, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("auth"))
    assert cli.main(["list-email", "--contact", identifier]) == 1


def test_lookup_failure_stops(api, server, monkeypatch):
    setup(api, server, monkeypatch)

    def fail(*a):
        raise SyncError("lookup failed")

    monkeypatch.setattr("contacts_cli.contact_resolution.read_match_contacts", fail)
    monkeypatch.setattr(api, "get_contact", lambda *a: pytest.fail("command read"))
    assert cli.main(["list-email", "--contact", "Jane Example"]) == 1


def test_eof_cancels(api, server, monkeypatch):
    other, _, baseline = setup(api, server, monkeypatch, [])
    other["names"] = deepcopy(server.person["names"])

    def eof():
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert cli.main(["list-email", "--contact", "Jane Example"]) == 0
    assert server.writes == baseline


@pytest.mark.parametrize("command,options", COMMANDS)
def test_ambiguity_cancellation_blocks_every_command(command, options, api, server, monkeypatch):
    other, _, baseline = setup(api, server, monkeypatch, ["q"])
    other["names"] = deepcopy(server.person["names"])
    monkeypatch.setattr(api, "get_contact", lambda *a: pytest.fail("command read"))
    assert cli.main([command, "--contact", "Jane Example", *options]) == 0
    assert server.writes == baseline


def test_later_page_target(api, server, monkeypatch, capsys):
    setup(api, server, monkeypatch)
    person = deepcopy(server.person)
    person["resourceName"] = "people/c789"
    person["metadata"]["sources"][0]["id"] = "789"
    person["names"] = [{"displayName": "Later Example"}]
    person["emailAddresses"] = [{"value": "later@example.com"}]
    server.created["people/c789"] = person
    assert cli.main(["list-email", "--contact", "Later Example"]) == 0
    assert "later@example.com" in capsys.readouterr().out
    assert len([p for _, p, _, _ in server.calls if p.endswith("/connections")]) == 2


def test_extension_ambiguity(api, server, monkeypatch, capsys):
    other, _, baseline = setup(api, server, monkeypatch, ["q"])
    other["phoneNumbers"] = [{"value": "+1 202-555-0142 ext. 43"}]
    assert cli.main(["list-phone", "--contact", "12025550142"]) == 0
    out = capsys.readouterr().out
    assert "Multiple contacts match" in out
    assert "Jane Example (c123)" in out and "Other Example (c456)" in out
    assert server.writes == baseline


@pytest.mark.parametrize("command,options", COMMANDS)
def test_help_lists_lookup(command, options, capsys):
    with pytest.raises(SystemExit) as result:
        cli.main([command, "--help"])
    assert result.value.code == 0
    out = capsys.readouterr().out
    assert "full name, email, or complete phone number" in " ".join(out.split())


def test_single_selection_contract(monkeypatch, capsys):
    from contacts_cli.selection import select_one

    replies = iter(["all", "1,3", "1-3", "2", "", "3"])
    monkeypatch.setattr("builtins.input", lambda: next(replies))
    assert select_one([1, 3]) == 3
    assert capsys.readouterr().out.count("Enter one displayed number") == 5
