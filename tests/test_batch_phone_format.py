"""Batch formatting resolves, previews and verifies independent contact updates."""

from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.errors import (
    ContactFailure,
    ContactVerificationFailure,
    SyncError,
    WriteUnverified,
)

from .test_contact_resolution import setup


def batch(api, server, monkeypatch, answers=None):
    other, _, baseline = setup(api, server, monkeypatch, answers)
    server.person["phoneNumbers"] = [{"value": "+12025550142", "type": "work"}]
    other["phoneNumbers"] = [{"value": "+442079460018 x0042", "type": "mobile"}]
    return other, baseline


@pytest.mark.parametrize(
    "apply,answers,changed",
    [
        (False, None, []),
        (False, ["q"], []),
        (False, ["all", "y"], [0, 1]),
        (False, ["2", "y"], [1]),
        (False, ["1", "n", "2", "y"], [1]),
        (True, None, [0, 1]),
    ],
)
def test_batch_selection(apply, answers, changed, api, server, monkeypatch, capsys):
    other, baseline = batch(api, server, monkeypatch, answers)
    before = deepcopy([server.person, other])
    args = ["format-phone", "--contact", "c123", "--contact", "c456"] + (
        ["--apply"] if apply else []
    )
    assert cli.main(args) == 0
    actual = [server.person, server.created["people/c456"]]
    for i in range(2):
        assert (actual[i]["phoneNumbers"] != before[i]["phoneNumbers"]) == (i in changed)
        for field in before[i].keys() - {"phoneNumbers", "metadata"}:
            assert actual[i][field] == before[i][field]
    assert server.writes == baseline + len(changed)
    out = capsys.readouterr().out
    assert "Jane Example" in out and "Other Example" in out
    if changed:
        assert f"verified: {len(changed)}" in out


def test_combined_file_deduplicates_and_scans_once(api, server, monkeypatch, tmp_path):
    _, baseline = batch(api, server, monkeypatch)
    file = tmp_path / "contacts.txt"
    file.write_text(
        "\ufeff# targets\nJane@example.com\n\nc456\nOther Example\nc123\n", encoding="utf-8"
    )
    assert (
        cli.main(
            [
                "format-phones",
                "--contact",
                "c123",
                "--contact",
                "Jane Example",
                "--contact-file",
                str(file),
                "--apply",
            ]
        )
        == 0
    )
    assert server.writes == baseline + 2
    assert len([p for _, p, _, _ in server.calls if p.endswith("/connections")]) == 1


def test_unmatched_and_missing_ids_skip(api, server, monkeypatch, capsys):
    _, baseline = batch(api, server, monkeypatch)
    assert (
        cli.main(
            [
                "format-phone",
                "--contact",
                "Nobody",
                "--contact",
                "c999",
                "--contact",
                "c456",
                "--apply",
            ]
        )
        == 0
    )
    assert server.writes == baseline + 1
    out = capsys.readouterr().out
    assert "Nobody" in out and "c999" in out


@pytest.mark.parametrize(
    "answers,status,writes",
    [(None, 1, 0), (["q"], 0, 0), (["s"], 0, 0), (["all"], 0, 2), (["2"], 0, 1)],
)
def test_ambiguity(answers, status, writes, api, server, monkeypatch):
    other, baseline = batch(api, server, monkeypatch, answers)
    other["names"] = deepcopy(server.person["names"])
    assert cli.main(["format-phone", "--contact", "Jane Example", "--apply"]) == status
    assert server.writes == baseline + writes


@pytest.mark.parametrize(
    "failure,status,attempts",
    [
        (ContactFailure("stale"), 1, 2),
        (ContactVerificationFailure("mismatch"), 3, 2),
        (SyncError("connection"), 1, 1),
        (WriteUnverified("unknown write"), 3, 1),
        (KeyboardInterrupt(), 130, 1),
    ],
)
def test_saving_failure_policy(failure, status, attempts, api, server, monkeypatch, capsys):
    batch(api, server, monkeypatch)
    original = api.apply_field_change
    calls = []

    def apply(person, *args, **kwargs):
        calls.append(person["resourceName"])
        if len(calls) == 1:
            raise failure
        return original(person, *args, **kwargs)

    monkeypatch.setattr(api, "apply_field_change", apply)
    assert cli.main(["format-phone", "--contact", "c123", "--contact", "c456", "--apply"]) == status
    assert len(calls) == attempts
    out = capsys.readouterr().out
    assert f"unattempted: {2 - attempts}" in out


