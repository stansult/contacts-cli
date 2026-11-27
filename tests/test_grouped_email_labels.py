"""Grouped email-label decisions stay narrow and use the normal verified merge path."""

from copy import deepcopy

import pytest

from contacts_cli import cli

from .test_contact_merge import setup


def group_setup(api, server, monkeypatch, tmp_path, answers, count=2):
    base = deepcopy(server.person)
    inputs, saved = [], []
    for i in range(count):
        person = deepcopy(base)
        resource = "people/c123" if i == 0 else f"people/c{900 + i}"
        person["resourceName"] = resource
        person["metadata"]["sources"][0]["id"] = resource.removeprefix("people/c")
        person["names"] = [{"givenName": f"Person {i + 1}"}]
        person["emailAddresses"] = [
            {"value": f"Saved{i + 1}@example.com", "type": "work" if i % 2 == 0 else "WORK"}
        ]
        person["phoneNumbers"] = []
        if i == 0:
            server.person = person
        else:
            server.created[resource] = person
        saved.append(person)
        inputs.append({"emailAddresses": [{"value": f"saved{i + 1}@example.com", "type": "Event"}]})
    return setup(api, server, monkeypatch, tmp_path, inputs, answers), inputs, saved


@pytest.mark.parametrize("action", ["r", "k", "q"])
def test_group_action_avoids_individual_choices(api, server, monkeypatch, tmp_path, capsys, action):
    args, _, saved = group_setup(
        api, server, monkeypatch, tmp_path, ["all", action] + (["y"] if action == "r" else [])
    )
    assert cli.main(args) == 0
    assert server.writes == (2 if action == "r" else 0)
    assert [p["emailAddresses"][0]["type"] for p in saved] == (
        ["Event", "Event"] if action == "r" else ["work", "WORK"]
    )
    assert [p["emailAddresses"][0]["value"] for p in saved] == [
        "Saved1@example.com",
        "Saved2@example.com",
    ]
    output = capsys.readouterr().out
    assert "Available email label changes: 2 contacts" in output
    assert "Saved label: work / WORK" in output and "Incoming label: Event" in output
    assert "Choice [s]" not in output and "Choice [k]" not in output


def test_group_decline_final_approval_saves_nothing(api, server, monkeypatch, tmp_path):
    args, _, saved = group_setup(api, server, monkeypatch, tmp_path, ["all", "r", "n"])
    before = deepcopy(saved)
    assert cli.main(args) == 0 and server.writes == 0
    assert saved == before


@pytest.mark.parametrize("answer", ["", "i"])
def test_individual_fallback_keeps_existing_choices(
    api, server, monkeypatch, tmp_path, capsys, answer
):
    args, _, _ = group_setup(api, server, monkeypatch, tmp_path, ["all", answer, "s", "s"])
    assert cli.main(args) == 0 and server.writes == 0
    assert capsys.readouterr().out.count("Choice [s]") == 2


@pytest.mark.parametrize("action", ["r", "k"])
def test_partial_group_selection_leaves_others_for_review(
    api, server, monkeypatch, tmp_path, capsys, action
):
    args, _, saved = group_setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        ["all", "1,3", action, "s"] + (["y"] if action == "r" else []),
        count=3,
    )
    assert cli.main(args) == 0
    assert [p["emailAddresses"][0]["type"] for p in saved] == (
        ["Event", "WORK", "Event"] if action == "r" else ["work", "WORK", "work"]
    )
    output = capsys.readouterr().out
    assert "One entry remains; continuing with individual review." in output
    assert output.count("Choice [s]") == 1
    assert server.writes == (2 if action == "r" else 0)


@pytest.mark.parametrize("apply", [False, True])
def test_noninteractive_group_never_resolves_duplicates(
    api, server, monkeypatch, tmp_path, capsys, apply
):
    args, _, _ = group_setup(api, server, monkeypatch, tmp_path, [])
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    assert cli.main(args + (["--apply"] if apply else [])) == (1 if apply else 0)
    assert server.writes == 0 and "Choice [i]" not in capsys.readouterr().out


