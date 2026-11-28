"""Shared batch policy for contact labeling; no live account access."""

import pytest

from contacts_cli import bulk_labels, cli
from contacts_cli.errors import (
    ContactFailure,
    ContactVerificationFailure,
    SyncError,
    WriteUnverified,
)
from contacts_cli.label_edit import memberships

from .test_contact_resolution import setup


def test_combined_inputs_deduplicate(api, server, monkeypatch, tmp_path):
    other, label, baseline = setup(api, server, monkeypatch)
    path = tmp_path / "contacts.txt"
    path.write_text("\ufeff# list\nc123\nc456\n")
    assert (
        cli.main(
            [
                "add-label",
                "--contact",
                "c123",
                "--contact",
                "Jane Example",
                "--contact-file",
                str(path),
                "--label",
                "Test",
                "--apply",
            ]
        )
        == 0
    )
    assert label in memberships(server.person) and label in memberships(other)
    assert server.writes == baseline + 2


@pytest.mark.parametrize(
    "failure,code,continues",
    [
        (ContactFailure("missing contact"), 1, True),
        (ContactVerificationFailure("content differs"), 3, True),
        (SyncError("shared label missing"), 1, False),
        (WriteUnverified("connection lost after write"), 3, False),
        (KeyboardInterrupt(), 130, False),
    ],
)
def test_failure_policy(api, server, monkeypatch, tmp_path, capsys, failure, code, continues):
    other, label, _ = setup(api, server, monkeypatch)
    real = bulk_labels.add_membership
    calls = []

    def apply(api, person, group):
        calls.append(person["resourceName"])
        if len(calls) == 1:
            raise failure
        return real(api, person, group)

    monkeypatch.setattr(bulk_labels, "add_membership", apply)
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc456\n")
    assert (
        cli.main(["add-label", "--contact-file", str(path), "--label", "Test", "--apply"]) == code
    )
    assert (label in memberships(other)) == continues
    output = capsys.readouterr().out
    assert f"{0 if continues else 1} not attempted" in output


def test_all_shared_labels_created_before_memberships(api, server, monkeypatch, tmp_path):
    setup(api, server, monkeypatch)
    real = bulk_labels.add_membership
    seen = []

    def apply(api, person, group):
        assert {"First", "Second"}.issubset({g["name"] for g in server.groups.values()})
        seen.append(group)
        return real(api, person, group)

    monkeypatch.setattr(bulk_labels, "add_membership", apply)
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc456\n")
    assert (
        cli.main(
            [
                "add-label",
                "--contact-file",
                str(path),
                "--label",
                "First",
                "--label",
                "Second",
                "--apply",
            ]
        )
        == 0
    )
    assert len(seen) == 4


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("missing_contact", ContactFailure),
        ("missing_label", SyncError),
        ("content", ContactVerificationFailure),
        ("read", WriteUnverified),
        ("identity", ContactFailure),
    ],
)
def test_membership_failure_classification(api, server, monkeypatch, kind, expected):
    """Exercise the writer, not merely the batch's exception dispatch."""
    from copy import deepcopy

    from contacts_cli.label_edit import add_membership

    _, label, _ = setup(api, server, monkeypatch)
    person = deepcopy(server.person)
    real_read, real_write = api.get_contact, api.write
    reads = 0

    def read(*args, **kwargs):
        nonlocal reads
        reads += 1
        result = real_read(*args, **kwargs)
        if kind == "identity" and reads == 1:
            result["metadata"]["sources"][0]["id"] = "999"
        if reads == 2:
            if kind == "content":
                result["memberships"] = []
            elif kind == "read":
                raise SyncError("verification transport failed")
        return result

    def write(*args, **kwargs):
        if kind == "missing_contact":
            return {"notFoundResourceNames": [person["resourceName"]]}
        if kind == "missing_label":
            raise ContactFailure("HTTP 404 shared group")
        return real_write(*args, **kwargs)

    monkeypatch.setattr(api, "get_contact", read)
    monkeypatch.setattr(api, "write", write)
    with pytest.raises(expected) as caught:
        add_membership(api, person, label)
    assert type(caught.value) is expected
    assert reads == (2 if kind in {"content", "read"} else 1)


def test_partial_contact_failure_continues_with_label_evidence(
    api, server, monkeypatch, tmp_path, capsys
):
    from .test_label_edit import group

    other, first, baseline = setup(api, server, monkeypatch)
    second = group(server, "Second")
    real = bulk_labels.add_membership

    def apply(api, person, label):
        if person["resourceName"] == "people/c123" and label == second:
            raise ContactFailure("contact rejected")
        return real(api, person, label)

    monkeypatch.setattr(bulk_labels, "add_membership", apply)
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc456\n")
    assert (
        cli.main(
            [
                "add-label",
                "--contact-file",
                str(path),
                "--label",
                "Test",
                "--label",
                "Second",
                "--apply",
            ]
        )
        == 1
    )
    assert first in memberships(server.person) and second not in memberships(server.person)
    assert {first, second}.issubset(memberships(other))
    assert server.writes == baseline + 4  # one label creation and three verified memberships
    output = capsys.readouterr().out
    assert "Labels verified on this contact: Test" in output
    assert "Label not applied: Second" in output
    assert "1 verified; 1 failed; 0 unverified; 0 not attempted" in output


