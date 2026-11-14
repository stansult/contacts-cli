"""Removal affects contact memberships, never the labels or other contact fields."""

from copy import deepcopy

import pytest

from contacts_cli import cli, contact_create
from contacts_cli.errors import SyncError, WriteUnverified
from contacts_cli.label_edit import LABEL_FIELDS, edit_membership

from .test_fixture_contract import fetch
from .test_label_edit import group


def apply_group(server, resource):
    fetch(server, f"/v1/{resource}/members:modify", "POST", {"resourceNamesToAdd": ["people/c123"]})


def test_remove_fixture_contract(server):
    resource = group(server, "Remove")
    original = deepcopy(server.person)
    apply_group(server, resource)
    path = f"/v1/{resource}/members:modify"
    for _ in range(2):
        assert fetch(server, path, "POST", {"resourceNamesToRemove": ["people/c123"]}) == (200, {})
    assert server.person == original and resource in server.groups
    server.person["memberships"] = [
        {"contactGroupMembership": {"contactGroupResourceName": resource}}
    ]
    _, response = fetch(server, path, "POST", {"resourceNamesToRemove": ["people/c123"]})
    assert response == {"canNotRemoveLastContactGroupResourceNames": ["people/c123"]}
    assert len(server.person["memberships"]) == 1


@pytest.mark.parametrize("command", ["remove-label", "remove-labels"])
@pytest.mark.parametrize("apply", [False, True])
def test_remove_preview_apply_noop(command, apply, api, server, monkeypatch, capsys):
    resource = group(server, "Remove")
    group(server, "Unapplied")
    original = deepcopy(server.person)
    apply_group(server, resource)
    baseline = server.writes
    groups = deepcopy(server.groups)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    args = [
        command,
        "--contact",
        "c123",
        "--label",
        "Remove",
        "--label",
        "Remove",
        "--label",
        "Unapplied",
        "--label",
        "Missing",
    ]
    assert cli.main(args + (["--apply"] if apply else [])) == 0
    output = capsys.readouterr().out
    assert "Labels not found: 1 label" in output
    assert "Not on this contact: 1 label" in output
    assert (
        "Removing labels: 1 label" in output
        if apply
        else "Proposed label removals: 1 label" in output
    )
    assert server.groups == groups
    if apply:
        assert server.person == original
        assert "Removed and verified 1 label" in output
        writes = server.writes
        assert cli.main(args + ["--apply"]) == 0
        assert server.writes == writes
    else:
        assert server.writes == baseline
        assert resource in str(server.person["memberships"])


@pytest.mark.parametrize("answer", [True, False])
def test_remove_confirmation(answer, api, server, monkeypatch):
    resource = group(server, "Remove")
    apply_group(server, resource)
    baseline = server.writes
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)

    def confirm(question):
        assert question == "Remove 1 label from this contact?"
        assert server.writes == baseline
        return answer

    monkeypatch.setattr(cli, "confirm_apply", confirm)
    assert cli.main(["remove-label", "--contact", "c123", "--label", "Remove"]) == 0
    assert server.writes == baseline + int(answer)


@pytest.mark.parametrize("cancel", [False, True])
def test_removal_case_choice_has_no_create_option(cancel, api, server, monkeypatch, capsys):
    resource = group(server, "Recruiter")
    apply_group(server, resource)
    baseline = server.writes
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (contact_create.sys.stdin, contact_create.sys.stdout, contact_create.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "2" if cancel else "1")
    assert cli.main(["remove-label", "--contact", "c123", "--label", "recruiter", "--apply"]) == 0
    output = capsys.readouterr().out
    assert "Create new" not in output
    assert "Remove 'Recruiter' from this contact" in output and "2. Cancel" in output
    assert server.writes == baseline + int(not cancel)


@pytest.mark.parametrize("fault", ["still_present", "lost_existing"])
def test_removal_readback_verification(fault, api, server, monkeypatch):
    resource = group(server, "Remove")
    apply_group(server, resource)
    person = api.get_contact("people/c123", LABEL_FIELDS)
    original = api.get_contact
    reads = 0

    def altered(*args):
        nonlocal reads
        saved = original(*args)
        reads += 1
        if reads == 2:
            saved["memberships"] = person["memberships"] if fault == "still_present" else []
        return saved

    monkeypatch.setattr(api, "get_contact", altered)
    with pytest.raises(WriteUnverified, match="verification failed"):
        edit_membership(api, person, resource, remove=True)


def test_google_last_membership_refusal(api, server):
    resource = group(server, "Last")
    server.person["memberships"] = [
        {"contactGroupMembership": {"contactGroupResourceName": resource}}
    ]
    with pytest.raises(SyncError, match="last contact-group"):
        edit_membership(api, api.get_contact("people/c123", LABEL_FIELDS), resource, remove=True)
    assert len(server.person["memberships"]) == 1


@pytest.mark.parametrize("command", ["add-label", "remove-label"])
def test_label_commands_accept_global_options_after_command(command):
    args = cli.parser().parse_args(
        [
            command,
            "--contact",
            "c123",
            "--label",
            "Example",
            "--token",
            "/tmp/example-token",
            "--auth-timeout",
            "5",
        ]
    )
    assert str(args.token) == "/tmp/example-token" and args.auth_timeout == 5


@pytest.mark.parametrize("failure,code", [(429, 1), (503, 3), ("interrupt", 130)])
def test_removal_partial_failure_and_interrupt(failure, code, api, server, monkeypatch, capsys):
    import httplib2

    resources = [group(server, name) for name in ("One", "Two", "Three")]
    for resource in resources:
        apply_group(server, resource)
    original = server.request
    attempts = []

    def fail(uri, method="GET", *args, **kwargs):
        if method == "POST" and resources[1] + "/members:modify" in uri:
            attempts.append(uri)
            if failure == "interrupt":
                raise KeyboardInterrupt
            return httplib2.Response({"status": failure}), b'{"error":{"message":"failure"}}'
        return original(uri, method, *args, **kwargs)

    monkeypatch.setattr(server, "request", fail)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert (
        cli.main(
            [
                "remove-label",
                "--contact",
                "c123",
                "--label",
                "One",
                "--label",
                "Two",
                "--label",
                "Three",
                "--apply",
            ]
        )
        == code
    )
    assert "Label removals verified: 1 of 3" in capsys.readouterr().out
    assert len(attempts) == 1
    assert resources[0] not in str(server.person["memberships"])
    assert all(resource in str(server.person["memberships"]) for resource in resources[1:])
    assert all(resource in server.groups for resource in resources)