def test_apply_still_requires_group_action(api, server, monkeypatch, tmp_path, capsys):
    args, _, _ = group_setup(api, server, monkeypatch, tmp_path, ["r"])
    assert cli.main(args + ["--apply"]) == 0 and server.writes == 2
    assert "Choice [i]" in capsys.readouterr().out


@pytest.mark.parametrize(
    "case",
    [
        "added-field",
        "missing-saved-label",
        "display-name",
        "two-conflicts",
        "ambiguous-entry",
        "ambiguous-target",
        "input-match",
        "shared-target",
        "new-label",
        "existing-label",
    ],
)
def test_ineligible_changes_are_not_grouped(api, server, monkeypatch, tmp_path, case):
    from contacts_cli.contact_matches import duplicate_matches
    from contacts_cli.grouped_email_labels import label_groups

    args, inputs, saved = group_setup(api, server, monkeypatch, tmp_path, [])
    labels, missing = {}, []
    if case == "added-field":
        inputs[0]["urls"] = [{"value": "https://example.com/new"}]
    elif case == "missing-saved-label":
        saved[0]["emailAddresses"][0].pop("type")
    elif case == "display-name":
        saved[0]["emailAddresses"][0]["displayName"] = "Old"
        inputs[0]["emailAddresses"][0]["displayName"] = "New"
    elif case == "two-conflicts":
        saved[0]["organizations"] = [{"name": "Example", "title": "Old"}]
        inputs[0]["organizations"] = [{"name": "Example", "title": "New"}]
    elif case == "ambiguous-entry":
        saved[0]["emailAddresses"].append({**saved[0]["emailAddresses"][0], "type": "home"})
    elif case == "ambiguous-target":
        other = deepcopy(saved[0])
        other["resourceName"] = "people/c999"
        saved.append(other)
    elif case in {"input-match", "shared-target"}:
        inputs.append(deepcopy(inputs[0]))
    elif case == "new-label":
        missing = ["New"]
    elif case == "existing-label":
        labels = {"New": "contactGroups/new"}
    matches = duplicate_matches(inputs, saved)
    if case == "shared-target":
        # Independently exercise reference guarding, without the input-match guard masking it.
        matches = {
            n: [m for m in rows if not m[0].startswith("input #")] for n, rows in matches.items()
        }
    before = deepcopy((inputs, saved))
    assert (
        label_groups(
            list(range(1, len(inputs) + 1)),
            inputs,
            matches,
            {p["resourceName"]: p for p in saved},
            api.people._rootDesc["schemas"],
            labels,
            missing,
        )
        == []
    )
    assert (inputs, saved) == before and server.batch_reads == 0 and server.writes == 0


def test_group_keys_do_not_combine_different_labels(api, server, monkeypatch, tmp_path):
    from contacts_cli.contact_matches import duplicate_matches
    from contacts_cli.grouped_email_labels import label_groups

    _, inputs, saved = group_setup(api, server, monkeypatch, tmp_path, [], count=4)
    inputs[2]["emailAddresses"][0]["type"] = "event"
    inputs[3]["emailAddresses"][0]["type"] = "event"

    def groups():
        return label_groups(
            [1, 2, 3, 4],
            inputs,
            duplicate_matches(inputs, saved),
            {p["resourceName"]: p for p in saved},
            api.people._rootDesc["schemas"],
            {},
            [],
        )

    assert [[i.number for i in g] for g in groups()] == [[1, 2], [3, 4]]
    saved[3]["emailAddresses"][0]["type"] = "home"
    assert [[i.number for i in g] for g in groups()] == [[1, 2], [3, 4]]


