"""Membership-aware label choices and concise previews use the actual CLI path."""

import pytest

from contacts_cli import cli, contact_create

from .test_label_edit import group
from .test_remove_label import apply_group


@pytest.mark.parametrize("on_contact", [False, True])
@pytest.mark.parametrize("remove", [False, True])
def test_case_menu_membership_context(on_contact, remove, api, server, monkeypatch, capsys):
    resource = group(server, "Recruiter")
    if on_contact:
        apply_group(server, resource)
    baseline = server.writes
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (contact_create.sys.stdin, contact_create.sys.stdout, contact_create.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "")
    monkeypatch.setattr(cli, "confirm_apply", lambda q: False)
    command = "remove-label" if remove else "add-label"
    assert cli.main([command, "--contact", "c123", "--label", "recruiter"]) == 0
    captured = capsys.readouterr()
    if remove and not on_contact:
        assert "Not on this contact: 1 label" in captured.out
        assert "Choose" not in captured.err
    else:
        expected = (
            "Remove 'Recruiter' from this contact"
            if remove
            else "Keep 'Recruiter'; skip adding 'recruiter'"
            if on_contact
            else "Add 'Recruiter'"
        )
        assert expected in captured.out
        assert "Cancel command" in captured.out
        assert f"Choose 1–{2 if remove else 3} (Enter = 1):" in captured.err
    assert server.writes == baseline


@pytest.mark.parametrize("on_contact", [False, True])
def test_exact_match_wins_over_other_case(on_contact, api, server, monkeypatch, capsys):
    exact = group(server, "recruiter")
    other = group(server, "Recruiter")
    apply_group(server, other)
    if on_contact:
        apply_group(server, exact)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    monkeypatch.setattr(contact_create, "choose_label", lambda *a, **k: pytest.fail("case menu"))
    assert cli.main(["add-label", "--contact", "c123", "--label", "recruiter"]) == 0
    output = capsys.readouterr().out
    assert ("Already on this contact: 1 label" in output) == on_contact
    assert f"Proposed label additions: {0 if on_contact else 1} label" in output


@pytest.mark.parametrize("existing,new", [(0, 1), (0, 2), (1, 0), (1, 1)])
def test_preview_and_confirmation_counts(existing, new, api, server, monkeypatch, capsys):
    args = ["add-label", "--contact", "c123"]
    for i in range(existing):
        group(server, f"Existing{i}")
        args += ["--label", f"Existing{i}"]
    for i in range(new):
        args += ["--label", f"New{i}"]
    baseline = server.writes
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    questions = []
    monkeypatch.setattr(cli, "confirm_apply", lambda q: questions.append(q) or False)
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    assert "Labels to create" not in output
    assert output.count("New0 (new label)") == int(new > 0)
    expected = {
        (0, 1): "Create 1 new label and add it to this contact?",
        (0, 2): "Create 2 new labels and add them to this contact?",
        (1, 0): "Add 1 label to this contact?",
        (1, 1): "Create 1 new label and add 2 labels to this contact?",
    }
    assert questions == [expected[existing, new]]
    assert server.writes == baseline


@pytest.mark.parametrize("remove", [False, True])
@pytest.mark.parametrize("count", [1, 2])
def test_success_summary_is_not_repeated(remove, count, api, server, monkeypatch, capsys):
    args = ["remove-label" if remove else "add-label", "--contact", "c123", "--apply"]
    for i in range(count):
        resource = group(server, f"Label{i}")
        if remove:
            apply_group(server, resource)
        args += ["--label", f"Label{i}"]
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    verb = "Removed" if remove else "Added"
    assert output.count(f"{verb} and verified label:") == (count if count > 1 else 0)
    assert f"{verb} and verified {count} label" in output


@pytest.mark.parametrize("answer", ["2", "3"])
def test_keep_or_create_case_variant_and_cancel_entire_plan(
    answer, api, server, monkeypatch, capsys
):
    resource = group(server, "Recruiter")
    apply_group(server, resource)
    baseline = server.writes
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (contact_create.sys.stdin, contact_create.sys.stdout, contact_create.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: answer)
    assert (
        cli.main(
            [
                "add-label",
                "--contact",
                "c123",
                "--label",
                "Other",
                "--label",
                "recruiter",
                "--apply",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    if answer == "3":
        assert "Cancelled; no changes made" in output
        assert server.writes == baseline
    else:
        assert {g["name"] for g in server.groups.values()} == {"Recruiter", "recruiter", "Other"}
        assert len(server.person["memberships"]) == 4
        assert "recruiter (new label)" in output


@pytest.mark.parametrize("remove", [False, True])
def test_multiple_case_matches_show_only_applicable_actions(
    remove, api, server, monkeypatch, capsys
):
    applied = group(server, "Recruiter")
    group(server, "RECRUITER")
    apply_group(server, applied)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (contact_create.sys.stdin, contact_create.sys.stdout, contact_create.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "1")
    monkeypatch.setattr(cli, "confirm_apply", lambda q: False)
    assert (
        cli.main(
            ["remove-label" if remove else "add-label", "--contact", "c123", "--label", "recruiter"]
        )
        == 0
    )
    output = capsys.readouterr().out
    if remove:
        assert "Remove 'Recruiter' from this contact" in output
        assert "Remove 'RECRUITER'" not in output
        assert "Not on this contact: 1 label" in output
    else:
        assert "Keep 'Recruiter'; skip adding 'recruiter'" in output
        assert "Add 'RECRUITER'" in output
