"""Symmetric email editing, collision policy, and preservation through real client calls."""

from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.address_inputs import edit_inputs
from contacts_cli.core import email_update_body
from contacts_cli.email_edit import make_edit_plan, verify_edit
from contacts_cli.errors import SyncError


def args(action, *extra):
    return [f"{action}-email", "--contact", "people/c123", *extra]


@pytest.fixture
def connected(api, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    return api


def test_fixture_replaces_empty_email_list_independently(server):
    from .test_fixture_contract import fetch

    before = deepcopy(server.person)
    status, saved = fetch(
        server,
        "/v1/people/c123:updateContact?updatePersonFields=emailAddresses",
        "PATCH",
        {"metadata": {"sources": [{"etag": "source-v1"}]}, "emailAddresses": []},
    )
    assert status == 200 and saved["emailAddresses"] == []
    assert server.person["emailAddresses"] == []
    assert saved["names"] == before["names"]


def test_add_files_labels_and_rerun(connected, server, tmp_path, capsys):
    path = tmp_path / "add.txt"
    path.write_text(
        "# comment\nNEW@example.com — Alerts\nnew@example.com — alerts\n", encoding="utf-8"
    )
    before = deepcopy(server.person)
    command = args("add", "--add-file", str(path), "--add", "other@example.com", "--apply")
    assert cli.main(command) == 0
    assert server.person["emailAddresses"][:2] == before["emailAddresses"]
    assert {"value": "NEW@example.com", "type": "Alerts"} in server.person["emailAddresses"]
    assert cli.main(command) == 0
    assert server.writes == 1
    assert not any("gmail" in call[1] for call in server.calls)
    assert "No changes selected" in capsys.readouterr().out


@pytest.mark.parametrize("apply", [False, True])
def test_remove_all_duplicates_and_noop(connected, server, capsys, apply):
    server.person["emailAddresses"] = [
        {"value": "same@example.com", "type": "Work"},
        {"value": "SAME@example.com", "type": "Billing"},
    ]
    before = deepcopy(server.person)
    command = args(
        "remove", "--remove", "same@example.com — ignored", "--remove", "absent@example.com"
    )
    assert cli.main(command + (["--apply"] if apply else [])) == 0
    text = capsys.readouterr().out
    assert "Remaining email entries: 0" in text
    assert ("Removing" if apply else "Proposed removals") + ": 2 entries (1 address)" in text
    assert (
        "  1. same@example.com — Work\n  2. SAME@example.com — Billing [duplicate of #1]\n" in text
    )
    assert "absent@example.com" in text
    assert "entry(s)" not in text
    if apply:
        assert server.person["emailAddresses"] == []
        assert cli.main(command + ["--apply"]) == 0
        assert server.writes == 1
    else:
        assert server.person == before and server.writes == 0


@pytest.mark.parametrize("label", ["", "New"])
def test_apply_keeps_conflicts_unless_replacement_authorized(connected, server, label):
    server.person["emailAddresses"] = [
        {"value": "same@example.com", "type": "Work"},
        {"value": "SAME@example.com", "type": "Billing", "metadata": {"sourcePrimary": True}},
    ]
    before = deepcopy(server.person["emailAddresses"])
    value = "same@example.com" + (" — " + label if label else "")
    command = args("add", "--add", value, "--apply")
    assert cli.main(command) == 0
    assert server.writes == 0 and server.person["emailAddresses"] == before
    assert cli.main(command + ["--replace-existing"]) == 0
    saved = server.person["emailAddresses"]
    assert len(saved) == 1 and saved[0]["value"] == "SAME@example.com"
    assert saved[0].get("type", "") == label
    assert saved[0]["metadata"]["sourcePrimary"] is True


def test_suppression_precedes_input_conflicts(connected, server):
    server.person["names"] = [{"displayName": "Shop"}]
    assert (
        cli.main(
            args("add", "--add", "new@example.com", "--add", "NEW@example.com — Shop", "--apply")
        )
        == 0
    )
    assert next(e for e in server.person["emailAddresses"] if e["value"] == "new@example.com") == {
        "value": "new@example.com"
    }


def test_conflicting_input_stops_before_any_prompt_or_write(connected, server, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("prompt"))
    assert (
        cli.main(
            args(
                "add",
                "--add",
                "new@example.com — Work",
                "--add",
                "new@example.com — Billing",
                "--apply",
            )
        )
        == 1
    )
    assert server.writes == 0
    assert "--add #1 and --add #2" in capsys.readouterr().err


@pytest.mark.parametrize("choice,changes", [("y", True), ("n", False), ("a", True), ("s", False)])
def test_interactive_conflicts_then_final_confirmation(
    connected, server, monkeypatch, choice, changes
):
    server.person["emailAddresses"] = [
        {"value": "one@example.com", "type": "Old"},
        {"value": "two@example.com", "type": "Old"},
    ]
    for stream in (cli.sys.stdin, cli.sys.stdout, cli.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    answers = iter(
        ([choice] if choice in {"a", "s"} else [choice, choice]) + (["y"] if changes else [])
    )
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    assert cli.main(args("add", "--add", "one@example.com", "--add", "two@example.com")) == 0
    assert server.writes == int(changes)
    assert all(
        e.get("type", "") == ("" if changes else "Old") for e in server.person["emailAddresses"]
    )
    assert next(answers, None) is None


def test_replacement_preview_and_final_decline_never_write(connected, server, monkeypatch):
    before = deepcopy(server.person)
    for stream in (cli.sys.stdin, cli.sys.stdout, cli.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "n")
    assert cli.main(args("add", "--add", "existing@example.com", "--replace-existing")) == 0
    assert server.person == before and server.writes == 0


@pytest.mark.parametrize("action", ["add", "remove"])
def test_inputs_required_and_invalid_before_connect(action, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("authorization"))
    with pytest.raises(SystemExit):
        cli.main(args(action))
    assert cli.main(args(action, f"--{action}", "not-an-email")) == 1


@pytest.mark.parametrize("action", ["add", "remove"])
def test_concurrent_edit_blocks_write(connected, server, action):
    server.concurrent_edit = True
    address = "new@example.com" if action == "add" else "existing@example.com"
    assert cli.main(args(action, f"--{action}", address, "--apply")) == 1
    assert server.writes == 0


@pytest.mark.parametrize("failure", ["lose_additions", "fail_verification"])
def test_removal_verification_failures(connected, server, failure):
    setattr(server, failure, True)
    assert cli.main(args("remove", "--remove", "existing@example.com", "--apply")) == 3
    assert server.writes == 1


def test_primary_reassignment_allowed_but_unrelated_damage_rejected(server):
    server.person["emailAddresses"] = [
        {"value": "one@example.com", "metadata": {"sourcePrimary": True}},
        {"value": "two@example.com"},
    ]
    plan = make_edit_plan(
        server.person, edit_inputs(["one@example.com"], [], "--remove"), remove=True
    )
    saved = deepcopy(server.person)
    saved["emailAddresses"] = deepcopy(plan.emails)
    saved["emailAddresses"][0]["metadata"] = {"sourcePrimary": True}
    verify_edit(plan, saved)
    saved["names"] = [{"displayName": "Changed"}]
    with pytest.raises(SyncError, match="names"):
        verify_edit(plan, saved)
    assert email_update_body(plan.person, plan.emails)["emailAddresses"] == plan.emails


@pytest.mark.parametrize(
    "old,new,replace,expected",
    [
        ("", "Work", False, "Work"),
        ("Work", "work", False, "Work"),
        ("Work", "Billing", False, "Work"),
        ("Work", "Billing", True, "Billing"),
        ("Work", "", True, ""),
    ],
)
def test_single_entry_label_policy(connected, server, old, new, replace, expected):
    server.person["emailAddresses"] = [
        {"value": "person@example.com", **({"type": old} if old else {})}
    ]
    value = "person@example.com" + (" — " + new if new else "")
    command = args("add", "--add", value, "--apply") + (["--replace-existing"] if replace else [])
    assert cli.main(command) == 0
    assert server.person["emailAddresses"][0].get("type", "") == expected


def test_noninteractive_replacement_preview_never_writes(connected, server):
    before = deepcopy(server.person)
    assert (
        cli.main(
            args(
                "add",
                "--add",
                "existing@example.com",
                "--add",
                "new@example.com",
                "--replace-existing",
            )
        )
        == 0
    )
    assert server.person == before and server.writes == 0


def test_remove_file_combines_and_ignores_conflicting_labels(connected, server, tmp_path):
    path = tmp_path / "remove.txt"
    path.write_text("existing@example.com — One\nexisting@example.com — Two\n", encoding="utf-8")
    assert (
        cli.main(
            args("remove", "--remove-file", str(path), "--remove", "missing@example.com", "--apply")
        )
        == 0
    )
    assert all(
        e["value"].lower() != "existing@example.com" for e in server.person["emailAddresses"]
    )
    assert server.writes == 1


def test_lost_retained_primary_rejected(server):
    server.person["emailAddresses"] = [
        {"value": "one@example.com", "metadata": {"sourcePrimary": True}}
    ]
    plan = make_edit_plan(server.person, edit_inputs(["two@example.com"], [], "--add"))
    saved = deepcopy(server.person)
    saved["emailAddresses"] = deepcopy(plan.emails)
    saved["emailAddresses"][0].pop("metadata")
    with pytest.raises(SyncError, match="primary"):
        verify_edit(plan, saved)


def test_numbered_removal_preview_alignment_and_unlabeled_entries(connected, server, capsys):
    server.person["emailAddresses"] = [{"value": f"person{i:02}@example.com"} for i in range(1, 11)]
    command = args("remove")
    for entry in server.person["emailAddresses"]:
        command.extend(["--remove", entry["value"]])
    assert cli.main(command) == 0
    text = capsys.readouterr().out
    assert "Proposed removals: 10 entries (10 addresses)" in text
    assert "   1. person01@example.com\n" in text
    assert "  10. person10@example.com\n" in text
    assert "(no label)" not in text
    assert server.writes == 0


def test_removal_duplicates_reference_first_row_per_address(connected, server, capsys):
    server.person["emailAddresses"] = [
        {"value": "a@example.com", "type": "Work"},
        {"value": "A@example.com"},
        {"value": "a@example.com", "type": "Other"},
        {"value": "b@example.com"},
        {"value": "B@example.com", "type": "Home"},
        {"value": "c@example.com"},
    ]
    assert (
        cli.main(
            args(
                "remove",
                "--remove",
                "a@example.com",
                "--remove",
                "b@example.com",
                "--remove",
                "c@example.com",
            )
        )
        == 0
    )
    text = capsys.readouterr().out
    assert "  1. a@example.com — Work\n" in text
    assert "  2. A@example.com [duplicate of #1]\n" in text
    assert "  3. a@example.com — Other [duplicate of #1]\n" in text
    assert "  4. b@example.com\n" in text
    assert "  5. B@example.com — Home [duplicate of #4]\n" in text
    assert "  6. c@example.com\n" in text
    assert text.count("[duplicate of #") == 3
    assert server.writes == 0


@pytest.mark.parametrize("apply", [False, True])
def test_mixed_edit_lists_and_action_headings(connected, server, capsys, apply):
    server.person["emailAddresses"] = [{"value": "old@example.com", "type": "Old"}]
    command = args(
        "add", "--add", "old@example.com — New", "--add", "new@example.com", "--replace-existing"
    )
    assert cli.main(command + (["--apply"] if apply else [])) == 0
    text = capsys.readouterr().out
    assert (
        "Adding" if apply else "Proposed additions"
    ) + ": 1 entry\n  1. new@example.com\n" in text
    assert ("Updating" if apply else "Proposed updates") + ": 1 change" in text
    assert "Old" in text and "New" in text
    assert "Add new@example.com" not in text
    assert "(no label)" not in text
    assert server.writes == int(apply)


def test_conflicts_use_local_numbers_after_consolidation(connected, server, monkeypatch, capsys):
    server.person["emailAddresses"] = [
        {"value": "untouched@example.com"},
        {"value": "a@example.com", "type": "First"},
        {"value": "A@example.com", "type": "Second"},
        {"value": "b@example.com", "type": "Third"},
    ]
    for stream in (cli.sys.stdin, cli.sys.stdout, cli.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    answers = iter(["y", "n", "n"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    assert cli.main(args("add", "--add", "a@example.com", "--add", "b@example.com")) == 0
    text = capsys.readouterr().out
    assert (
        "Existing matches: 2 entries\n  1. a@example.com — First\n"
        "  2. A@example.com — Second [duplicate of #1]" in text
    )
    assert "Existing matches: 1 entry\n  1. b@example.com — Third" in text
    assert "Skipped conflicts: 1 conflict\n  1. b@example.com" in text
    assert server.writes == 0


def test_removal_not_found_and_local_numbers(connected, server, capsys):
    server.person["emailAddresses"] = [
        {"value": "keep@example.com"},
        {"value": "remove@example.com"},
    ]
    assert (
        cli.main(
            args("remove", "--remove", "remove@example.com", "--remove", "missing@example.com")
        )
        == 0
    )
    text = capsys.readouterr().out
    assert "Proposed removals: 1 entry (1 address)\n  1. remove@example.com" in text
    assert "Not found: 1 address\n  1. missing@example.com" in text


@pytest.mark.parametrize("command", ["list-email", "list-emails"])
@pytest.mark.parametrize("empty", [False, True])
def test_list_email_read_only(connected, server, monkeypatch, capsys, command, empty):
    server.person["emailAddresses"] = (
        []
        if empty
        else [
            {"value": "same@example.com", "type": "Work"},
            {"value": "SAME@example.com"},
        ]
    )
    before = deepcopy(server.person)
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("read-only command prompted"))
    assert cli.main([command, "--contact", "people/c123"]) == 0
    output = capsys.readouterr().out
    assert f"Email addresses: {0 if empty else 2} entries" in output
    if not empty:
        assert "  1. same@example.com — Work\n  2. SAME@example.com [duplicate of #1]\n" in output
    assert server.person == before and server.writes == 0
    assert len(server.calls) == 1
    assert not any("gmail" in call[1] for call in server.calls)


@pytest.mark.parametrize("action", ["add", "remove"])
def test_plural_edit_alias_and_no_existing_list(connected, server, capsys, action):
    server.person["emailAddresses"] = [
        {"value": "keep@example.com"},
        {"value": "target@example.com"},
    ]
    address = "new@example.com" if action == "add" else "target@example.com"
    assert (
        cli.main(
            [f"{action}-emails", "--contact", "people/c123", f"--{action}", address, "--apply"]
        )
        == 0
    )
    text = capsys.readouterr().out
    assert "Existing email entries: 2\n" in text
    assert "keep@example.com" not in text
    assert "alias" not in text.lower()
    assert server.writes == 1
    values = {entry["value"] for entry in server.person["emailAddresses"]}
    assert (address in values) == (action == "add")


def test_list_input_and_help(monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("network"))
    assert cli.main(["list-email", "--contact", "invalid"]) == 1
    for extra in [[], ["--contact", "people/c123", "--apply"]]:
        with pytest.raises(SystemExit) as error:
            cli.main(["list-emails", *extra])
        assert error.value.code == 2
    capsys.readouterr()
    for command in [[], ["add-emails"], ["remove-emails"], ["list-emails"]]:
        with pytest.raises(SystemExit) as error:
            cli.main([*command, "--help"])
        assert error.value.code == 0
        help_text = capsys.readouterr().out
        assert (command[0][:-1] if command else "list-email") in help_text
        assert all(
            alias not in help_text for alias in ["add-emails", "remove-emails", "list-emails"]
        )
