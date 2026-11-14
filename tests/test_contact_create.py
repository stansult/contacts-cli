"""Creation contract, preview safety, sequential writes and independent verification."""

import json
from copy import deepcopy
from datetime import UTC

import pytest

from contacts_cli import cli
from contacts_cli.contact_create import create_contact, verify_created
from contacts_cli.errors import SyncError, WriteUnverified

from .fake_google import FIXTURES
from .test_fixture_contract import fetch


def test_group_fixture_contract(server):
    for name in ("One", "Two"):
        status, result = fetch(
            server, "/v1/contactGroups", "POST", {"contactGroup": {"name": name}}
        )
        assert status == 200
        _, saved = fetch(server, "/v1/" + result["resourceName"])
        assert saved["name"] == name and saved["groupType"] == "USER_CONTACT_GROUP"
    _, first = fetch(server, "/v1/contactGroups")
    assert len(first["contactGroups"]) == 1 and first["nextPageToken"] == "1"
    _, second = fetch(server, "/v1/contactGroups?pageToken=1")
    assert second["contactGroups"][0]["name"] == "Two"
    assert "nextPageToken" not in second
    status, _ = fetch(server, "/v1/contactGroups", "POST", {"contactGroup": {"name": "One"}})
    assert status == 409 and len(server.groups) == 2


