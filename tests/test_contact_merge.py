"""Synthetic additive merge, conflict, cancellation, and preservation contracts."""

import json
from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.contact_merge import MergePlan, apply_merge, merge_values, verify_merge
from contacts_cli.duplicate import copy_body
from contacts_cli.errors import SyncError, WriteUnverified


def setup(api, server, monkeypatch, tmp_path, inputs, answers):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (cli.sys.stdin, cli.sys.stdout, cli.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    responses = iter(answers)

    def answer():
        assert server.writes == 0
        return next(responses)

    monkeypatch.setattr("builtins.input", answer)
    path = tmp_path / "merge.json"
    path.write_text(json.dumps(inputs))
    return ["add-contact", "--file", str(path)]


def incoming(server, **fields):
    return {"emailAddresses": [{"value": server.person["emailAddresses"][0]["value"]}], **fields}


def test_fill_preserve_append_and_conflicts():
    before = {
        "emailAddresses": [{"value": "a@example.com", "type": "work"}],
        "organizations": [{"name": "Acme", "title": "Old"}],
        "userDefined": [{"key": "Created", "value": "Original"}],
    }
    new = {
        "emailAddresses": [
            {"value": "A@example.com", "type": "home", "displayName": "Jane"},
            {"value": "b@example.com"},
        ],
        "organizations": [{"name": "ACME", "title": "New", "department": "Sales"}],
        "userDefined": [
            {"key": "Created", "value": "Later"},
            {"key": "External ID", "value": "1"},
            {"key": "External ID", "value": "2"},
        ],
    }
    snapshot = deepcopy(before)
    merged, changes, conflicts = merge_values(before, new)
    assert before == snapshot
    assert merged["emailAddresses"] == [
        {"value": "a@example.com", "type": "work", "displayName": "Jane"},
        {"value": "b@example.com"},
    ]
    assert merged["organizations"] == [{"name": "Acme", "title": "Old", "department": "Sales"}]
    assert merged["userDefined"] == [*before["userDefined"], *new["userDefined"][1:]]
    assert len(conflicts) == 3 and changes
    assert merge_values(merged, new)[0] == merged


def test_singletons_and_duplicate_stored_entries():
    before = {
        "names": [{"givenName": "Jane"}],
        "biographies": [{"value": "Old"}],
        "emailAddresses": [{"value": "a@example.com"}, {"value": "a@example.com"}],
    }
    result, _, conflicts = merge_values(
        before,
        {
            "names": [{"givenName": "Other"}],
            "biographies": [{"value": "New"}],
            "emailAddresses": [{"value": "a@example.com", "type": "work"}],
        },
    )
    assert result == before and len(conflicts) == 3


def test_merge_fixture_replaces_only_target_fields(api, server):
    original = deepcopy(server.person)
    other = deepcopy(original)
    other["resourceName"] = "people/c999"
    other["metadata"]["sources"][0]["id"] = "999"
    for values in other.values():
        if isinstance(values, list):
            for entry in values:
                source = entry.get("metadata", {}).get("source")
                if source:
                    source["id"] = "999"
    server.created["people/c999"] = other
    other_before = deepcopy(other)
    result = api.write(
        api.people.people().updateContact(
            resourceName="people/c999",
            updatePersonFields="urls,userDefined",
            personFields="urls,userDefined,metadata",
            body={
                "metadata": other["metadata"],
                "urls": [{"value": "https://example.com"}],
                "userDefined": [{"key": "A", "value": "B"}],
            },
        )
    )
    assert server.person == original
    assert result["urls"] == [{"value": "https://example.com"}]
    assert result["userDefined"] == [{"key": "A", "value": "B"}]
    assert result["emailAddresses"] == other_before["emailAddresses"]
    assert result["metadata"]["sources"][0]["etag"] != original["metadata"]["sources"][0]["etag"]


@pytest.mark.parametrize("apply", [False, True])
def test_merge_existing(api, server, monkeypatch, tmp_path, capsys, apply):
    before = deepcopy(server.person)
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server, userDefined=[{"key": "External ID", "value": "new"}])],
        ["m"] if apply else ["m", "y"],
    )
    assert cli.main(args + (["--apply"] if apply else [])) == 0
    assert not server.created and server.writes == 1
    assert {"key": "External ID", "value": "new"} in server.person["userDefined"]
    assert server.person["emailAddresses"] == before["emailAddresses"]
    assert "Merged and verified" in capsys.readouterr().out