def test_stale_group_target_never_overwrites_newer_contact(api, server, monkeypatch, tmp_path):
    args, _, saved = group_setup(api, server, monkeypatch, tmp_path, [])
    answers = iter(["all", "r", "y"])

    def answer():
        value = next(answers)
        if value == "y":
            saved[0]["metadata"]["sources"][0]["etag"] = "edited"
        return value

    monkeypatch.setattr("builtins.input", answer)
    assert cli.main(args) == 1 and server.writes == 1
    assert saved[0]["emailAddresses"][0]["type"] == "work"
    assert saved[1]["emailAddresses"][0]["type"] == "Event"


@pytest.mark.parametrize("stage", ["group", "selection"])
def test_eof_cancels_group_review(api, server, monkeypatch, tmp_path, stage):
    args, _, saved = group_setup(api, server, monkeypatch, tmp_path, [])
    before = deepcopy(saved)
    answers = iter(["all"] + (["1"] if stage == "selection" else []))

    def answer():
        try:
            return next(answers)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", answer)
    assert cli.main(args) == 0 and server.writes == 0 and saved == before


def test_group_uses_original_selected_numbers_only(api, server, monkeypatch, tmp_path, capsys):
    args, _, saved = group_setup(api, server, monkeypatch, tmp_path, ["1,3", "r", "y"], count=3)
    assert cli.main(args) == 0 and server.writes == 2
    assert saved[1]["emailAddresses"][0]["type"] == "WORK"
    group = (
        capsys.readouterr().out.split("Available email label changes:")[1].split("Choice [i]")[0]
    )
    assert "1. Person 1" in group and "3. Person 3" in group
    assert "2. Person 2" not in group


def test_group_partial_cancel_discards_prior_replacements(api, server, monkeypatch, tmp_path):
    args, _, saved = group_setup(api, server, monkeypatch, tmp_path, ["all", "1", "r", "q"])
    before = deepcopy(saved)
    assert cli.main(args) == 0 and saved == before and server.writes == 0


def test_grouped_and_individual_changes_and_new_contact(api, server, monkeypatch, tmp_path, capsys):
    _, inputs, saved = group_setup(api, server, monkeypatch, tmp_path, [], count=3)
    inputs[2]["urls"] = [{"value": "https://example.com/new"}]
    inputs.append({"names": [{"givenName": "New Person"}]})
    args = setup(api, server, monkeypatch, tmp_path, inputs, ["all", "r", "m", "k", "y"])
    assert cli.main(args) == 0 and server.writes == 4
    assert [p["emailAddresses"][0]["type"] for p in saved] == ["Event", "Event", "work"]
    assert saved[2]["urls"] == [{"value": "https://example.com/new"}]
    assert any(p["names"][0].get("givenName") == "New Person" for p in server.created.values())
    output = capsys.readouterr().out
    assert "Available email label changes: 2 contacts" in output
    assert output.count("Choice [s]") == 1 and output.count("Choice [k]") == 1


def test_group_choices_reprompt_invalid_values(api, server, monkeypatch, tmp_path, capsys):
    args, _, _ = group_setup(
        api, server, monkeypatch, tmp_path, ["all", "bad", "99", "1", "k", "s"]
    )
    assert cli.main(args) == 0 and server.writes == 0
    output = capsys.readouterr().out
    assert "Enter r, k, i, q, or displayed numbers/ranges." in output
    assert "Use only displayed item numbers." in output


def test_grouping_adds_no_contact_reads(api, server, monkeypatch, tmp_path):
    args, _, _ = group_setup(api, server, monkeypatch, tmp_path, ["all", "k"])
    assert cli.main(args) == 0
    assert server.batch_reads == 2 and server.writes == 0


