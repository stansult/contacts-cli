"""Contact identifiers resolve before any label writes."""

from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.label_edit import memberships

from .test_label_edit import group


def setup(api, server, monkeypatch, answers=None):
    server.person["names"] = [{"displayName": "Jane Example"}]
    server.person["emailAddresses"] = [{"value": "Jane@example.com"}]
    server.person["phoneNumbers"] = [{"value": "+1 (202) 555-0142 ext. 42"}]
    other = deepcopy(server.person)
    other["resourceName"] = "people/c456"
    other["metadata"]["sources"][0]["id"] = "456"
    other["names"] = [{"displayName": "Other Example"}]
    other["emailAddresses"] = [{"value": "other@example.com"}]
    other["phoneNumbers"] = [{"value": "202-555-0142"}]
    server.created["people/c456"] = other
    label = group(server, "Test")
    baseline = server.writes
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (cli.sys.stdin, cli.sys.stdout, cli.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: answers is not None)
    replies = iter(answers or [])

    def answer():
        assert server.writes == baseline
        return next(replies)

    monkeypatch.setattr("builtins.input", answer)
    return other, label, baseline


@pytest.mark.parametrize(
    "identifier", ["jane@example.COM", "  jane   EXAMPLE ", "+1-202-555-0142 x42"]
)
def test_exact_resolution(identifier, api, server, monkeypatch):
    other, label, baseline = setup(api, server, monkeypatch)
    assert cli.main(["add-label", "--contact", identifier, "--label", "Test", "--apply"]) == 0
    assert label in memberships(server.person)
    assert label not in memberships(other)
    assert server.writes == baseline + 1


@pytest.mark.parametrize("identifier", ["Jane", "example.com", "2025550142 ext42"])
def test_no_partial_country_or_extension_guess(identifier, api, server, monkeypatch):
    _, _, baseline = setup(api, server, monkeypatch)
    assert cli.main(["add-label", "--contact", identifier, "--label", "New", "--apply"]) == 0
    assert server.writes == baseline


def test_file_dedup_apply(api, server, monkeypatch, tmp_path):
    other, label, baseline = setup(api, server, monkeypatch)
    path = tmp_path / "contacts.txt"
    path.write_text("# Contacts\nc123\n\njane@example.com\n2025550142\nc456\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "Test", "--apply"]) == 0
    assert label in memberships(server.person) and label in memberships(other)
    assert server.writes == baseline + 2


def test_missing_file_target_skipped(api, server, monkeypatch, tmp_path, capsys):
    _, _, baseline = setup(api, server, monkeypatch)
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nmissing@example.com\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "New", "--apply"]) == 0
    assert server.writes == baseline + 2
    assert "Skipped" in capsys.readouterr().out


@pytest.mark.parametrize("answers,expected", [(None, 1), (["q"], 0), (["2", "y"], 0)])
def test_multiple_matches(api, server, monkeypatch, answers, expected):
    other, label, baseline = setup(api, server, monkeypatch, answers)
    other["names"] = deepcopy(server.person["names"])
    assert cli.main(["add-label", "--contact", "Jane Example", "--label", "Test"]) == expected
    assert label not in memberships(server.person)
    assert (label in memberships(other)) == (answers == ["2", "y"])
    assert server.writes == baseline + (answers == ["2", "y"])


@pytest.mark.parametrize(
    "answers,selected",
    [(["2", "y"], {2}), (["all", "n", "1", "y"], {1}), (["q"], set()), (None, set())],
)
def test_file_partial_selection(api, server, monkeypatch, tmp_path, answers, selected):
    other, label, baseline = setup(api, server, monkeypatch, answers)
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc456\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "Test"]) == 0
    assert (label in memberships(server.person)) == (1 in selected)
    assert (label in memberships(other)) == (2 in selected)
    assert server.writes == baseline + len(selected)
    assert not any("/connections" in call[1] for call in server.calls)


@pytest.mark.parametrize(
    "contents", ["", "# nothing\n\n", "https://example.com/contact", "person/c123"]
)
def test_bad_file_before_auth(contents, monkeypatch, tmp_path):
    def connect(*args):
        pytest.fail("Invalid file must be rejected before authorization")

    monkeypatch.setattr(cli, "connect_with_authorization", connect)
    path = tmp_path / "contacts.txt"
    path.write_text(contents)
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "Test"]) == 1


