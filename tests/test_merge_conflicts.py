"""Explicit conflict choices preserve complete entries and require approved writes."""

from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.contact_merge import merge_values

from .test_contact_merge import incoming, setup


@pytest.mark.parametrize("choice", ["k", "r", "b"])
def test_company_conflict_choices(choice):
    old = {"organizations": [{"name": "Example", "title": "Engineer", "department": "Tools"}]}
    new = {"organizations": [{"name": "Example", "title": "Senior Engineer", "location": "Irvine"}]}
    before = deepcopy(old)
    result, _, _ = merge_values(old, new, resolver=lambda conflict: choice)
    assert old == before
    values = result["organizations"]
    if choice == "b":
        assert values == before["organizations"] + new["organizations"]
    else:
        assert values == [
            {
                "name": "Example",
                "title": "Senior Engineer" if choice == "r" else "Engineer",
                "department": "Tools",
                "location": "Irvine",
            }
        ]


@pytest.mark.parametrize("choice", ["k", "r", "b", "q"])
def test_conflicts_visible_before_choice_and_resolved_before_write(
    api, server, monkeypatch, tmp_path, capsys, choice
):
    server.person["organizations"] = [{"name": "Example", "title": "Old"}]
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server, organizations=[{"name": "Example", "title": "New"}])],
        [],
    )
    answers = iter(["m", choice] + (["y"] if choice in {"r", "b"} else []))
    first = True

    def answer():
        nonlocal first
        if first:
            output = capsys.readouterr().out
            assert "Saved:" in output and "Incoming:" in output
            assert "Old" in output and "New" in output
            assert "  m   Merge" in output
            first = False
        assert server.writes == 0
        return next(answers)

    monkeypatch.setattr("builtins.input", answer)
    assert cli.main(args) == 0
    assert server.writes == int(choice in {"r", "b"})
    expected = (
        [{"name": "Example", "title": "New"}]
        if choice == "r"
        else [{"name": "Example", "title": "Old"}]
    )
    if choice == "b":
        expected.append({"name": "Example", "title": "New"})
    assert server.person["organizations"] == expected


@pytest.mark.parametrize(
    "field,old,new",
    [
        (
            "names",
            {"givenName": "Old", "familyName": "Person"},
            {"unstructuredName": "New Different Person"},
        ),
        ("biographies", {"value": "Old"}, {"value": "New"}),
        (
            "birthdays",
            {"date": {"year": 1990, "month": 1, "day": 1}},
            {"date": {"month": 2, "day": 3}},
        ),
    ],
)
def test_singleton_replace_is_atomic_and_both_rejected(field, old, new):
    from contacts_cli.errors import SyncError

    result, _, _ = merge_values({field: [old]}, {field: [new]}, resolver=lambda c: "r")
    assert result[field] == [new]
    with pytest.raises(SyncError, match="Unsupported"):
        merge_values({field: [old]}, {field: [new]}, resolver=lambda c: "b")


@pytest.mark.parametrize(
    "field,value", [("emailAddresses", "a@example.com"), ("phoneNumbers", "+12025550123")]
)
def test_both_preserves_complete_entry_and_primary(field, value):
    old = {"value": value, "type": "work", "metadata": {"sourcePrimary": True}}
    new = (
        {"value": value, "type": "home", "displayName": "Incoming"}
        if field == "emailAddresses"
        else {"value": value, "type": "home"}
    )
    for choice in ["r", "b"]:
        result, _, _ = merge_values(
            {field: [old]}, {field: [new]}, resolver=lambda c, choice=choice: choice
        )
        assert result[field][0]["metadata"]["sourcePrimary"] is True
        if choice == "b":
            assert result[field] == [old, new] and "metadata" not in result[field][1]
        else:
            assert len(result[field]) == 1 and result[field][0]["type"] == "home"