def test_invalid_file_before_auth(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("auth"))
    file = tmp_path / "bad.txt"
    file.write_text("c123\nhttps://example.com/not-contact\n")
    assert cli.main(["format-phone", "--contact", "c123", "--contact-file", str(file)]) == 1
    assert cli.main(["format-phone", "--contact-file", str(tmp_path / "missing")]) == 1
    assert cli.main(["format-phone"]) == 1


def test_input_loader_contract(tmp_path):
    from contacts_cli.contact_resolution import load_batch_identifiers

    file = tmp_path / "ids.txt"
    file.write_text("\ufeff # ignored\nc456\nc123\nJane Example\n", encoding="utf-8")
    assert load_batch_identifiers([" c123 ", "Jane Example", "c123"], file) == [
        "c123",
        "Jane Example",
        "c456",
    ]
    file.write_text(" # empty\n\n")
    assert load_batch_identifiers(["c123"], file) == ["c123"]
    with pytest.raises(SyncError):
        load_batch_identifiers([], file)
    file.write_bytes(b"\xff")
    with pytest.raises(SyncError):
        load_batch_identifiers(["c123"], file)


def test_noop_skips_unsupported_without_writes(api, server, monkeypatch, capsys):
    other, baseline = batch(api, server, monkeypatch)
    server.person["phoneNumbers"] = [{"value": "+1 202-555-0142"}]
    other["phoneNumbers"] = [{"value": "5550123"}]
    assert cli.main(["format-phone", "--contact", "c123", "--contact", "c456", "--apply"]) == 0
    assert server.writes == baseline
    out = capsys.readouterr().out
    assert "country code is unknown" in out and "No phone formatting changes needed" in out


def test_all_preview_reads_before_writes(api, server, monkeypatch):
    _, baseline = batch(api, server, monkeypatch)
    original = api.get_contact

    def read(resource, *args, **kwargs):
        if resource == "people/c456":
            raise SyncError("connection failure")
        return original(resource, *args, **kwargs)

    monkeypatch.setattr(api, "get_contact", read)
    assert cli.main(["format-phone", "--contact", "c123", "--contact", "c456", "--apply"]) == 1
    assert server.writes == baseline


def test_stale_contact_continues_via_real_guard(api, server, monkeypatch, capsys):
    _, baseline = batch(api, server, monkeypatch)
    original = api.get_contact
    reads = 0

    def read(resource, *args, **kwargs):
        nonlocal reads
        reads += 1
        if reads == 3:
            server.person["phoneNumbers"][0]["type"] = "changed"
        return original(resource, *args, **kwargs)

    monkeypatch.setattr(api, "get_contact", read)
    assert cli.main(["format-phone", "--contact", "c123", "--contact", "c456", "--apply"]) == 1
    assert server.writes == baseline + 1
    assert server.person["phoneNumbers"][0]["value"] == "+12025550142"
    assert "verified: 1; failed: 1" in capsys.readouterr().out


@pytest.mark.parametrize("stage", ["response", "readback", "connection"])
def test_actual_verification_paths(stage, api, server, monkeypatch, capsys):
    _, baseline = batch(api, server, monkeypatch)
    original_write = api.write
    original_read = api.get_contact
    reads = 0

    def write(*args, **kwargs):
        result = original_write(*args, **kwargs)
        if stage == "response" and result["resourceName"] == "people/c123":
            result["phoneNumbers"][0]["value"] = "wrong"
        return result

    def read(*args, **kwargs):
        nonlocal reads
        reads += 1
        if reads == 4 and stage == "connection":
            raise SyncError("readback connection failed")
        result = original_read(*args, **kwargs)
        if reads == 4 and stage == "readback":
            result["phoneNumbers"][0]["value"] = "wrong"
        return result

    monkeypatch.setattr(api, "write", write)
    monkeypatch.setattr(api, "get_contact", read)
    assert cli.main(["format-phone", "--contact", "c123", "--contact", "c456", "--apply"]) == 3
    assert server.writes == baseline + (1 if stage == "connection" else 2)
    out = capsys.readouterr().out
    assert "unverified: 1" in out
    assert f"unattempted: {1 if stage == 'connection' else 0}" in out