def test_ambiguous_apply_never_guesses(api, server, monkeypatch):
    other, _, baseline = setup(api, server, monkeypatch)
    other["emailAddresses"] = deepcopy(server.person["emailAddresses"])
    assert (
        cli.main(["add-label", "--contact", "jane@example.com", "--label", "New", "--apply"]) == 1
    )
    assert server.writes == baseline


def test_create_label_once_and_rerun(api, server, monkeypatch, tmp_path):
    other, _, baseline = setup(api, server, monkeypatch)
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc456\n")
    args = ["add-label", "--contact-file", str(path), "--label", "New", "--apply"]
    assert cli.main(args) == 0
    assert server.writes == baseline + 3
    assert memberships(server.person) == memberships(other)
    assert cli.main(args) == 0
    assert server.writes == baseline + 3


def test_all_matches_and_overlapping_file(api, server, monkeypatch, tmp_path):
    other, label, baseline = setup(api, server, monkeypatch, ["all"])
    other["names"] = deepcopy(server.person["names"])
    path = tmp_path / "contacts.txt"
    path.write_text("Jane Example\nc123\nother@example.com\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "Test", "--apply"]) == 0
    assert server.writes == baseline + 2
    assert label in memberships(other)
    assert sum("/connections" in call[1] for call in server.calls) == 1


def test_fixture_multiple_contact_membership_contract(api, server, monkeypatch):
    from .test_fixture_contract import fetch

    other, label, _ = setup(api, server, monkeypatch)
    assert fetch(
        server, f"/v1/{label}/members:modify", "POST", {"resourceNamesToAdd": ["people/c456"]}
    ) == (200, {})
    assert label in memberships(other) and label not in memberships(server.person)
    status, result = fetch(
        server,
        "/v1/people/me/connections?personFields=metadata,names,organizations,emailAddresses,phoneNumbers&pageSize=1000&sources=READ_SOURCE_TYPE_CONTACT",
    )
    assert status == 200
    assert {p["resourceName"] for p in result["connections"]} == {"people/c123", "people/c456"}
    assert all("emailAddresses" in p and "phoneNumbers" in p for p in result["connections"])


@pytest.mark.parametrize("failure", ["identity", "verify", "interrupt"])
def test_bulk_failure_stops_and_reports(api, server, monkeypatch, tmp_path, capsys, failure):
    from contacts_cli import bulk_labels
    from contacts_cli.errors import SyncError, WriteUnverified

    _, _, baseline = setup(api, server, monkeypatch)
    calls = []
    real = bulk_labels.add_membership

    def apply(api, person, label):
        calls.append(person["resourceName"])
        if len(calls) == 2:
            if failure == "interrupt":
                raise KeyboardInterrupt
            if failure == "verify":
                raise WriteUnverified("Synthetic verification failure")
            raise SyncError("Contact identity changed")
        return real(api, person, label)

    monkeypatch.setattr(bulk_labels, "add_membership", apply)
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc456\n")
    result = cli.main(["add-label", "--contact-file", str(path), "--label", "Test", "--apply"])
    assert result == {"identity": 1, "verify": 3, "interrupt": 130}[failure]
    assert server.writes == baseline + 1
    assert "1 label addition verified" in capsys.readouterr().out


def test_contact_file_exclusive_and_only_add(monkeypatch):
    for args in [
        ["add-label", "--contact", "c123", "--contact-file", "list.txt", "--label", "Test"],
        ["remove-label", "--contact", "c123", "--contact-file", "list.txt", "--label", "Test"],
    ]:
        with pytest.raises(SystemExit) as exc:
            cli.main(args)
        assert exc.value.code == 2


@pytest.mark.parametrize(
    "identifier", ["c123", "people/c123", "https://contacts.google.com/person/c123"]
)
def test_direct_identifier_avoids_directory(api, server, monkeypatch, identifier):
    _, _, baseline = setup(api, server, monkeypatch)
    assert cli.main(["add-label", "--contact", identifier, "--label", "Test"]) == 0
    assert server.writes == baseline
    assert not any("/connections" in call[1] for call in server.calls)


@pytest.mark.parametrize("kind", ["missing", "encoding"])
def test_unreadable_file_before_auth(monkeypatch, tmp_path, kind):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("No auth"))
    path = tmp_path / "contacts.txt"
    if kind == "encoding":
        path.write_bytes(b"\xff")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "Test"]) == 1