def test_replace_one_ambiguous_entry_preserves_others():
    old = {
        "emailAddresses": [
            {"value": "a@example.com", "type": "work"},
            {"value": "a@example.com", "type": "home"},
        ]
    }
    new = {"emailAddresses": [{"value": "a@example.com", "type": "custom"}]}
    result, _, _ = merge_values(old, new, resolver=lambda c: ("r", 1))
    assert result["emailAddresses"] == [old["emailAddresses"][0], new["emailAddresses"][0]]


@pytest.mark.parametrize("answer", ["n", "q", None])
def test_conflict_cancel_or_final_decline_never_writes(
    api, server, monkeypatch, tmp_path, capsys, answer
):
    server.person["organizations"] = [{"name": "Example", "title": "Old"}]
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server, organizations=[{"name": "Example", "title": "New"}])],
        [],
    )
    answers = iter(["m", "r", "n"] if answer == "n" else ["m", answer])

    def respond():
        value = next(answers)
        if value is None:
            raise EOFError
        return value

    monkeypatch.setattr("builtins.input", respond)
    assert cli.main(args) == 0 and server.writes == 0
    output = capsys.readouterr().out
    if answer == "n":
        assert "Company after merge: Example; Title: New" in output
    assert server.person["organizations"][0]["title"] == "Old"


def test_singleton_ui_rejects_both_and_defaults_keep(api, server, monkeypatch, tmp_path, capsys):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server, names=[{"givenName": "Different"}])],
        ["m", "b", ""],
    )
    assert cli.main(args) == 0 and server.writes == 0
    output = capsys.readouterr().out
    assert "Choose k, r, or q." in output
    assert "b   Keep both" not in output


@pytest.mark.parametrize("apply", [False, True])
def test_both_email_round_trip_and_explicit_choice_even_apply(
    api, server, monkeypatch, tmp_path, capsys, apply
):
    address = server.person["emailAddresses"][0]["value"]
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [{"emailAddresses": [{"value": address, "type": "custom"}]}],
        ["m", "b"] + ([] if apply else ["y"]),
    )
    assert cli.main(args + (["--apply"] if apply else [])) == 0
    assert len([e for e in server.person["emailAddresses"] if e["value"] == address]) == 2
    assert "Keep both labels as two email entries" in capsys.readouterr().out


@pytest.mark.parametrize("kind", ["name", "primary-email"])
def test_replacement_verified_with_primary_and_unrelated_data(
    api, server, monkeypatch, tmp_path, kind
):
    before = deepcopy(server.person)
    if kind == "name":
        person = incoming(server, names=[{"givenName": "Replacement", "familyName": "Person"}])
    else:
        server.person["emailAddresses"][0].setdefault("metadata", {})["sourcePrimary"] = True
        person = {
            "emailAddresses": [
                {"value": server.person["emailAddresses"][0]["value"], "type": "custom"}
            ]
        }
    args = setup(api, server, monkeypatch, tmp_path, [person], ["m", "r", "y"])
    assert cli.main(args) == 0 and server.writes == 1
    assert server.person.get("phoneNumbers") == before.get("phoneNumbers")
    assert server.person.get("memberships") == before.get("memberships")
    if kind == "name":
        assert server.person["names"][0]["givenName"] == "Replacement"
    else:
        assert server.person["emailAddresses"][0]["type"] == "custom"
        assert server.person["emailAddresses"][0]["metadata"]["sourcePrimary"] is True


