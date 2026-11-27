"""Label-only import review stays compact without bypassing write safeguards."""

from copy import deepcopy

import pytest

from contacts_cli import cli

from .test_contact_merge import setup
from .test_grouped_email_labels import group_setup


def label_setup(api, server, monkeypatch, tmp_path, answers, count=3):
    _, inputs, saved = group_setup(api, server, monkeypatch, tmp_path, [], count=count)
    for person, original in zip(inputs, saved, strict=True):
        person["emailAddresses"][0]["type"] = original["emailAddresses"][0]["type"]
    server.groups["contactGroups/recruiter"] = {
        "resourceName": "contactGroups/recruiter",
        "name": "Recruiter",
        "groupType": "USER_CONTACT_GROUP",
    }
    return (
        setup(api, server, monkeypatch, tmp_path, inputs, answers) + ["--label", "Recruiter"],
        inputs,
        saved,
    )


@pytest.mark.parametrize("count", [1, 3, 20])
def test_compact_label_import(api, server, monkeypatch, tmp_path, capsys, count):
    from contacts_cli.quota import PeopleQuota

    from .test_people_quota import Clock

    clock = Clock()
    api.people._http.contacts_quota = PeopleQuota(clock=clock, sleep=clock.sleep)
    args, _, saved = label_setup(
        api, server, monkeypatch, tmp_path, (["all"] if count > 1 else []) + ["all", "y"], count
    )
    before = deepcopy(saved)
    assert cli.main(args) == 0
    captured = capsys.readouterr()
    assert "Add label Recruiter:" in captured.out
    assert "No new contact details" not in captured.out
    assert "matching email" not in captured.out
    assert "Merging into" not in captured.out
    assert "Merged and verified:" not in captured.out
    assert f"Existing contacts to label: {count}" in captured.out
    assert f"{count} {'contact' if count == 1 else 'contacts'} labeled and verified" in captured.out
    assert "Saving contact labels" in captured.err
    assert server.writes == count
    if count == 20:
        assert clock.waits  # Large batches exercise pacing without a wall-clock sleep.
    for old, new in zip(before, saved, strict=True):
        assert new["emailAddresses"] == old["emailAddresses"]
        assert any(
            m["contactGroupMembership"]["contactGroupResourceName"] == "contactGroups/recruiter"
            for m in new["memberships"]
        )


def test_subset_preserves_numbers(api, server, monkeypatch, tmp_path, capsys):
    args, _, saved = label_setup(api, server, monkeypatch, tmp_path, ["1,3", "3", "y"])
    assert cli.main(args) == 0 and server.writes == 1
    out = capsys.readouterr().out
    assert "3. Person 3" in out
    assert "1. Person 3" not in out
    assert not any(
        m["contactGroupMembership"]["contactGroupResourceName"] == "contactGroups/recruiter"
        for m in saved[0]["memberships"]
    )


@pytest.mark.parametrize("answers", [["q"], ["all", "q"], ["all", "s"], ["all", "all", "n"]])
def test_cancel_or_skip_writes_nothing(api, server, monkeypatch, tmp_path, answers):
    args, _, saved = label_setup(api, server, monkeypatch, tmp_path, answers)
    before = deepcopy(saved)
    assert cli.main(args) == 0 and server.writes == 0 and saved == before


@pytest.mark.parametrize("apply", [False, True])
def test_noninteractive_remains_preview_or_error(api, server, monkeypatch, tmp_path, apply):
    args, _, _ = label_setup(api, server, monkeypatch, tmp_path, [])
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    assert cli.main(args + (["--apply"] if apply else [])) == (1 if apply else 0)
    assert server.writes == 0


def test_apply_still_reviews_labels(api, server, monkeypatch, tmp_path):
    args, _, _ = label_setup(api, server, monkeypatch, tmp_path, ["all"])
    assert cli.main(args + ["--apply"]) == 0 and server.writes == 3


def test_different_missing_label_sets(api, server, monkeypatch, tmp_path, capsys):
    args, _, saved = label_setup(api, server, monkeypatch, tmp_path, ["all", "all", "all", "y"], 2)
    server.groups["contactGroups/other"] = {
        "resourceName": "contactGroups/other",
        "name": "Other",
        "groupType": "USER_CONTACT_GROUP",
    }
    saved[0]["memberships"].append(
        {"contactGroupMembership": {"contactGroupResourceName": "contactGroups/recruiter"}}
    )
    assert cli.main(args + ["--label", "Other"]) == 0
    out = capsys.readouterr().out
    assert "Add label Other: 1 contact" in out
    assert "Add labels Recruiter, Other: 1 contact" in out
    assert server.writes == 2


def test_mixed_creation_label_merge_and_unchanged(api, server, monkeypatch, tmp_path, capsys):
    _, inputs, saved = label_setup(api, server, monkeypatch, tmp_path, [], 3)
    saved[1]["memberships"].append(
        {"contactGroupMembership": {"contactGroupResourceName": "contactGroups/recruiter"}}
    )
    inputs[2]["organizations"] = [{"name": "New Company"}]
    inputs.append({"names": [{"givenName": "New", "familyName": "Person"}]})
    args = setup(api, server, monkeypatch, tmp_path, inputs, ["all", "y", "all", "m", "y"])
    assert cli.main(args + ["--label", "Recruiter"]) == 0
    out = capsys.readouterr().out
    assert "Contacts to create: 1" in out
    assert "Existing contacts to label: 1" in out
    assert "Existing contacts with information changes: 1" in out
    assert "Already-complete inputs skipped: 1" in out
    assert "Company after merge: New Company" in out
    assert "1 contact labeled and verified; 1 merged and verified" in out
    assert server.writes == 3