def test_group_fixture_targets_are_independent(api, server, monkeypatch, tmp_path):
    from .test_fixture_contract import fetch

    _, _, saved = group_setup(api, server, monkeypatch, tmp_path, [])
    before = deepcopy(saved)
    for person in saved:
        status, result = fetch(
            server,
            "/v1/people:batchGet?resourceNames="
            + person["resourceName"]
            + "&personFields=metadata,names,emailAddresses&sources=READ_SOURCE_TYPE_CONTACT",
        )
        assert status == 200
        actual = result["responses"][0]["person"]
        assert actual["resourceName"] == person["resourceName"]
        assert actual["emailAddresses"] == person["emailAddresses"]
    second = saved[1]
    status, _ = fetch(
        server,
        "/v1/" + second["resourceName"] + ":updateContact?updatePersonFields=emailAddresses",
        "PATCH",
        {
            "metadata": {"sources": deepcopy(second["metadata"]["sources"])},
            "emailAddresses": [{**second["emailAddresses"][0], "type": "Event"}],
        },
    )
    assert status == 200 and saved[0] == before[0]
    assert saved[1]["emailAddresses"][0]["type"] == "Event"


def test_help_documents_group_choices(capsys):
    with pytest.raises(SystemExit) as result:
        cli.main(["add-contact", "--help"])
    assert result.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    assert "duplicate and label choices still prompt" in text
    assert "docs/command-reference.md#add-contact" in text


def test_direct_group_numbers_spacing_and_return(api, server, monkeypatch, tmp_path, capsys):
    args, _, saved = group_setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        ["all", "1", "n", "2-3", "r", "s", "y"],
        count=3,
    )
    assert cli.main(args) == 0
    assert [p["emailAddresses"][0]["type"] for p in saved] == ["work", "Event", "Event"]
    out = capsys.readouterr().out
    assert "Select entries by number\n" not in out
    assert "Choose email label changes:" not in out
    assert "1-3" in out
    assert "Choice [i]: \n" in out
    assert "Saved3@example.com\n\n" in out
    assert "Changes will be saved after final confirmation." in out


def test_group_apply_saving_explanation(api, server, monkeypatch, tmp_path, capsys):
    args, _, _ = group_setup(api, server, monkeypatch, tmp_path, ["q"])
    assert cli.main(args + ["--apply"]) == 0
    out = capsys.readouterr().out
    assert "With --apply, changes are saved after review without final confirmation." in out


@pytest.mark.parametrize("apply", [False, True])
def test_remaining_group_supports_multiple_subset_decisions(
    api, server, monkeypatch, tmp_path, capsys, apply
):
    answers = ([] if apply else ["all"]) + ["1", "r", "1", "2", "k", "r"]
    if not apply:
        answers += ["y"]
    args, _, saved = group_setup(api, server, monkeypatch, tmp_path, answers, count=4)
    assert cli.main(args + (["--apply"] if apply else [])) == 0
    assert [p["emailAddresses"][0]["type"] for p in saved] == ["Event", "WORK", "Event", "Event"]
    assert server.writes == 3
    out = capsys.readouterr().out
    assert "Available email label changes: 3 contacts" in out
    assert "Available email label changes: 2 contacts" in out
    assert "Use only displayed item numbers." in out
    assert "Choice [s]" not in out
    remaining = out.split("Available email label changes: 3 contacts")[1].split("Choice [i]")[0]
    assert "1. Person 1" not in remaining and "2. Person 2" in remaining
    assert "2-4" in remaining


@pytest.mark.parametrize("decision", ["i", ""])
def test_remaining_group_can_choose_individual_review(
    api, server, monkeypatch, tmp_path, capsys, decision
):
    args, _, saved = group_setup(
        api, server, monkeypatch, tmp_path, ["all", "1", "r", decision, "s", "s", "y"], count=3
    )
    assert cli.main(args) == 0 and server.writes == 1
    assert saved[0]["emailAddresses"][0]["type"] == "Event"
    out = capsys.readouterr().out
    assert "Available email label changes: 2 contacts" in out
    assert out.count("Choice [s]") == 2


@pytest.mark.parametrize("end", ["q", "eof"])
def test_cancel_remaining_group_discards_plans(api, server, monkeypatch, tmp_path, end):
    args, _, saved = group_setup(api, server, monkeypatch, tmp_path, [], count=3)
    before = deepcopy(saved)
    answers = iter(["all", "1", "r"] + (["q"] if end == "q" else []))

    def answer():
        try:
            return next(answers)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", answer)
    assert cli.main(args) == 0 and server.writes == 0 and saved == before