def test_merge_cancel(api, server, monkeypatch, tmp_path):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server, urls=[{"value": "https://example.com/new"}])],
        ["m", "n"],
    )
    assert cli.main(args) == 0 and server.writes == 0


def test_incoming_merge_creates_one_contact(api, server, monkeypatch, tmp_path):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [
            {"names": [{"givenName": "Jane"}], "emailAddresses": [{"value": "jane@example.com"}]},
            {"names": [{"givenName": "Jane"}], "phoneNumbers": [{"value": "2025550142"}]},
        ],
        ["all", "m", "y"],
    )
    assert cli.main(args) == 0
    assert len(server.created) == 1
    saved = next(iter(server.created.values()))
    assert saved["phoneNumbers"] and saved["emailAddresses"]
    assert not saved.get("userDefined")


def test_two_inputs_one_existing_update(api, server, monkeypatch, tmp_path):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server, userDefined=[{"key": "External ID", "value": str(i)}]) for i in (1, 2)],
        ["all", "m", "m", "y"],
    )
    assert cli.main(args) == 0 and server.writes == 1
    assert all(
        {"key": "External ID", "value": str(i)} in server.person["userDefined"] for i in (1, 2)
    )


def test_noop_merge_no_write(api, server, monkeypatch, tmp_path):
    args = setup(api, server, monkeypatch, tmp_path, [incoming(server)], ["n", "s"])
    assert cli.main(args) == 0 and server.writes == 0


def make_plan(api, server):
    original = deepcopy(server.person)
    body = copy_body(original, api.people._rootDesc["schemas"])
    body.setdefault("userDefined", []).append({"key": "External ID", "value": "new"})
    return MergePlan(original, body)


def test_changed_target_blocks_write(api, server):
    plan = make_plan(api, server)
    server.person["names"] = [{"givenName": "Edited"}]
    with pytest.raises(SyncError, match="changed"):
        apply_merge(api, plan)
    assert server.writes == 0


@pytest.mark.parametrize("field", ["emailAddresses", "userDefined", "names", "photos"])
def test_verification_detects_loss(api, server, field):
    plan = make_plan(api, server)
    saved = {**deepcopy(server.person), **deepcopy(plan.expected)}
    saved[field] = [] if field != "photos" else [{"url": "https://example.com/changed"}]
    with pytest.raises(SyncError):
        verify_merge(plan, saved, api.people._rootDesc["schemas"])


def test_failed_verification_does_not_retry(api, server):
    plan = make_plan(api, server)
    server.lose_additions = True
    with pytest.raises(WriteUnverified):
        apply_merge(api, plan)
    assert server.writes == 1


def test_standard_url_label_normalization_custom_strict(api, server):
    plan = make_plan(api, server)
    plan.expected["urls"] = [{"value": "https://example.com", "type": "Profile"}]
    saved = {**deepcopy(server.person), **deepcopy(plan.expected)}
    saved["urls"][0]["type"] = "profile"
    verify_merge(plan, saved, api.people._rootDesc["schemas"])
    plan.expected["urls"][0]["type"] = "Custom"
    saved["urls"][0]["type"] = "custom"
    with pytest.raises(SyncError):
        verify_merge(plan, saved, api.people._rootDesc["schemas"])


def test_multiple_targets_choice_and_cancel(api, server, monkeypatch, tmp_path):
    other = deepcopy(server.person)
    other["resourceName"] = "people/c999"
    other["metadata"]["sources"][0]["id"] = "999"
    for values in other.values():
        if isinstance(values, list):
            for entry in values:
                source = entry.get("metadata", {}).get("source")
                if source:
                    source["id"] = "999"
    server.created["people/c999"] = other
    before = deepcopy(server.person)
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server, userDefined=[{"key": "External ID", "value": "new"}])],
        ["m", "bad", "2", "y"],
    )
    assert cli.main(args) == 0
    assert server.person == before and server.writes == 1
    assert {"key": "External ID", "value": "new"} in other["userDefined"]