def test_choose_which_duplicate_to_replace_and_cancel(monkeypatch):
    from contacts_cli.merge_conflicts import Conflict, MergeCancelled, choose_conflict

    conflict = Conflict(
        "emailAddresses",
        [0, 1],
        [{"value": "a@example.com", "type": "work"}, {"value": "a@example.com", "type": "home"}],
        {"value": "a@example.com", "type": "new"},
        [],
    )
    answers = iter(["r", "0", "bad", "2"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    assert choose_conflict(conflict) == ("r", 1)
    answers = iter(["r", "q"])
    with pytest.raises(MergeCancelled):
        choose_conflict(conflict)


def test_combined_inputs_conflict_can_replace_before_creation(api, server, monkeypatch, tmp_path):
    inputs = [
        {
            "names": [{"givenName": "New", "familyName": "Person"}],
            "organizations": [{"name": "Example", "title": title}],
        }
        for title in ["Old", "New"]
    ]
    args = setup(api, server, monkeypatch, tmp_path, inputs, ["all", "m", "r", "y"])
    assert cli.main(args) == 0 and len(server.created) == 1
    saved = next(iter(server.created.values()))
    assert saved["organizations"][0]["title"] == "New"


def test_cancel_after_prior_planned_replacement_discards_whole_plan(
    api, server, monkeypatch, tmp_path
):
    inputs = [incoming(server, names=[{"givenName": name}]) for name in ["First", "Second"]]
    before = deepcopy(server.person)
    args = setup(api, server, monkeypatch, tmp_path, inputs, ["all", "m", "r", "m", "q"])
    assert cli.main(args) == 0 and server.writes == 0
    assert server.person == before


def test_verification_rejects_lost_both_entry(api, server):
    from contacts_cli.contact_merge import MergePlan, verify_merge
    from contacts_cli.duplicate import copy_body
    from contacts_cli.errors import SyncError, WriteUnverified

    original = deepcopy(server.person)
    body = copy_body(original, api.people._rootDesc["schemas"])
    address = body["emailAddresses"][0]["value"]
    expected, _, _ = merge_values(
        body, {"emailAddresses": [{"value": address, "type": "custom"}]}, resolver=lambda c: "b"
    )
    plan = MergePlan(original, expected)
    with pytest.raises((SyncError, WriteUnverified)):
        verify_merge(plan, original, api.people._rootDesc["schemas"])


def test_fixture_round_trips_replaced_company_and_duplicate_emails(server):
    from .test_fixture_contract import fetch

    original = deepcopy(server.person)
    body = {
        "metadata": {"sources": [{"etag": "source-v1"}]},
        "organizations": [{"name": "Example", "title": "New"}],
        "emailAddresses": [
            {"value": "a@example.com", "type": "work", "metadata": {"sourcePrimary": True}},
            {"value": "a@example.com", "type": "home"},
        ],
    }
    status, saved = fetch(
        server,
        "/v1/people/c123:updateContact?updatePersonFields=organizations,emailAddresses",
        "PATCH",
        body,
    )
    assert status == 200
    status, reread = fetch(
        server,
        "/v1/people:batchGet?resourceNames=people/c123&personFields=organizations,emailAddresses&sources=READ_SOURCE_TYPE_CONTACT",
    )
    assert status == 200
    for field in ["organizations", "emailAddresses"]:
        assert saved[field] == body[field] == reread["responses"][0]["person"][field]
    assert server.person["phoneNumbers"] == original["phoneNumbers"]


def test_interrupt_conflict_after_prior_choice_saves_nothing(
    api, server, monkeypatch, tmp_path, capsys
):
    inputs = [incoming(server, names=[{"givenName": name}]) for name in ["First", "Second"]]
    args = setup(api, server, monkeypatch, tmp_path, inputs, [])
    before = deepcopy(server.person)
    answers = iter(["all", "m", "r", "m"])
    prompts = []

    def respond():
        assert server.writes == 0
        try:
            return next(answers)
        except StopIteration:
            prompts.append(capsys.readouterr().out)
            raise KeyboardInterrupt from None

    monkeypatch.setattr("builtins.input", respond)
    assert cli.main(args) == 130
    assert len(prompts) == 1 and "Choose an option (Enter = keep saved values):" in prompts[0]
    assert "First" in prompts[0] and "Second" in prompts[0]
    assert server.writes == 0 and server.person == before
    assert "no contact changes made" in capsys.readouterr().err


def test_keep_both_crossing_size_limit_stops_before_write(
    api, server, monkeypatch, tmp_path, capsys
):
    from contacts_cli.duplicate import copy_body

    server.person["organizations"] = [{"name": "Example", "title": "Old"}]
    body = copy_body(server.person, api.people._rootDesc["schemas"])
    count = sum(len(v) for v in body.values() if isinstance(v, list))
    server.person.setdefault("userDefined", []).extend(
        {"key": f"Fixture {i}", "value": "x"} for i in range(500 - count)
    )
    body = copy_body(server.person, api.people._rootDesc["schemas"])
    assert sum(len(v) for v in body.values() if isinstance(v, list)) == 500
    before = deepcopy(server.person)
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server, organizations=[{"name": "Example", "title": "New"}])],
        ["m", "b", "y"],
    )
    assert cli.main(args) == 1
    output = capsys.readouterr()
    assert "500-entry or 128-KiB size guard" in output.err
    assert "Choose an option (Enter = keep saved values):" in output.out
    assert "Apply these changes?" not in output.err
    assert server.writes == 0 and server.person == before


