"""Account label operations never read or edit a contact."""

from copy import deepcopy

import pytest

from contacts_cli import cli, contact_create
from contacts_cli.errors import WriteUnverified

from .test_label_edit import group


def connect(api, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    monkeypatch.setattr(api, "get_contact", lambda *a: pytest.fail("contact read"))


@pytest.mark.parametrize("command", ["list-label", "list-labels"])
def test_account_listing(command, api, server, monkeypatch, capsys):
    for name in ("Zulu", "alpha", "System", "Deleted"):
        resource = group(server, name)
        if name == "System":
            server.groups[resource]["groupType"] = "SYSTEM_CONTACT_GROUP"
        if name == "Deleted":
            server.groups[resource]["metadata"] = {"deleted": True}
    connect(api, monkeypatch)
    baseline = server.writes
    assert cli.main([command]) == 0
    output = capsys.readouterr().out
    assert "Labels: 2 labels" in output
    assert "1. alpha" in output and "2. Zulu" in output
    assert "System" not in output and "Deleted" not in output
    assert server.writes == baseline


@pytest.mark.parametrize("command", ["add-label", "add-labels"])
@pytest.mark.parametrize("apply", [False, True])
def test_account_creation(command, apply, api, server, monkeypatch, capsys):
    group(server, "Existing")
    connect(api, monkeypatch)
    before, baseline = deepcopy(server.person), server.writes
    args = [command, "--label", "Existing", "--label", "New", "--label", "New"]
    assert cli.main(args + (["--apply"] if apply else [])) == 0
    output = capsys.readouterr().out
    assert "Already exists: 1 label" in output
    assert "1. New" in output
    assert "this contact" not in output
    assert server.writes == baseline + int(apply)
    assert server.person == before
    if apply:
        assert "Created and verified 1 label" in output
        assert cli.main(args + ["--apply"]) == 0
        assert server.writes == baseline + 1


@pytest.mark.parametrize("answer", [True, False])
def test_account_confirmation(answer, api, server, monkeypatch):
    connect(api, monkeypatch)

    def confirm(question):
        assert server.writes == 0
        assert question == "Create 1 label?"
        return answer

    monkeypatch.setattr(cli, "confirm_apply", confirm)
    assert cli.main(["add-label", "--label", "New"]) == 0
    assert server.writes == int(answer)


@pytest.mark.parametrize("choice", ["Recruiter", "recruiter", None])
def test_account_case_choice(choice, api, server, monkeypatch):
    group(server, "Recruiter")
    connect(api, monkeypatch)
    baseline = server.writes

    def choose(*args, **kwargs):
        assert kwargs.get("on_contact") is None
        if choice is None:
            raise contact_create.LabelChoiceCancelled
        return choice

    monkeypatch.setattr(contact_create, "choose_label", choose)
    assert cli.main(["add-label", "--label", "recruiter", "--apply"]) == 0
    assert server.writes == baseline + int(choice == "recruiter")


def test_account_unresolved_case_apply(api, server, monkeypatch):
    group(server, "Recruiter")
    connect(api, monkeypatch)
    baseline = server.writes
    assert cli.main(["add-label", "--label", "recruiter", "--apply"]) == 1
    assert server.writes == baseline


@pytest.mark.parametrize(
    "error,code", [(WriteUnverified("saved mismatch"), 3), (KeyboardInterrupt(), 130)]
)
def test_account_partial_failure(error, code, api, server, monkeypatch, capsys):
    from contacts_cli import label_edit

    connect(api, monkeypatch)
    original = label_edit.create_label
    attempted = []

    def create(api, name, state):
        attempted.append(name)
        resource = original(api, name, state)
        if name == "Two":
            state.phase = "created"
            raise error
        return resource

    monkeypatch.setattr(label_edit, "create_label", create)
    args = ["add-label", "--label", "One", "--label", "Two", "--label", "Three", "--apply"]
    assert cli.main(args) == code
    output = capsys.readouterr().out
    assert attempted == ["One", "Two"]
    assert "1 verified" in output and "1 not attempted" in output
    assert "remain saved" in output


@pytest.mark.parametrize("label_request", ["Absent", "absent", "Abs*", "Unknown"])
def test_remove_only_contact_matches(label_request, api, server, monkeypatch, capsys):
    group(server, "Absent")
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    baseline = server.writes
    assert cli.main(["remove-label", "--contact", "c123", "--label", label_request]) == 0
    output = capsys.readouterr().out
    assert "No matching labels on this contact" in output
    assert "Not on this contact" not in output and "Labels not found" not in output
    assert "1. Absent" not in output
    assert server.writes == baseline


@pytest.mark.parametrize("answer,created", [("1", False), ("2", True), ("3", False)])
def test_account_case_menu_wording(answer, created, api, server, monkeypatch, capsys):
    group(server, "test1")
    connect(api, monkeypatch)
    for stream in (cli.sys.stdin, cli.sys.stdout, cli.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: answer)
    baseline = server.writes
    assert cli.main(["add-label", "--label", "TEST1", "--apply"]) == 0
    output = capsys.readouterr().out
    assert "Label 'test1' already exists; only its case differs from 'TEST1'." in output
    assert "Keep 'test1'; skip creating 'TEST1'" in output
    assert "Create 'TEST1' as a separate label" in output
    assert "Use existing" not in output
    assert server.writes == baseline + int(created)
