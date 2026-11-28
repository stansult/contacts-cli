"""Conflict-free bulk decisions use ordinary merge verification without live Google access."""

from copy import deepcopy

import pytest

from contacts_cli import cli

from .test_contact_merge import setup
from .test_grouped_email_labels import group_setup


def additions_setup(api, server, monkeypatch, tmp_path, answers, count=3):
    _, inputs, saved = group_setup(api, server, monkeypatch, tmp_path, [], count=count)
    for person, original in zip(inputs, saved, strict=True):
        person["emailAddresses"][0]["type"] = original["emailAddresses"][0]["type"]
        person["names"] = deepcopy(original["names"])
        person["organizations"] = [{"name": "Example Company"}]
    return setup(api, server, monkeypatch, tmp_path, inputs, answers), inputs, saved


@pytest.mark.parametrize("action", ["m", "s", "q"])
def test_bulk_additions_actions(api, server, monkeypatch, tmp_path, capsys, action):
    args, _, saved = additions_setup(
        api, server, monkeypatch, tmp_path, ["all", action] + (["y"] if action == "m" else [])
    )
    before = deepcopy(saved)
    assert cli.main(args) == 0
    assert server.writes == (3 if action == "m" else 0)
    out = capsys.readouterr().out
    assert "Available merges without conflicts: 3 contacts" in out
    assert "Target: Person 1 (c123)" in out and "Add Company: Example Company" in out
    assert "Choose an option (Enter = skip this input)" not in out
    if action != "m":
        assert saved == before
    else:
        assert all(p["organizations"] == [{"name": "Example Company"}] for p in saved)


def test_subset_then_remaining_and_invalid_number(api, server, monkeypatch, tmp_path, capsys):
    args, _, saved = additions_setup(
        api, server, monkeypatch, tmp_path, ["all", "2", "s", "2", "1-100", "m", "y"], count=4
    )
    assert cli.main(args) == 0 and server.writes == 3
    assert not saved[1].get("organizations")
    out = capsys.readouterr().out
    assert "Available merges without conflicts: 3 contacts" in out
    assert "Use only displayed item numbers." in out
    assert "Selected merges: 3 contacts. Not saved yet." in out


@pytest.mark.parametrize("choice", ["i", ""])
def test_individual_option(api, server, monkeypatch, tmp_path, capsys, choice):
    args, _, _ = additions_setup(api, server, monkeypatch, tmp_path, ["all", choice, "s", "s", "s"])
    assert cli.main(args) == 0 and server.writes == 0
    assert capsys.readouterr().out.count("Choose an option (Enter = skip this input)") == 3


@pytest.mark.parametrize("last", ["q", EOFError()])
def test_cancel_after_subset_discards_plan(api, server, monkeypatch, tmp_path, last):
    args, _, saved = additions_setup(api, server, monkeypatch, tmp_path, [])
    before = deepcopy(saved)
    answers = iter(["all", "1", "m", last])

    def answer():
        value = next(answers)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr("builtins.input", answer)
    assert cli.main(args) == 0 and server.writes == 0 and saved == before


@pytest.mark.parametrize("apply", [False, True])
def test_final_confirmation_and_apply(api, server, monkeypatch, tmp_path, apply):
    answers = ["m"] if apply else ["all", "m", "n"]
    args, _, _ = additions_setup(api, server, monkeypatch, tmp_path, answers)
    assert cli.main(args + (["--apply"] if apply else [])) == 0
    assert server.writes == (3 if apply else 0)


@pytest.mark.parametrize(
    "case", ["conflict", "shared", "ambiguous", "input", "no-change", "uncached", "planned"]
)
def test_eligibility_requires_independent_unambiguous_targets(
    api, server, monkeypatch, tmp_path, case
):
    from contacts_cli.contact_matches import duplicate_matches
    from contacts_cli.contact_merge import ImportReview, MergePlan
    from contacts_cli.grouped_additions import additive_candidates

    _, inputs, saved = additions_setup(api, server, monkeypatch, tmp_path, [])
    matches = duplicate_matches(inputs, saved)
    assert all(len(rows) == 1 for rows in matches.values())
    details = {p["resourceName"]: p for p in saved}
    review = ImportReview()
    if case == "conflict":
        inputs[0]["emailAddresses"][0]["type"] = "Different"
    elif case == "shared":
        matches[2] = matches[1]
    elif case == "ambiguous":
        matches[1] += matches[2]
    elif case == "input":
        matches[1] = [("input #2", inputs[1], ["name"])]
    elif case == "no-change":
        inputs[0].pop("organizations")
    elif case == "uncached":
        details.pop(saved[0]["resourceName"])
    else:
        review.merges[saved[0]["resourceName"]] = MergePlan(saved[0], {})
    before = deepcopy((inputs, saved))
    candidates = additive_candidates(
        [1, 2, 3], inputs, matches, details, api.people._rootDesc["schemas"], {}, [], review
    )
    assert 1 not in [item.number for item in candidates]
    assert (inputs, saved) == before and server.writes == 0 and server.batch_reads == 0