def test_mixed_conflict_decisions_save_complete_expected_result(api, server, monkeypatch, tmp_path):
    server.person["organizations"] = [{"name": "Example", "title": "Old", "department": "Tools"}]
    server.person["phoneNumbers"] = [{"value": "+12025550123", "type": "work"}]
    before = deepcopy(server.person)
    address = before["emailAddresses"][0]["value"]
    person = {
        "emailAddresses": [{"value": address, "type": "custom"}],
        "organizations": [{"name": "Example", "title": "New"}],
        "phoneNumbers": [{"value": "+12025550123", "type": "home"}],
    }
    args = setup(api, server, monkeypatch, tmp_path, [person], ["m", "k", "r", "b", "y"])
    assert cli.main(args) == 0 and server.writes == 1
    expected = deepcopy(before)
    expected["organizations"][0]["title"] = "New"
    expected["phoneNumbers"].append(person["phoneNumbers"][0])
    expected["metadata"]["sources"][0]["etag"] = "written-1"
    assert server.person == expected


@pytest.mark.parametrize(
    "saved,incoming_address",
    [("chris@example.com", "Chris@Example.COM"), ("Chris@Example.COM", "chris@example.com")],
)
def test_replace_email_label_preserves_saved_spelling(saved, incoming_address):
    old = {
        "emailAddresses": [
            {
                "value": saved,
                "type": "work",
                "displayName": "Saved name",
                "metadata": {"sourcePrimary": True},
            }
        ]
    }
    new = {"emailAddresses": [{"value": incoming_address, "type": "Event"}]}
    result, changes, conflicts = merge_values(old, new, resolver=lambda c: "r")
    assert result == {"emailAddresses": [{**old["emailAddresses"][0], "type": "Event"}]}
    assert changes and not conflicts
    assert incoming_address not in "\n".join(changes)


def test_case_only_email_change_needs_no_resolution():
    old = {"emailAddresses": [{"value": "Saved@Example.COM", "type": "work"}]}

    def unexpected(conflict):
        pytest.fail("Capitalization alone must not require a conflict choice")

    result, changes, conflicts = merge_values(
        old,
        {"emailAddresses": [{"value": "saved@example.com", "type": "work"}]},
        resolver=unexpected,
    )
    assert result == old and not changes and not conflicts


def test_replace_email_label_case_variant_round_trip(api, server, monkeypatch, tmp_path, capsys):
    from contacts_cli.duplicate import copy_body

    old = copy_body(server.person, api.people._rootDesc["schemas"])["emailAddresses"]
    address = old[0]["value"]
    variant = address.swapcase()
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [{"emailAddresses": [{"value": variant, "type": "Event"}]}],
        ["m", "r", "y"],
    )
    assert cli.main(args) == 0 and server.writes == 1
    expected = deepcopy(old)
    expected[0]["type"] = "Event"
    assert server.person["emailAddresses"] == expected
    final = capsys.readouterr().out.split("Contacts to update:")[1]
    assert address in final and variant not in final