def test_cancel_target_choice(api, server, monkeypatch, tmp_path):
    other = deepcopy(server.person)
    other["resourceName"] = "people/c999"
    server.created["people/c999"] = other
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server, urls=[{"value": "https://example.com/new"}])],
        ["m", "q"],
    )
    assert cli.main(args) == 0 and server.writes == 0


def test_merge_labels_preserve_memberships_and_created(api, server, monkeypatch, tmp_path):
    server.person.setdefault("userDefined", []).append({"key": "Created", "value": "Original"})
    before = deepcopy(server.person)
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server, userDefined=[{"key": "Created", "value": "Other"}])],
        ["m", "k", "y"],
    )
    assert cli.main(args + ["--label", "New"]) == 0
    assert server.writes == 2
    assert server.person["userDefined"] == before["userDefined"]
    assert all(e in server.person["memberships"] for e in before.get("memberships", []))
    assert len(server.person["memberships"]) == len(before.get("memberships", [])) + 1


def test_preflight_conflict_prevents_label_creation(api, server, monkeypatch, tmp_path):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server, urls=[{"value": "https://example.com"}])],
        ["m", "y"],
    )
    original = api.get_contact
    reads = 0

    def read(*a, **kw):
        nonlocal reads
        reads += 1
        if reads == 2:
            server.person["metadata"]["sources"][0]["etag"] = "other"
        return original(*a, **kw)

    monkeypatch.setattr(api, "get_contact", read)
    assert cli.main(args + ["--label", "New"]) == 1
    assert server.writes == 0


def test_create_failure_after_merge_reports_progress(api, server, monkeypatch, tmp_path, capsys):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [
            incoming(server, urls=[{"value": "https://example.com/new"}]),
            {"names": [{"givenName": "New Person"}]},
        ],
        ["all", "m", "y"],
    )
    server.create_status = 400
    assert cli.main(args) == 1
    assert server.writes == 1 and not server.created
    output = capsys.readouterr().out
    assert "0 contacts created and verified; 1 merged and verified" in output
    assert "1 failed before saving; 0 unverified; 0 not attempted" in output


def test_merge_interrupt_reports_uncertain_write(api, server, monkeypatch, tmp_path, capsys):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server, urls=[{"value": "https://example.com/new"}])],
        ["m", "y"],
    )

    def interrupt(*a, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(api, "write", interrupt)
    assert cli.main(args) == 130
    assert "may have been saved" in capsys.readouterr().out


def test_merge_rejects_changed_primary(api, server):
    plan = make_plan(api, server)
    plan.expected["emailAddresses"][0].setdefault("metadata", {})["sourcePrimary"] = True
    saved = {**deepcopy(server.person), **deepcopy(plan.expected)}
    saved["emailAddresses"][0]["metadata"]["sourcePrimary"] = False
    with pytest.raises(SyncError, match="primary"):
        verify_merge(plan, saved, api.people._rootDesc["schemas"])


def test_partial_birthday_fills_zero_year_and_rejects_invalid_date():
    result, _, _ = merge_values(
        {"birthdays": [{"date": {"year": 0, "month": 2, "day": 29}}]},
        {"birthdays": [{"date": {"year": 2024}}]},
    )
    assert result["birthdays"][0]["date"]["year"] == 2024
    with pytest.raises(SyncError):
        merge_values(
            {"birthdays": [{"date": {"month": 2, "day": 29}}]},
            {"birthdays": [{"date": {"year": 2023}}]},
        )


def test_generated_address_properties_and_extra_entry_guard(api, server):
    plan = make_plan(api, server)
    plan.expected["addresses"] = [{"city": "Irvine", "countryCode": "US"}]
    saved = {**deepcopy(server.person), **deepcopy(plan.expected)}
    saved["addresses"][0].update(formattedValue="Irvine, USA", country="United States")
    verify_merge(plan, saved, api.people._rootDesc["schemas"])
    saved["addresses"].append({"city": "Unexpected"})
    with pytest.raises(SyncError):
        verify_merge(plan, saved, api.people._rootDesc["schemas"])


@pytest.mark.parametrize("conflict", [False, True])
@pytest.mark.parametrize("apply", [False, True])
def test_no_changes_finishes_without_approval(
    api, server, monkeypatch, tmp_path, capsys, conflict, apply
):
    fields = {"names": [{"givenName": "Different"}]} if conflict else {}
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server, **fields)],
        ["s"] if conflict else ["n", "s"],
    )
    assert cli.main(args + (["--apply"] if apply else [])) == 0
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert server.writes == 0
    assert "All selected inputs skipped; no changes made." in output
    assert "Apply these" not in output and "Merging into" not in output
    assert "Merge targets:" not in output
    if conflict:
        assert "Conflicts to resolve" in output
        assert "Already contains all supplied information" not in output
    else:
        assert "Nothing new" in output
        assert "  m   Merge" not in output


