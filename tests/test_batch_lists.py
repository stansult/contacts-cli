"""Read-only field listings share batch resolution, numbering, and failure handling."""

from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.errors import SyncError

from .test_contact_resolution import setup

COMMANDS = ["list-email", "list-phone", "list-label"]


@pytest.mark.parametrize("command", COMMANDS)
def test_combined_inputs_read_once_and_never_write(
    command, api, server, monkeypatch, tmp_path, capsys
):
    _, _, baseline = setup(api, server, monkeypatch)
    path = tmp_path / "contacts.txt"
    path.write_text("\ufeff# targets\nc456\nc123\n")
    real = api.get_contact
    reads = []

    def read(resource, *args):
        reads.append(resource)
        return real(resource, *args)

    monkeypatch.setattr(api, "get_contact", read)
    monkeypatch.setattr(api, "write", lambda *a, **k: pytest.fail("write"))
    assert (
        cli.main(
            [command, "--contact", "c123", "--contact", "Jane Example", "--contact-file", str(path)]
        )
        == 0
    )
    assert reads == ["people/c123", "people/c456"]
    output = capsys.readouterr().out
    assert "Contact #1:" in output and "Contact #2:" in output
    assert "Contacts: 2 listed; 0 skipped; 0 failed; 0 not attempted." in output
    assert server.writes == baseline


@pytest.mark.parametrize("command", COMMANDS)
def test_missing_id_leaves_number_gap(command, api, server, monkeypatch, capsys):
    setup(api, server, monkeypatch)
    assert cli.main([command, "--contact", "c999", "--contact", "c123"]) == 0
    output = capsys.readouterr().out
    assert "Contact #2:" in output
    assert "1 listed; 1 skipped; 0 failed; 0 not attempted" in output


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("failure", [SyncError("connection failed"), KeyboardInterrupt()])
def test_failure_keeps_prior_results_and_stops(command, failure, api, server, monkeypatch, capsys):
    setup(api, server, monkeypatch)
    real = api.get_contact
    reads = []

    def read(resource, *args):
        reads.append(resource)
        if resource == "people/c456":
            raise failure
        return real(resource, *args)

    monkeypatch.setattr(api, "get_contact", read)
    expected = 130 if isinstance(failure, KeyboardInterrupt) else 1
    assert (
        cli.main([command, "--contact", "c123", "--contact", "c456", "--contact", "c789"])
        == expected
    )
    assert reads == ["people/c123", "people/c456"]
    output = capsys.readouterr().out
    assert "Listing incomplete" in output
    assert "1 listed; 0 skipped; 1 failed; 1 not attempted" in output


@pytest.mark.parametrize("command", COMMANDS)
def test_invalid_file_before_auth(command, monkeypatch, tmp_path):
    path = tmp_path / "contacts.txt"
    path.write_text("https://example.com/not-a-contact")
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("auth"))
    assert cli.main([command, "--contact", "c123", "--contact-file", str(path)]) == 1


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("answers,count", [(["all"], 2), (["2"], 1), (["s"], 0), (["q"], 0)])
def test_ambiguity_read_only_selection(command, answers, count, api, server, monkeypatch):
    other, _, baseline = setup(api, server, monkeypatch, answers)
    other["names"] = deepcopy(server.person["names"])
    real = api.get_contact
    reads = []

    def read(resource, *args):
        reads.append(resource)
        return real(resource, *args)

    monkeypatch.setattr(api, "get_contact", read)
    assert cli.main([command, "--contact", "Jane Example"]) == 0
    assert len(reads) == count
    assert server.writes == baseline


def test_label_pages_read_once_per_batch(api, server, monkeypatch, capsys):
    from .test_label_edit import group

    other, first, _ = setup(api, server, monkeypatch)
    second = group(server, "Second")
    server.person["memberships"] = [{"contactGroupMembership": {"contactGroupResourceName": first}}]
    other["memberships"] = [{"contactGroupMembership": {"contactGroupResourceName": second}}]
    baseline = server.writes
    assert cli.main(["list-label", "--contact", "c123", "--contact", "c456"]) == 0
    # Fixture intentionally pages one group at a time; both pages must be reused.
    calls = [
        query
        for method, path, query, _ in server.calls
        if method == "GET" and path == "/v1/contactGroups"
    ]
    assert len(calls) == 2
    assert {tuple(q.get("pageToken", [])) for q in calls} == {(), ("1",)}
    out = capsys.readouterr().out
    first_block, second_block = out.split("Contact #2:")
    assert "  1. Test" in first_block and "  1. Second" not in first_block
    assert "  1. Second" in second_block and "  1. Test" not in second_block
    assert server.writes == baseline