def test_batch_unresolved_label_case_writes_nothing(api, server, monkeypatch, tmp_path):
    _, _, baseline = setup(api, server, monkeypatch)
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc456\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "test", "--apply"]) == 1
    assert server.writes == baseline


def test_company_equal_name(api, server, monkeypatch):
    other, label, _ = setup(api, server, monkeypatch)
    other["names"] = [{"displayName": "Example Company"}]
    other["organizations"] = [{"name": "Example Company"}]
    assert (
        cli.main(["add-label", "--contact", "example company", "--label", "Test", "--apply"]) == 0
    )
    assert label in memberships(other) and label not in memberships(server.person)


def test_missing_id_skipped(api, server, monkeypatch, tmp_path, capsys):
    _, _, baseline = setup(api, server, monkeypatch)
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc999\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "New", "--apply"]) == 0
    assert server.writes == baseline + 2
    assert "Skipped" in capsys.readouterr().out


def test_phone_extension_hash_is_not_inline_comment(api, server, monkeypatch, tmp_path):
    _, label, _ = setup(api, server, monkeypatch)
    path = tmp_path / "contacts.txt"
    path.write_text("\ufeff# Contacts\n+1 202 555 0142 #42\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "Test", "--apply"]) == 0
    assert label in memberships(server.person)


def test_company_only_does_not_match_name(api, server, monkeypatch):
    other, _, baseline = setup(api, server, monkeypatch)
    other["names"] = []
    other["organizations"] = [{"name": "Example Company"}]
    assert (
        cli.main(["add-label", "--contact", "Example Company", "--label", "Test", "--apply"]) == 0
    )
    assert server.writes == baseline


@pytest.mark.parametrize(
    "identifier", ["missing@example.com", "Nobody Example", "+442055501234", "c999"]
)
def test_all_unmatched_no_label_creation(api, server, monkeypatch, identifier, capsys):
    _, _, baseline = setup(api, server, monkeypatch)
    assert cli.main(["add-label", "--contact", identifier, "--label", "New", "--apply"]) == 0
    assert server.writes == baseline
    output = capsys.readouterr().out
    assert "Skipped" in output and "No contacts selected; no changes made." in output


@pytest.mark.parametrize("apply", [False, True])
def test_mixed_unmatched_file(api, server, monkeypatch, tmp_path, capsys, apply):
    other, label, baseline = setup(api, server, monkeypatch)
    path = tmp_path / "contacts.txt"
    path.write_text("missing@example.com\nc123\nc999\nOther Example\nUnknown Person\n")
    args = ["add-label", "--contact-file", str(path), "--label", "Test"]
    assert cli.main(args + (["--apply"] if apply else [])) == 0
    assert server.writes == baseline + (2 if apply else 0)
    assert (label in memberships(other)) == apply
    output = capsys.readouterr().out
    assert "Unmatched inputs: 2 inputs" in output
    assert "Skipped 'c999': contact not found." in output


def test_read_failure_still_blocks_before_writes(api, server, monkeypatch, tmp_path):
    from contacts_cli.errors import SyncError

    _, _, baseline = setup(api, server, monkeypatch)
    real = api.get_contact

    def read(resource, fields):
        if resource == "people/c456":
            raise SyncError("Synthetic connection failure")
        return real(resource, fields)

    monkeypatch.setattr(api, "get_contact", read)
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc456\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "New", "--apply"]) == 1
    assert server.writes == baseline


@pytest.mark.parametrize(
    "saved,identifier,expected",
    [
        ("+1 (202) 555-0142", "12025550142", True),
        ("1 (202) 555-0142", "+12025550142", True),
        ("+1 (202) 555-0142 ext. 42", "12025550142 x42", True),
        ("1 (202) 555-0142 #42", "+12025550142 ext42", True),
        ("+1 (202) 555-0142", "2025550142", False),
        ("+1 (202) 555-0142 ext42", "12025550142", True),
        ("+1 (202) 555-0142 ext42", "12025550142 x43", False),
        ("+44 20 5550 1234", "00442055501234", False),
    ],
)
def test_optional_phone_plus(api, server, monkeypatch, saved, identifier, expected):
    _, label, baseline = setup(api, server, monkeypatch)
    server.person["phoneNumbers"] = [{"value": saved}]
    server.created["people/c456"]["phoneNumbers"] = []
    assert cli.main(["add-label", "--contact", identifier, "--label", "Test", "--apply"]) == 0
    assert (label in memberships(server.person)) == expected
    assert server.writes == baseline + expected