def test_concurrent_membership_is_verified_without_write(
    api, server, monkeypatch, tmp_path, capsys
):
    _, label, baseline = setup(api, server, monkeypatch)
    real = bulk_labels.add_membership

    def apply(api, person, group):
        target = (
            server.person
            if person["resourceName"] == "people/c123"
            else server.created["people/c456"]
        )
        target["memberships"].append(
            {"contactGroupMembership": {"contactGroupResourceName": group}}
        )
        return real(api, person, group)

    monkeypatch.setattr(bulk_labels, "add_membership", apply)
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc456\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "Test", "--apply"]) == 0
    assert server.writes == baseline
    assert "0 saved; 2 already applied since preview" in capsys.readouterr().out


def test_shared_creation_failure_prevents_all_contact_writes(
    api, server, monkeypatch, tmp_path, capsys
):
    setup(api, server, monkeypatch)
    real = bulk_labels.create_label
    created = []

    def create(api, name, state):
        if created:
            raise SyncError("shared failure")
        result = real(api, name, state)
        created.append(result)
        return result

    monkeypatch.setattr(bulk_labels, "create_label", create)
    monkeypatch.setattr(
        bulk_labels, "add_membership", lambda *a: pytest.fail("membership before labels ready")
    )
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc456\n")
    assert (
        cli.main(
            [
                "add-label",
                "--contact-file",
                str(path),
                "--label",
                "First",
                "--label",
                "Second",
                "--apply",
            ]
        )
        == 1
    )
    output = capsys.readouterr().out
    assert "New labels verified: First. They remain saved." in output
    assert "2 not attempted" in output


def test_interrupted_write_is_unverified(api, server, monkeypatch, tmp_path, capsys):
    setup(api, server, monkeypatch)

    def apply(api, *args):
        api.write_started = True
        raise KeyboardInterrupt

    monkeypatch.setattr(bulk_labels, "add_membership", apply)
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc456\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "Test", "--apply"]) == 130
    assert "0 verified; 0 failed; 1 unverified; 1 not attempted" in capsys.readouterr().out


def test_invalid_combined_input_stops_before_authorization(monkeypatch, tmp_path):
    path = tmp_path / "contacts.txt"
    path.write_text("https://example.com/not-a-contact\n")
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("authorization"))
    assert (
        cli.main(
            [
                "add-label",
                "--contact",
                "c123",
                "--contact-file",
                str(path),
                "--label",
                "Test",
                "--apply",
            ]
        )
        == 1
    )


@pytest.mark.parametrize("phase", ["writing", "created"])
def test_uncertain_label_creation_reports_no_contact_attempts(
    api, server, monkeypatch, tmp_path, capsys, phase
):
    setup(api, server, monkeypatch)

    def create(api, name, state):
        state.phase = phase
        state.location = "contactGroups/synthetic"
        api.write_started = True
        raise WriteUnverified("creation uncertain")

    monkeypatch.setattr(bulk_labels, "create_label", create)
    monkeypatch.setattr(
        bulk_labels, "add_membership", lambda *a: pytest.fail("unexpected membership")
    )
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc456\n")
    assert cli.main(["add-label", "--contact-file", str(path), "--label", "New", "--apply"]) == 3
    output = capsys.readouterr().out
    assert "0 verified; 0 failed; 0 unverified; 2 not attempted" in output
    assert (
        "Label creation outcome is unknown"
        if phase == "writing"
        else "Label created but unverified"
    ) in output


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("names", [["Test"], ["Test", "Another"]])
def test_batch_heading_distinguishes_preview_from_apply(
    api, server, monkeypatch, tmp_path, capsys, apply, names
):
    setup(api, server, monkeypatch)
    path = tmp_path / "contacts.txt"
    path.write_text("c123\nc456\n")
    args = ["add-label", "--contact-file", str(path)]
    for name in names:
        args += ["--label", name]
    if apply:
        args += ["--apply"]
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    labels = ", ".join(repr(name) for name in names)
    if apply:
        noun = "label" if len(names) == 1 else "labels"
        assert f"Adding {noun} {labels}: 2 contacts" in output
        assert "Proposed label additions" not in output
    else:
        assert f"Proposed label additions: {labels} — 2 contacts" in output