@pytest.mark.parametrize(
    "command,field,entry",
    [
        ("list-email", "emailAddresses", {"value": "same@example.com"}),
        ("list-phone", "phoneNumbers", {"value": "+12025550142"}),
    ],
)
def test_duplicate_numbers_are_local_to_contact(
    command, field, entry, api, server, monkeypatch, capsys
):
    other, _, _ = setup(api, server, monkeypatch)
    for person in (server.person, other):
        person[field] = [deepcopy(entry), deepcopy(entry)]
    assert cli.main([command, "--contact", "c123", "--contact", "c456"]) == 0
    out = capsys.readouterr().out
    assert out.count("[duplicate of #1]") == 2
    assert out.count("  1. " + entry["value"]) == 2
    assert out.count("  2. " + entry["value"]) == 2


@pytest.mark.parametrize(
    "command,field,heading",
    [
        ("list-email", "emailAddresses", "Email addresses: 0 entries"),
        ("list-phone", "phoneNumbers", "Phone numbers: 0 entries"),
        ("list-label", "memberships", "Labels: 0 labels"),
    ],
)
def test_empty_lists_and_single_contact_output(
    command, field, heading, api, server, monkeypatch, capsys
):
    setup(api, server, monkeypatch)
    server.person[field] = []
    assert cli.main([command, "--contact", "c123"]) == 0
    out = capsys.readouterr().out
    assert heading in out and "Contact: 'name: Jane Example' (c123)" in out
    assert "Contact #1:" not in out and "Contacts: 1 listed" not in out


@pytest.mark.parametrize("command", COMMANDS)
def test_no_apply_and_input_requirement(command, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("auth"))
    with pytest.raises(SystemExit) as error:
        cli.main([command, "--contact", "c123", "--apply"])
    assert error.value.code == 2
    if command != "list-label":
        assert cli.main([command]) == 1


@pytest.mark.parametrize("command", COMMANDS)
def test_redirected_ambiguity_does_not_choose(command, api, server, monkeypatch):
    other, _, baseline = setup(api, server, monkeypatch)
    other["names"] = deepcopy(server.person["names"])
    monkeypatch.setattr(api, "get_contact", lambda *a: pytest.fail("target read"))
    assert cli.main([command, "--contact", "Jane Example"]) == 1
    assert server.writes == baseline


@pytest.mark.parametrize("command", COMMANDS)
def test_eof_before_reads(command, api, server, monkeypatch):
    other, _, baseline = setup(api, server, monkeypatch, [])
    other["names"] = deepcopy(server.person["names"])

    def eof():
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    monkeypatch.setattr(api, "get_contact", lambda *a: pytest.fail("target read"))
    assert cli.main([command, "--contact", "Jane Example"]) == 0
    assert server.writes == baseline


@pytest.mark.parametrize(
    "command,field",
    [
        ("list-email", "emailAddresses"),
        ("list-phone", "phoneNumbers"),
        ("list-label", "memberships"),
    ],
)
def test_incomplete_contact_data_stops_without_misleading_empty_result(
    command, field, api, server, monkeypatch, capsys
):
    other, _, baseline = setup(api, server, monkeypatch)
    other[field] = "incomplete"
    assert cli.main([command, "--contact", "c123", "--contact", "c456", "--contact", "c789"]) == 1
    out = capsys.readouterr().out
    assert "Contact #1:" in out and "Contact #2:" not in out
    assert "Listing incomplete" in out
    assert "1 listed; 0 skipped; 1 failed; 1 not attempted" in out
    assert server.writes == baseline


@pytest.mark.parametrize("command", COMMANDS)
def test_empty_file_is_not_account_mode(command, monkeypatch, tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("# nothing\n")
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("authorization"))
    assert cli.main([command, "--contact-file", str(path)]) == 1


def test_label_lookup_failure_marks_incomplete(api, server, monkeypatch, capsys):
    setup(api, server, monkeypatch)
    from contacts_cli import batch_lists

    def fail(*a):
        raise SyncError("label lookup failed")

    monkeypatch.setattr(batch_lists, "contact_groups", fail)
    assert cli.main(["list-label", "--contact", "c123", "--contact", "c456"]) == 1
    out = capsys.readouterr().out
    assert "Listing incomplete" in out and "label lookup failed" in out
    assert "0 listed; 0 skipped; 1 failed; 1 not attempted" in out


@pytest.mark.parametrize("command", COMMANDS)
def test_help_describes_file_and_repeated_inputs(command, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main([command, "--help"])
    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "--contact-file" in output and "repeatable" in output
    assert "--apply" not in output


@pytest.mark.parametrize("command", COMMANDS)
def test_file_only_lists_contacts_not_account_labels(
    command, api, server, monkeypatch, tmp_path, capsys
):
    setup(api, server, monkeypatch)
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc456\n")
    monkeypatch.setattr(api, "write", lambda *a, **k: pytest.fail("write"))
    assert cli.main([command, "--contact-file", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Contact #1:" in out and "Contact #2:" in out
    assert "Contacts: 2 listed; 0 skipped; 0 failed; 0 not attempted." in out