@pytest.mark.parametrize("command", ["add-contact", "add-contacts"])
@pytest.mark.parametrize("apply", [False, True])
def test_preview_and_apply(command, apply, api, server, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for name in ("Other", "Recruiter"):
        fetch(server, "/v1/contactGroups", "POST", {"contactGroup": {"name": name}})
    original_writes = server.writes
    person = json.loads((FIXTURES / "new-contact.json").read_text())
    file = tmp_path / "contacts.json"
    file.write_text(json.dumps([person, {"names": [{"unstructuredName": "Alex"}]}]))
    args = [
        command,
        "--file",
        str(file),
        "--label",
        "Recruiter",
        "--label",
        "New",
        "--label",
        "New",
    ]
    assert cli.main(args + (["--apply"] if apply else [])) == 0
    output = capsys.readouterr().out
    assert "Labels to create: 1 label" in output
    assert ("Creating contacts: 2 contacts" if apply else "Proposed contacts: 2 contacts") in output
    for field in (
        "Name:",
        "Email:",
        "Phone:",
        "Company:",
        "Address:",
        "Website:",
        "Custom field:",
        "Notes:",
        "Birthday:",
        "Event:",
        "Nickname:",
    ):
        assert field in output
    if apply:
        assert len(server.created) == 2 and len(server.groups) == 3
        saved = server.created["people/c456"]
        for field in person:
            assert (saved[field][:-1] if field == "userDefined" else saved[field]) == person[field]
        assert len(saved["memberships"]) == 2
        assert "Created and verified 2 contacts" in output
        assert "https://contacts.google.com/person/c457" in output
    else:
        assert not server.created and server.writes == original_writes
        assert "Preview only" in output
    assert not any("gmail" in call[1] for call in server.calls)


@pytest.mark.parametrize("answer", [True, False])
def test_confirmation_controls_all_writes(answer, api, server, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    questions = []

    def confirm(question):
        questions.append(question)
        assert server.writes == 0
        return answer

    monkeypatch.setattr(cli, "confirm_apply", confirm)
    assert cli.main(["add-contact", "--name", "Jane", "--label", "New"]) == 0
    assert len(questions) == 1 and "1 new label" in questions[0]
    assert server.writes == (2 if answer else 0)


@pytest.mark.parametrize("status,code", [(400, 1), (503, 3)])
def test_failed_create_stops_without_retry(
    status, code, api, server, monkeypatch, capsys, tmp_path
):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    file = tmp_path / "contacts.json"
    file.write_text(json.dumps([{"emailAddresses": [{"value": "a@example.com"}]}] * 3))
    original = server.request

    def fail_second(uri, *args, **kwargs):
        if len(server.created) == 1:
            server.create_status = status
        return original(uri, *args, **kwargs)

    monkeypatch.setattr(server, "request", fail_second)
    assert cli.main(["add-contact", "--file", str(file), "--apply"]) == code
    output = capsys.readouterr()
    assert "1 created; 1 verified; 1 not attempted" in output.out
    assert (
        "Contact #2 was not created."
        if status == 400
        else "Contact #2: creation outcome is unknown."
    ) in output.out
    assert "Created contact: https://contacts.google.com/person/c457" not in output.out
    assert len(server.created) == 1
    assert sum(call[1].endswith(":createContact") for call in server.calls) == 2


def test_readback_loss_is_unverified(api, server, monkeypatch, capsys):
    original = api.get_contact

    def lose(resource, fields):
        assert "Created contact: https://contacts.google.com/person/c456" in capsys.readouterr().out
        saved = original(resource, fields)
        saved.pop("emailAddresses", None)
        return saved

    monkeypatch.setattr(api, "get_contact", lose)
    with pytest.raises(WriteUnverified, match="Email differs from the input"):
        create_contact(api, {"emailAddresses": [{"value": "a@example.com"}]})
    assert len(server.created) == 1


def test_verification_allows_generated_fields_but_preserves_multiplicity(api, server):
    body = {
        "names": [{"unstructuredName": "Jane Doe"}],
        "userDefined": [{"key": "ID", "value": "1"}] * 2,
    }
    create_contact(api, body)
    saved = deepcopy(server.created["people/c456"])
    saved["names"] = [{"givenName": "Jane", "familyName": "Doe", "displayName": "Jane Doe"}]
    verify_created(body, saved)
    saved["userDefined"].pop(0)
    with pytest.raises(SyncError, match="Custom field"):
        verify_created(body, saved)


@pytest.mark.parametrize("status,code", [(409, 1), (503, 3)])
def test_label_failure_prevents_contacts(status, code, api, server, monkeypatch, capsys):
    import httplib2

    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    original = server.request
    writes = []

    def fail_label(uri, method="GET", *args, **kwargs):
        if method == "POST" and "/contactGroups" in uri:
            writes.append(uri)
            return httplib2.Response({"status": status}), b'{"error":{"message":"failure"}}'
        return original(uri, method, *args, **kwargs)

    monkeypatch.setattr(server, "request", fail_label)
    assert cli.main(["add-contact", "--name", "Jane", "--label", "New", "--apply"]) == code
    assert len(writes) == 1 and not server.created
    assert "0 created; 0 verified; 1 not attempted" in capsys.readouterr().out


def test_interrupt_reports_completed_and_remaining(api, server, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    original = api.write

    def interrupt(request, **kwargs):
        if server.created:
            raise KeyboardInterrupt
        return original(request, **kwargs)

    monkeypatch.setattr(api, "write", interrupt)
    file = tmp_path / "contacts.json"
    file.write_text(json.dumps([{"emailAddresses": [{"value": "a@example.com"}]}] * 3))
    assert cli.main(["add-contact", "--file", str(file), "--apply"]) == 130
    output = capsys.readouterr()
    assert "1 created; 1 verified; 1 not attempted" in output.out
    assert "no contact changes made" not in output.err
    assert len(server.created) == 1


@pytest.mark.parametrize("field", ["nicknames", "emailAddresses"])
def test_single_created_mismatch_is_clear(field, api, server, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    original = api.get_contact

    def changed(resource, fields):
        saved = original(resource, fields)
        saved.pop(field)
        return saved

    monkeypatch.setattr(api, "get_contact", changed)
    file = tmp_path / "contacts.json"
    file.write_text((FIXTURES / "new-contact.json").read_text())
    assert cli.main(["add-contact", "--file", str(file), "--apply"]) == 3
    output = capsys.readouterr()
    assert "Created contact: https://contacts.google.com/person/c456" in output.out
    assert "Contact #1 was created, but verification failed." in output.out
    assert "Requested:" in output.out and "Saved: Not present" in output.out
    assert "Stopped:" not in output.out and "0 not attempted" not in output.out
    assert "Unverified creation" not in output.err and not output.err


def test_readable_preview_preserves_values():
    from contacts_cli.contact_create import contact_preview

    preview = contact_preview(json.loads((FIXTURES / "new-contact.json").read_text()))
    assert "Name: First name: Jane; Last name: Doe" in preview
    assert "Birthday: February 29" in preview
    assert "Event: May 1 2020 — anniversary" in preview
    assert "Current: yes" in preview
    assert "Format: Plain text" in preview
    assert "Nickname: J" in preview
    assert "Nickname: J — Default" not in preview
    assert "Pipeline ID: P-001" in preview and "Pipeline ID: P-002" in preview
    assert all(key not in preview for key in ("givenName", "contentType", "countryCode", '"month"'))


@pytest.mark.parametrize("stage", ["write", "readback"])
def test_single_interrupt_distinguishes_creation(stage, api, server, monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(api, "write" if stage == "write" else "get_contact", interrupted)
    assert cli.main(["add-contact", "--name", "Jane", "--apply"]) == 130
    output = capsys.readouterr()
    if stage == "write":
        assert "creation outcome is unknown" in output.out
        assert "Created contact:" not in output.out
    else:
        assert "was created, but verification was interrupted" in output.out
        assert "Created contact:" in output.out
    assert not output.err


def test_label_readback_failure_reports_saved_label(api, server, monkeypatch, capsys):
    import httplib2

    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    original = server.request

    def missing(uri, method="GET", *args, **kwargs):
        if method == "GET" and "/contactGroups/" in uri:
            return httplib2.Response({"status": 404}), b'{"error":{"message":"missing"}}'
        return original(uri, method, *args, **kwargs)

    monkeypatch.setattr(server, "request", missing)
    assert cli.main(["add-contact", "--name", "Jane", "--label", "New", "--apply"]) == 3
    output = capsys.readouterr().out
    assert "Label 'New' was created, but verification failed" in output
    assert "New labels created: 1" in output
    assert "1 not attempted" in output
    assert not server.created


@pytest.mark.parametrize("saved_entry", [{"value": "J"}, {"value": "J", "type": "DEFAULT"}])
def test_default_nickname_type_may_be_omitted(api, server, monkeypatch, saved_entry):
    original = api.get_contact
    body = {"nicknames": [{"value": "J", "type": "DEFAULT"}]}

    def normalized(resource, fields):
        saved = original(resource, fields)
        saved["nicknames"] = [deepcopy(saved_entry)]
        return saved

    monkeypatch.setattr(api, "get_contact", normalized)
    assert create_contact(api, body).endswith("/c456")
    assert body["nicknames"] == [{"value": "J", "type": "DEFAULT"}]
    assert server.created["people/c456"]["nicknames"] == body["nicknames"]


@pytest.mark.parametrize(
    "entries", [[], [{"value": "Other"}], [{"value": "J", "type": "MAIDEN_NAME"}]]
)
def test_nickname_normalization_still_rejects_real_differences(api, server, entries):
    body = {"nicknames": [{"value": "J", "type": "DEFAULT"}]}
    create_contact(api, body)
    saved = deepcopy(server.created["people/c456"])
    saved["nicknames"] = entries
    with pytest.raises(SyncError, match="Nickname differs"):
        verify_created(body, saved)


@pytest.mark.parametrize("requested", ["recruiter", "Recruiter", "Unrelated"])
def test_label_case_notice_preserves_exact_matching(api, server, capsys, requested):
    from contacts_cli.contact_create import resolve_labels

    for name in ("Recruiter", "RECRUITER"):
        fetch(server, "/v1/contactGroups", "POST", {"contactGroup": {"name": name}})
    writes = server.writes
    if requested == "recruiter":
        with pytest.raises(SyncError, match="Use an exact existing spelling"):
            resolve_labels(api, [requested, requested])
    else:
        existing, missing = resolve_labels(api, [requested, requested])
        if requested == "Recruiter":
            assert existing and not missing
        else:
            assert missing == [requested] and not existing
    assert server.writes == writes


def test_deleted_label_is_not_a_case_suggestion(api, server, capsys):
    from contacts_cli.contact_create import resolve_labels

    server.groups["contactGroups/deleted"] = {
        "resourceName": "contactGroups/deleted",
        "name": "Recruiter",
        "groupType": "USER_CONTACT_GROUP",
        "metadata": {"deleted": True},
    }
    assert resolve_labels(api, ["recruiter"]) == ({}, ["recruiter"])
    assert "No exact match" not in capsys.readouterr().out


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("answer", ["", "2", "3"])
def test_interactive_label_choice(api, server, monkeypatch, capsys, apply, answer):
    from contacts_cli import contact_create

    _, group = fetch(server, "/v1/contactGroups", "POST", {"contactGroup": {"name": "Recruiter"}})
    baseline = server.writes
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (contact_create.sys.stdin, contact_create.sys.stdout, contact_create.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    answers = iter(["invalid", answer])
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    monkeypatch.setattr(cli, "confirm_apply", lambda *a: True)
    args = ["add-contact", "--name", "Jane", "--label", "recruiter"]
    assert cli.main(args + (["--apply"] if apply else [])) == 0
    output = capsys.readouterr()
    assert "Use existing 'Recruiter'" in output.out
    assert "Create new 'recruiter'" in output.out
    assert "Enter a number" in output.err
    if answer == "3":
        assert "Cancelled; no changes made" in output.out
        assert server.writes == baseline and not server.created
    else:
        saved = server.created["people/c456"]
        resource = saved["memberships"][0]["contactGroupMembership"]["contactGroupResourceName"]
        selected = "Recruiter" if answer == "" else "recruiter"
        assert f"Labels for every contact: {selected}" in output.out
        assert server.groups[resource]["name"] == selected
        assert len(server.groups) == (1 if answer == "" else 2)
        if answer == "":
            assert resource == group["resourceName"]


@pytest.mark.parametrize("apply", [False, True])
def test_noninteractive_case_collision_stops_before_writes(api, server, monkeypatch, capsys, apply):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    fetch(server, "/v1/contactGroups", "POST", {"contactGroup": {"name": "Recruiter"}})
    baseline = server.writes
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("prompt"))
    args = ["add-contact", "--name", "Jane", "--label", "recruiter"]
    assert cli.main(args + (["--apply"] if apply else [])) == 1
    assert "'Recruiter'" in capsys.readouterr().err
    assert server.writes == baseline


def test_multiple_label_choices_and_eof(monkeypatch, capsys):
    from contacts_cli import contact_create

    for stream in (contact_create.sys.stdin, contact_create.sys.stdout, contact_create.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "2")
    assert contact_create.choose_label("recruiter", ["Recruiter", "RECRUITER"]) == "RECRUITER"
    assert "2. Use existing 'RECRUITER'" in capsys.readouterr().out

    def eof():
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    with pytest.raises(contact_create.LabelChoiceCancelled):
        contact_create.choose_label("recruiter", ["Recruiter"])


def test_created_marker_preserves_custom_fields(api, server, monkeypatch):
    from datetime import datetime

    from contacts_cli import contact_create
    from contacts_cli.duplicate import creation_marker, duplicate_marker

    now = datetime(2026, 11, 14, 1, 30, tzinfo=UTC)
    monkeypatch.setattr(
        contact_create, "creation_marker", lambda label: creation_marker(label, now)
    )

    body = {
        "names": [{"givenName": "Jane"}],
        "userDefined": [{"key": "Created", "value": "Imported history"}],
    }
    original = deepcopy(body)
    create_contact(api, body)
    fields = server.created["people/c456"]["userDefined"]
    assert fields[:-1] == original["userDefined"]
    assert fields[-1]["key"] == "Created"
    assert fields[-1]["value"] == duplicate_marker(now)["value"]
    assert body == original


def test_created_marker_is_verified(api, monkeypatch):
    original = api.get_contact

    def missing_marker(resource, fields):
        saved = original(resource, fields)
        saved["userDefined"] = [
            entry for entry in saved.get("userDefined", []) if entry["key"] != "Created"
        ]
        return saved

    monkeypatch.setattr(api, "get_contact", missing_marker)
    with pytest.raises(WriteUnverified, match="Custom field differs"):
        create_contact(api, {"names": [{"givenName": "Jane"}]})