@pytest.mark.parametrize("last,expected", [("r", 4), ("k", 1)])
def test_group_distinguishes_available_reviewing_selected(
    api, server, monkeypatch, tmp_path, capsys, last, expected
):
    args, _, _ = group_setup(
        api, server, monkeypatch, tmp_path, ["all", "1", "r", last, "y"], count=4
    )
    assert cli.main(args) == 0 and server.writes == expected
    out = capsys.readouterr().out
    assert "Available email label changes: 4 contacts" in out
    assert "Reviewing selection: 1 contact" in out
    assert "Selected label replacements: 1 contact." in out
    assert f"Total selected label replacements: {expected} contact" in out
    assert "Not saved yet." in out
    if last == "r":
        assert "Selected label replacements: 3 more contacts." in out
    refreshed = out.split("Available email label changes: 3 contacts")[1]
    assert "Saved4@example.com\n\n  r" in refreshed
    assert "Saved4@example.com\n\n\n" not in refreshed
    assert "Continuing with individual contact review." not in out


def test_group_transition_explains_individual_review(api, server, monkeypatch, tmp_path, capsys):
    _, inputs, _ = group_setup(api, server, monkeypatch, tmp_path, [], count=3)
    inputs[2]["urls"] = [{"value": "https://example.com/new"}]
    args = setup(api, server, monkeypatch, tmp_path, inputs, ["all", "r", "s", "y"])
    assert cli.main(args) == 0 and server.writes == 2
    out = capsys.readouterr().out
    summary = out.index("Total selected label replacements: 2 contacts. Not saved yet.")
    transition = out.index("\n\nContinuing with individual contact review.\n\n", summary)
    assert out.index("3. Unnamed contact — possible match:", transition) > transition
    assert out.index("Person 3 (c902)", transition) > transition


def test_return_from_subset_has_one_menu_separator(api, server, monkeypatch, tmp_path, capsys):
    args, _, _ = group_setup(api, server, monkeypatch, tmp_path, ["all", "1", "n", "q"])
    assert cli.main(args) == 0 and server.writes == 0
    out = capsys.readouterr().out
    assert "Saved2@example.com\n\n  r" in out
    assert "Saved2@example.com\n\n\n" not in out


def test_group_range_ignores_already_reviewed_numbers(api, server, monkeypatch, tmp_path, capsys):
    args, _, saved = group_setup(
        api, server, monkeypatch, tmp_path, ["all", "2", "k", "1-100", "r", "y"], count=4
    )
    assert cli.main(args) == 0 and server.writes == 3
    assert [p["emailAddresses"][0]["type"] for p in saved] == ["Event", "WORK", "Event", "Event"]
    out = capsys.readouterr().out
    assert "Use only displayed item numbers." not in out


@pytest.mark.parametrize("action", ["r", "k"])
def test_different_saved_labels_share_group(api, server, monkeypatch, tmp_path, capsys, action):
    args, _, saved = group_setup(
        api, server, monkeypatch, tmp_path, ["all", "3", action, "r", "y"], count=3
    )
    saved[2]["emailAddresses"][0]["type"] = "OTHER"
    assert cli.main(args) == 0
    assert server.writes == (3 if action == "r" else 2)
    assert [p["emailAddresses"][0]["type"] for p in saved] == [
        "Event",
        "Event",
        "Event" if action == "r" else "OTHER",
    ]
    out = capsys.readouterr().out
    assert "Available email label changes: 3 contacts" in out
    assert "Person 3 — Saved3@example.com — saved label: OTHER" in out
    assert "Person 1 — Saved1@example.com — saved label: work" in out
    subset = out.split("Reviewing selection: 1 contact")[1].split("Choice [n]")[0]
    assert "saved label: OTHER" in subset
    assert "Choice [s]" not in out