def test_interrupt_after_write_is_unverified(api, server, monkeypatch, capsys):
    _, baseline = batch(api, server, monkeypatch)
    original = api.write

    def write(*args, **kwargs):
        original(*args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(api, "write", write)
    assert cli.main(["format-phone", "--contact", "c123", "--contact", "c456", "--apply"]) == 130
    assert server.writes == baseline + 1
    assert "unverified: 1; unattempted: 1" in capsys.readouterr().out


def test_later_failure_preserves_completed_changes(api, server, monkeypatch, capsys):
    _, baseline = batch(api, server, monkeypatch)
    original = api.apply_field_change

    def apply(person, *args, **kwargs):
        if person["resourceName"] == "people/c456":
            raise ContactFailure("rejected")
        return original(person, *args, **kwargs)

    monkeypatch.setattr(api, "apply_field_change", apply)
    assert cli.main(["format-phone", "--contact", "c123", "--contact", "c456", "--apply"]) == 1
    assert server.writes == baseline + 1
    assert server.person["phoneNumbers"][0]["value"] == "+1 202-555-0142"
    assert "verified: 1; failed: 1" in capsys.readouterr().out


def test_skip_identifier_does_not_exclude_later_id(api, server, monkeypatch):
    other, baseline = batch(api, server, monkeypatch, ["s"])
    other["names"] = deepcopy(server.person["names"])
    assert (
        cli.main(["format-phone", "--contact", "Jane Example", "--contact", "c456", "--apply"]) == 0
    )
    assert server.writes == baseline + 1


def test_batch_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["format-phone", "--help"])
    out = capsys.readouterr().out
    assert (
        "--contact-file" in out
        and "repeatable" in out
        and "ambiguous contacts still prompt" in " ".join(out.split())
    )


def test_global_entry_numbers_keep_gaps(api, server, monkeypatch, capsys):
    other, baseline = batch(api, server, monkeypatch, ["3", "y"])
    server.person["phoneNumbers"].insert(0, {"value": "+1 202-555-0199"})
    assert cli.main(["format-phone", "--contact", "c123", "--contact", "c456"]) == 0
    assert server.writes == baseline + 1
    assert server.person["phoneNumbers"][1]["value"] == "+12025550142"
    assert server.created["people/c456"]["phoneNumbers"][0]["value"] == "+44 20 7946 0018 ext. 0042"
    out = capsys.readouterr().out
    assert "2. +12025550142" in out and "3. +442079460018" in out


def test_invalid_later_plan_blocks_all_writes(api, server, monkeypatch):
    other, baseline = batch(api, server, monkeypatch)
    other["userDefined"] = [{"key": f"key{i}", "value": "test"} for i in range(501)]
    assert cli.main(["format-phone", "--contact", "c123", "--contact", "c456", "--apply"]) == 1
    assert server.writes == baseline


@pytest.mark.parametrize("identifier", ["Nobody", "c999"])
def test_nothing_resolved_is_success(identifier, api, server, monkeypatch):
    _, baseline = batch(api, server, monkeypatch)
    assert cli.main(["format-phone", "--contact", identifier, "--apply"]) == 0
    assert server.writes == baseline


def test_eof_cancels_batch(api, server, monkeypatch):
    _, baseline = batch(api, server, monkeypatch, [])

    def eof():
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert cli.main(["format-phone", "--contact", "c123", "--contact", "c456"]) == 0
    assert server.writes == baseline


@pytest.mark.parametrize(
    "contacts,expected",
    [(["c123"], "1 phone entry on 1 contact"), (["c123", "c456"], "2 phone entries on 2 contacts")],
)
def test_preview_counts(contacts, expected, api, server, monkeypatch, capsys):
    batch(api, server, monkeypatch)
    args = ["format-phone"]
    for contact in contacts:
        args.extend(["--contact", contact])
    assert cli.main(args) == 0
    assert expected in capsys.readouterr().out