@pytest.mark.parametrize("case", ["shared", "ambiguous", "conflict"])
def test_nonroutine_candidates_stay_detailed(api, server, monkeypatch, tmp_path, capsys, case):
    _, inputs, saved = label_setup(api, server, monkeypatch, tmp_path, [], 1)
    if case == "shared":
        inputs.append(deepcopy(inputs[0]))
    elif case == "ambiguous":
        other = deepcopy(saved[0])
        other["resourceName"] = "people/c999"
        other["metadata"]["sources"][0]["id"] = "999"
        server.created[other["resourceName"]] = other
    else:
        inputs[0]["emailAddresses"][0]["type"] = "Changed"
    args = setup(api, server, monkeypatch, tmp_path, inputs, ["q"])
    assert cli.main(args + ["--label", "Recruiter"]) == 0
    out = capsys.readouterr().out
    assert "Possible match" in out
    assert "Available: add label" not in out
    assert server.writes == 0


def test_repeated_target_counted_and_written_once(api, server, monkeypatch, tmp_path, capsys):
    _, inputs, _ = label_setup(api, server, monkeypatch, tmp_path, [], 1)
    args = setup(api, server, monkeypatch, tmp_path, [inputs[0], inputs[0]], ["all", "m", "s", "y"])
    assert cli.main(args + ["--label", "Recruiter"]) == 0
    assert server.writes == 1
    assert "Existing contacts to label: 1" in capsys.readouterr().out


def test_stale_target_is_reported_and_remaining_continue(
    api, server, monkeypatch, tmp_path, capsys
):
    args, _, saved = label_setup(api, server, monkeypatch, tmp_path, [], 3)
    answers = iter(["all", "all", "y"])

    def answer():
        value = next(answers)
        if value == "y":
            saved[0]["metadata"]["sources"][0]["etag"] = "changed"
        return value

    monkeypatch.setattr("builtins.input", answer)
    assert cli.main(args) == 1
    captured = capsys.readouterr()
    assert "Contact changed since merge preview" in captured.out
    assert "2 contacts labeled and verified" in captured.out
    assert "2 of 2 processed" in captured.err
    assert server.writes == 2


@pytest.mark.parametrize("interrupt", [False, True])
def test_failed_write_or_interrupt_cleans_progress(
    api, server, monkeypatch, tmp_path, capsys, interrupt
):
    from contacts_cli import contact_merge
    from contacts_cli.errors import ContactFailure
    from contacts_cli.output import ACTIVE_PROGRESS

    args, _, _ = label_setup(api, server, monkeypatch, tmp_path, ["all", "all", "y"])
    original = contact_merge.apply_merge
    calls = 0

    def write(api, plan):
        nonlocal calls
        calls += 1
        if calls == 2:
            if interrupt:
                raise KeyboardInterrupt
            raise ContactFailure("Synthetic contact-specific failure")
        return original(api, plan)

    monkeypatch.setattr(contact_merge, "apply_merge", write)
    assert cli.main(args) == (130 if interrupt else 1)
    assert server.writes == (1 if interrupt else 2)
    assert ACTIVE_PROGRESS.get() is None
    out = capsys.readouterr().out
    if interrupt:
        assert "Remaining contacts: 1 not attempted" in out
    else:
        assert "Synthetic contact-specific failure" in out
        assert "2 contacts labeled and verified" in out


def test_new_label_is_created_only_after_confirmation(api, server, monkeypatch, tmp_path, capsys):
    args, _, _ = label_setup(api, server, monkeypatch, tmp_path, ["all", "all", "y"])
    server.groups.pop("contactGroups/recruiter")
    assert cli.main(args) == 0
    assert server.writes == 4
    out = capsys.readouterr().out
    assert "Labels to create: 1 label" in out
    assert "3 contacts labeled and verified" in out


def test_already_complete_all_skipped(api, server, monkeypatch, tmp_path, capsys):
    args, _, saved = label_setup(api, server, monkeypatch, tmp_path, ["all", "y"])
    for person in saved:
        person["memberships"].append(
            {"contactGroupMembership": {"contactGroupResourceName": "contactGroups/recruiter"}}
        )
    assert cli.main(args) == 0 and server.writes == 0
    assert "Skipped 3 unchanged inputs" in capsys.readouterr().out


def test_redirected_progress_has_no_control_codes(api, server, monkeypatch, tmp_path, capsys):
    from contacts_cli import contact_merge
    from contacts_cli.progress import StageProgress

    args, _, _ = label_setup(api, server, monkeypatch, tmp_path, ["all", "all", "y"])
    # Only progress is redirected: retain interactive command review.
    import io

    stream = io.StringIO()
    monkeypatch.setattr(contact_merge, "StageProgress", lambda: StageProgress(stream=stream))
    assert cli.main(args) == 0
    assert "3 of 3 processed" in stream.getvalue()
    assert "\r" not in stream.getvalue() and "\x1b" not in stream.getvalue()


def test_fixture_round_trip_changes_memberships_only(api, server, monkeypatch, tmp_path):
    from .test_fixture_contract import fetch

    _, _, saved = label_setup(api, server, monkeypatch, tmp_path, [], 1)
    before = deepcopy(saved[0])
    memberships = before["memberships"] + [
        {"contactGroupMembership": {"contactGroupResourceName": "contactGroups/recruiter"}}
    ]
    status, result = fetch(
        server,
        "/v1/people/c123:updateContact?updatePersonFields=memberships",
        method="PATCH",
        body={"metadata": before["metadata"], "memberships": memberships},
    )
    assert status == 200
    assert result["memberships"] == memberships
    for field in ("names", "emailAddresses", "phoneNumbers", "organizations", "photos"):
        assert result.get(field) == before.get(field)