@pytest.mark.parametrize("label_state", ["present", "existing", "new"])
def test_unchanged_details_still_plan_label_changes(
    api, server, monkeypatch, tmp_path, capsys, label_state
):
    resource = "contactGroups/test"
    if label_state != "new":
        server.groups[resource] = {
            "resourceName": resource,
            "name": "Test",
            "groupType": "USER_CONTACT_GROUP",
        }
    if label_state == "present":
        server.person.setdefault("memberships", []).append(
            {"contactGroupMembership": {"contactGroupResourceName": resource}}
        )
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server)],
        ["n", "s"] if label_state == "present" else ["m", "y"],
    )
    assert cli.main(args + ["--label", "Test"]) == 0
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert server.writes == {"present": 0, "existing": 1, "new": 2}[label_state]
    if label_state == "present":
        assert "All selected inputs skipped" in output
    else:
        assert "Contacts to update: 1 contact" in output
        assert "Labels to add: Test" in output
        assert "Contact details already present; requested labels will be added." in output
        assert "nothing to merge" not in output
        assert "Apply these changes?" in output


def test_unchanged_target_omitted_but_new_contact_confirmed(
    api, server, monkeypatch, tmp_path, capsys
):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server), {"names": [{"givenName": "New Person"}]}],
        ["all", "n", "s", "y"],
    )
    assert cli.main(args) == 0
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert server.writes == 1 and len(server.created) == 1
    assert "Contacts to update:" not in output and "Merging into" not in output
    assert "Created and verified 1 contact" in output
    assert "Skipped input #1" in output


@pytest.mark.parametrize("reverse", [False, True])
def test_same_target_noop_does_not_discard_pending_changes(
    api, server, monkeypatch, tmp_path, capsys, reverse
):
    inputs = [incoming(server), incoming(server, urls=[{"value": "https://example.com/new"}])]
    if reverse:
        inputs.reverse()
    answers = ["all", "m", "s", "y"] if reverse else ["all", "s", "m", "y"]
    args = setup(api, server, monkeypatch, tmp_path, inputs, answers)
    assert cli.main(args) == 0 and server.writes == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "Selected merge changes: 1 change" in output
    assert "Contacts to update: 1 contact" in output
    assert server.person["urls"] == [{"value": "https://example.com/new"}]


def test_conflicts_and_additions_both_shown(api, server, monkeypatch, tmp_path, capsys):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [
            incoming(
                server,
                names=[{"givenName": "Different"}],
                urls=[{"value": "https://example.com/new"}],
            )
        ],
        ["m", "k", "y"],
    )
    before = deepcopy(server.person["names"])
    assert cli.main(args) == 0 and server.writes == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "Selected merge changes: 1 change" in output
    assert "Kept existing; not imported" in output
    assert server.person["names"] == before


def test_identical_inputs_still_confirm_one_creation(api, server, monkeypatch, tmp_path, capsys):
    person = {"names": [{"givenName": "Brand New"}]}
    args = setup(api, server, monkeypatch, tmp_path, [person, person], ["all", "s", "y"])
    assert cli.main(args) == 0 and len(server.created) == 1
    captured = capsys.readouterr()
    assert "Nothing new" in captured.out
    assert "Created and verified 1 contact" in captured.out
    assert "Create 1 contact?" in captured.err


def test_label_only_cancel_creates_nothing(api, server, monkeypatch, tmp_path):
    args = setup(api, server, monkeypatch, tmp_path, [incoming(server)], ["m", "n"])
    before = deepcopy(server.person)
    assert cli.main(args + ["--label", "New"]) == 0
    assert server.writes == 0 and server.person == before and not server.groups