def test_optional_plus_ambiguity_does_not_guess(api, server, monkeypatch):
    other, _, baseline = setup(api, server, monkeypatch)
    other["phoneNumbers"] = [{"value": "12025550142 ext42"}]
    assert (
        cli.main(["add-label", "--contact", "+12025550142 x42", "--label", "Test", "--apply"]) == 1
    )
    assert server.writes == baseline


def test_optional_plus_file_deduplicates(api, server, monkeypatch, tmp_path):
    _, label, baseline = setup(api, server, monkeypatch)
    path = tmp_path / "contacts.txt"
    path.write_text("12025550142 ext42\n+12025550142 ext42\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "Test", "--apply"]) == 0
    assert label in memberships(server.person)
    assert server.writes == baseline + 1


@pytest.mark.parametrize(
    "answers,selected",
    [(["1", "y"], {1}), (["2", "y"], {2}), (["all", "all", "y"], {1, 2}), (["q"], set())],
)
def test_base_phone_selects_extensions(api, server, monkeypatch, answers, selected, capsys):
    other, label, baseline = setup(api, server, monkeypatch, answers)
    other["phoneNumbers"] = [{"value": "1-202-555-0142 ext 43"}]
    assert cli.main(["add-label", "--contact", "12025550142", "--label", "Test"]) == 0
    assert (label in memberships(server.person)) == (1 in selected)
    assert (label in memberships(other)) == (2 in selected)
    assert server.writes == baseline + len(selected)
    output = capsys.readouterr().out
    assert "ext. 42" not in output and "ext 43" not in output
    assert "Multiple contacts match '12025550142': 2 contacts" in output


@pytest.mark.parametrize("saved", ["+12025550142 ext43", "+12025550142"])
def test_explicit_extension_only_matches_same_extension(api, server, monkeypatch, saved):
    other, label, baseline = setup(api, server, monkeypatch)
    other["phoneNumbers"] = [{"value": saved}]
    assert (
        cli.main(["add-label", "--contact", "12025550142 x42", "--label", "Test", "--apply"]) == 0
    )
    assert label in memberships(server.person)
    assert label not in memberships(other)
    assert server.writes == baseline + 1


def test_base_phone_ambiguity_noninteractive_apply(api, server, monkeypatch):
    other, _, baseline = setup(api, server, monkeypatch)
    other["phoneNumbers"] = [{"value": "+12025550142"}]
    assert cli.main(["add-label", "--contact", "12025550142", "--label", "Test", "--apply"]) == 1
    assert server.writes == baseline


def test_base_and_extension_file_deduplicates(api, server, monkeypatch, tmp_path):
    _, label, baseline = setup(api, server, monkeypatch)
    server.person["phoneNumbers"].append({"value": "+12025550142 ext43"})
    path = tmp_path / "contacts.txt"
    path.write_text("12025550142\n+12025550142 ext42\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "Test", "--apply"]) == 0
    assert label in memberships(server.person)
    assert server.writes == baseline + 1


def test_unchanged_and_proposed_keep_match_numbers(api, server, monkeypatch, capsys):
    other, label, baseline = setup(api, server, monkeypatch, ["all", "y"])
    other["names"] = deepcopy(server.person["names"])
    other["memberships"] = [{"contactGroupMembership": {"contactGroupResourceName": label}}]
    assert cli.main(["add-label", "--contact", "Jane Example", "--label", "Test"]) == 0
    output = capsys.readouterr().out
    unchanged = output.split("Already have all requested labels:", 1)[1].split("Add label", 1)[0]
    assert "  2. Jane Example (c456)" in unchanged
    proposed = output.split("Add label 'Test':", 1)[1]
    assert "  1. Jane Example (c123)" in proposed
    assert server.writes == baseline + 1


def test_sparse_numbers_select_original_contact(api, server, monkeypatch, tmp_path, capsys):
    other, label, baseline = setup(api, server, monkeypatch, ["1", "3", "y"])
    server.person["memberships"] = [{"contactGroupMembership": {"contactGroupResourceName": label}}]
    third = deepcopy(other)
    third["resourceName"] = "people/c789"
    third["metadata"]["sources"][0]["id"] = "789"
    third["names"] = [{"displayName": "Third Example"}]
    server.created["people/c789"] = third
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc456\nc789\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "Test"]) == 0
    output = capsys.readouterr().out
    assert "  2. Other Example (c456)" in output
    assert "  3. Third Example (c789)" in output
    assert label not in memberships(other) and label in memberships(third)
    assert server.writes == baseline + 1


