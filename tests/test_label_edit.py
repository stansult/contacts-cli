"""Additive label edits use the real client with independently checked HTTP fixtures."""

from copy import deepcopy

import httplib2
import pytest

from contacts_cli import cli, contact_create
from contacts_cli.errors import WriteUnverified
from contacts_cli.label_edit import LABEL_FIELDS, add_membership

from .test_fixture_contract import fetch

ARGS = ["add-label", "--contact", "c123"]


def group(server, name):
    return fetch(server, "/v1/contactGroups", "POST", {"contactGroup": {"name": name}})[1][
        "resourceName"
    ]


def test_membership_fixture_contract(server):
    resource = group(server, "One")
    original = deepcopy(server.person)
    body = {"resourceNamesToAdd": ["people/c123"]}
    path = f"/v1/{resource}/members:modify"
    assert fetch(server, path, "POST", body) == (200, {})
    assert fetch(server, path, "POST", body) == (200, {})
    expected = {"contactGroupMembership": {"contactGroupResourceName": resource}}
    assert server.person["memberships"].count(expected) == 1
    for key, value in original.items():
        if key != "memberships":
            assert server.person[key] == value
    _, saved = fetch(
        server,
        "/v1/people:batchGet?resourceNames=people/c123&personFields=memberships&sources=READ_SOURCE_TYPE_CONTACT",
    )
    assert expected in saved["responses"][0]["person"]["memberships"]
    assert fetch(server, path, "POST", {"resourceNamesToAdd": ["people/c999"]}) == (
        200,
        {"notFoundResourceNames": ["people/c999"]},
    )


@pytest.mark.parametrize("command", ["add-label", "add-labels"])
@pytest.mark.parametrize("apply", [False, True])
def test_preview_apply_and_noop(command, apply, api, server, monkeypatch, capsys):
    first, second = group(server, "Existing"), group(server, "Recruiter")
    server.person["memberships"] = [{"contactGroupMembership": {"contactGroupResourceName": first}}]
    original = deepcopy(server.person)
    baseline = server.writes
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    args = [
        command,
        "--contact",
        "c123",
        "--label",
        "Existing",
        "--label",
        "Recruiter",
        "--label",
        "New",
        "--label",
        "New",
    ]
    assert cli.main(args + (["--apply"] if apply else [])) == 0
    output = capsys.readouterr().out
    assert "Already applied: 1 label" in output
    assert "Labels to create: 1 label" in output
    assert "2 labels" in output
    if not apply:
        assert server.writes == baseline and server.person == original
        return
    assert len(server.person["memberships"]) == 3
    for key, value in original.items():
        if key != "memberships":
            assert server.person[key] == value
    assert second in str(server.person["memberships"])
    writes = server.writes
    assert cli.main(args + ["--apply"]) == 0
    assert "already applied; no changes made" in capsys.readouterr().out
    assert server.writes == writes
    assert not any("gmail" in call[1] for call in server.calls)


@pytest.mark.parametrize("answer", [True, False])
def test_confirmation_before_label_creation(answer, api, server, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)

    def confirm(question):
        assert server.writes == 0
        assert "create the missing labels" in question
        return answer

    monkeypatch.setattr(cli, "confirm_apply", confirm)
    assert cli.main(ARGS + ["--label", "New"]) == 0
    assert server.writes == (2 if answer else 0)


def test_case_choice_updates_applied_label(api, server, monkeypatch, capsys):
    resource = group(server, "Recruiter")
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    monkeypatch.setattr(contact_create, "choose_label", lambda *a: "Recruiter")
    assert cli.main(ARGS + ["--label", "recruiter", "--apply"]) == 0
    assert resource in str(server.person["memberships"])
    assert "Applied and verified label: Recruiter" in capsys.readouterr().out
    assert len(server.groups) == 1


def test_case_choice_cancel_and_noninteractive(api, server, monkeypatch, capsys):
    group(server, "Recruiter")
    baseline = server.writes
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(ARGS + ["--label", "recruiter", "--apply"]) == 1

    def cancel(*args):
        raise contact_create.LabelChoiceCancelled

    monkeypatch.setattr(contact_create, "choose_label", cancel)
    assert cli.main(ARGS + ["--label", "recruiter"]) == 0
    assert server.writes == baseline
    assert "Cancelled" in capsys.readouterr().out


@pytest.mark.parametrize("retain", ["old", "new"])
def test_readback_checks_added_and_existing_labels(api, server, monkeypatch, retain):
    old, new = group(server, "Old"), group(server, "New")
    server.person["memberships"] = [{"contactGroupMembership": {"contactGroupResourceName": old}}]
    person = api.get_contact("people/c123", LABEL_FIELDS)
    original = api.get_contact

    def lose(resource, fields):
        saved = original(resource, fields)
        if any(call[1].endswith("/members:modify") for call in server.calls):
            saved["memberships"] = [
                {
                    "contactGroupMembership": {
                        "contactGroupResourceName": new if retain == "new" else old
                    }
                }
            ]
        return saved

    monkeypatch.setattr(api, "get_contact", lose)
    with pytest.raises(WriteUnverified, match="existing label is missing"):
        add_membership(api, person, new)


@pytest.mark.parametrize("status,code", [(429, 1), (503, 3)])
def test_partial_failure_stops_without_retry(status, code, api, server, monkeypatch, capsys):
    first = group(server, "One")
    before = deepcopy(server.person["memberships"])
    second = group(server, "Two")
    group(server, "Three")
    original = server.request
    attempts = []

    def fail(uri, method="GET", *args, **kwargs):
        if method == "POST" and second + "/members:modify" in uri:
            attempts.append(uri)
            return httplib2.Response({"status": status}), b'{"error":{"message":"failure"}}'
        return original(uri, method, *args, **kwargs)

    monkeypatch.setattr(server, "request", fail)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert (
        cli.main(ARGS + ["--label", "One", "--label", "Two", "--label", "Three", "--apply"]) == code
    )
    assert len(attempts) == 1
    assert "Label additions verified: 1 of 3" in capsys.readouterr().out
    assert server.person["memberships"] == before + [
        {"contactGroupMembership": {"contactGroupResourceName": first}}
    ]


def test_invalid_label_before_auth(monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("authorization"))
    assert cli.main(ARGS + ["--label", " "]) == 1