def test_single_remainder_is_reviewed_individually(api, server, monkeypatch, tmp_path, capsys):
    args, _, _ = additions_setup(api, server, monkeypatch, tmp_path, ["all", "1-2", "m", "s", "y"])
    assert cli.main(args) == 0 and server.writes == 2
    out = capsys.readouterr().out
    assert "One entry remains for individual review." in out
    assert out.count("Choose an option (Enter = skip this input)") == 1


def test_return_to_group_keeps_original_numbers(api, server, monkeypatch, tmp_path, capsys):
    args, _, _ = additions_setup(
        api, server, monkeypatch, tmp_path, ["all", "2", "n", "1,3", "s", "s"]
    )
    assert cli.main(args) == 0 and server.writes == 0
    assert "Skipped 2 inputs." in capsys.readouterr().out


def test_mixed_label_additive_conflict_and_new(api, server, monkeypatch, tmp_path, capsys):
    _, inputs, saved = additions_setup(api, server, monkeypatch, tmp_path, [], count=5)
    for person in inputs[:2]:
        person.pop("organizations")
        person["emailAddresses"][0]["type"] = "Event"
    inputs[4]["names"] = [{"givenName": "Different"}]
    inputs.append({"names": [{"givenName": "Brand New"}]})
    args = setup(api, server, monkeypatch, tmp_path, inputs, ["all", "r", "m", "s", "y"])
    assert cli.main(args) == 0 and server.writes == 5
    assert saved[0]["emailAddresses"][0]["type"] == "Event"
    assert saved[2]["organizations"] == [{"name": "Example Company"}]
    assert not saved[4].get("organizations")
    out = capsys.readouterr().out
    assert (
        out.index("Available email label changes")
        < out.index("Available merges without conflicts")
        < out.index("Continuing with individual contact review")
    )
    assert out.count("Continuing with individual contact review") == 1


@pytest.mark.parametrize("apply", [False, True])
def test_noninteractive_does_not_bulk_decide(api, server, monkeypatch, tmp_path, capsys, apply):
    args, _, _ = additions_setup(api, server, monkeypatch, tmp_path, [])
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    assert cli.main(args + (["--apply"] if apply else [])) == (1 if apply else 0)
    assert server.writes == 0
    assert "Available merges without conflicts" not in capsys.readouterr().out


def test_grouping_uses_cached_reads(api, server, monkeypatch, tmp_path):
    args, _, _ = additions_setup(api, server, monkeypatch, tmp_path, ["all", "s"])
    assert cli.main(args) == 0 and server.batch_reads == 3 and server.writes == 0


def test_stale_contact_is_not_overwritten(api, server, monkeypatch, tmp_path):
    args, _, saved = additions_setup(api, server, monkeypatch, tmp_path, [])
    answers = iter(["all", "m", "y"])

    def answer():
        value = next(answers)
        if value == "y":
            saved[0]["metadata"]["sources"][0]["etag"] = "changed"
        return value

    monkeypatch.setattr("builtins.input", answer)
    assert cli.main(args) == 1 and server.writes == 2
    assert not saved[0].get("organizations")


@pytest.mark.parametrize("new", [False, True])
def test_contact_labels_are_previewed_and_applied(api, server, monkeypatch, tmp_path, capsys, new):
    args, _, saved = additions_setup(api, server, monkeypatch, tmp_path, ["all", "m", "y"])
    if not new:
        server.groups["contactGroups/example"] = {
            "resourceName": "contactGroups/example",
            "name": "Example",
            "groupType": "USER_CONTACT_GROUP",
        }
    assert cli.main(args + ["--label", "Example"]) == 0
    out = capsys.readouterr().out
    assert "Add contact label: Example" in out
    assert "(new label)" in out if new else "(new label)" not in out
    assert all(p["organizations"] for p in saved)