def test_match_subset_keeps_original_numbers(api, server, monkeypatch, capsys):
    other, label, baseline = setup(api, server, monkeypatch, ["2-3", "3", "y"])
    third = deepcopy(other)
    third["resourceName"] = "people/c789"
    third["metadata"]["sources"][0]["id"] = "789"
    server.created["people/c789"] = third
    for person in (other, third):
        person["names"] = deepcopy(server.person["names"])
    assert cli.main(["add-label", "--contact", "Jane Example", "--label", "Test"]) == 0
    output = capsys.readouterr().out.split("Add label 'Test':", 1)[1]
    assert "  2. Jane Example (c456)" in output and "  3. Jane Example (c789)" in output
    assert label not in memberships(server.person) and label not in memberships(other)
    assert label in memberships(third) and server.writes == baseline + 1


def test_resolver_numbers_reused_across_identifiers(monkeypatch):
    from contacts_cli.contact_resolution import resolve_contacts

    people = [
        {
            "resourceName": f"people/c{i}",
            "names": [{"displayName": "Same Name"}],
            "emailAddresses": [{"value": "shared@example.com"}],
        }
        for i in (1, 2)
    ]
    monkeypatch.setattr("contacts_cli.contact_resolution.read_match_contacts", lambda api: people)
    for stream in (cli.sys.stdin, cli.sys.stdout, cli.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    replies = iter(["2", "all"])
    monkeypatch.setattr("builtins.input", lambda: next(replies))
    assert resolve_contacts(object(), ["Same Name", "shared@example.com", "c2"]) == {
        "people/c2": 2,
        "people/c1": 1,
    }


@pytest.mark.parametrize("answer", ["s", "S"])
def test_skip_ambiguous_identifier_continue_file(
    api, server, monkeypatch, tmp_path, capsys, answer
):
    other, label, baseline = setup(api, server, monkeypatch, [answer, "y"])
    other["names"] = deepcopy(server.person["names"])
    path = tmp_path / "contacts.txt"
    path.write_text("Jane Example\nother@example.com\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "Test"]) == 0
    assert label not in memberships(server.person) and label in memberships(other)
    assert server.writes == baseline + 1
    output = capsys.readouterr().out
    assert "Skipped 'Jane Example' by choice." in output
    assert "s       Skip this identifier" in output and "q       Cancel command" in output


def test_skip_does_not_discard_previous_resolution(api, server, monkeypatch, tmp_path):
    other, label, baseline = setup(api, server, monkeypatch, ["s"])
    other["names"] = deepcopy(server.person["names"])
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nJane Example\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "Test", "--apply"]) == 0
    assert label in memberships(server.person) and label not in memberships(other)
    assert server.writes == baseline + 1


def test_only_identifier_skipped_no_labels_created(api, server, monkeypatch, capsys):
    other, _, baseline = setup(api, server, monkeypatch, ["s"])
    other["names"] = deepcopy(server.person["names"])
    assert cli.main(["add-label", "--contact", "Jane Example", "--label", "New"]) == 0
    assert server.writes == baseline
    assert "No contacts selected; no changes made." in capsys.readouterr().out


def test_cancel_after_previous_resolution_stops_entire_file(api, server, monkeypatch, tmp_path):
    other, _, baseline = setup(api, server, monkeypatch, ["q"])
    other["names"] = deepcopy(server.person["names"])
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nJane Example\nc456\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "New", "--apply"]) == 0
    assert server.writes == baseline


def test_skip_option_does_not_leak_to_other_selectors(monkeypatch, capsys):
    from contacts_cli.selection import select_numbers

    replies = iter(["s", "2"])
    monkeypatch.setattr("builtins.input", lambda: next(replies))
    assert select_numbers([1, 2]) == [2]
    output = capsys.readouterr().out
    assert "Skip this identifier" not in output
    assert "Enter all, numbers or ranges" in output
