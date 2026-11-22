"""Full-name parsing and explicit components share input and verification rules."""

import json
from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.contact_create import verify_created
from contacts_cli.duplicate import READ_FIELDS, make_duplicate_plan, verify_duplicate
from contacts_cli.errors import SyncError

from .fake_google import FIXTURES
from .test_fixture_contract import fetch

CASES = json.loads((FIXTURES / "name-parsing.json").read_text())


def test_name_response_fixture_independently(server):
    server.created_names = [deepcopy(CASES[0]["saved"])]
    body = {"names": [{"unstructuredName": "Test Tester"}]}
    status, saved = fetch(server, "/v1/people:createContact", "POST", body)
    assert status == 200
    assert saved["names"] == [CASES[0]["saved"]]
    server.created_names[0]["givenName"] = "Changed fixture configuration"
    _, result = fetch(
        server,
        "/v1/people:batchGet?resourceNames=people/c456&personFields=names&sources=READ_SOURCE_TYPE_CONTACT",
    )
    assert result["responses"][0]["person"]["names"][0]["givenName"] == "Test"
    assert body == {"names": [{"unstructuredName": "Test Tester"}]}


@pytest.mark.parametrize("command", ["add-contact", "duplicate"])
@pytest.mark.parametrize("case", CASES, ids=[c["input"] for c in CASES])
def test_full_name_saved_and_verified(command, case, server, api, monkeypatch, capsys):
    original = deepcopy(server.person)
    server.created_names = [deepcopy(case["saved"])]
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    args = [command, "--name", case["input"], "--apply"]
    if command == "duplicate":
        args += ["--contact", "c123"]
    assert cli.main(args) == 0
    assert server.created["people/c456"]["names"] == [case["saved"]]
    assert "verified" in capsys.readouterr().out.lower()
    assert server.person == original


@pytest.mark.parametrize("command", ["add-contact", "duplicate"])
@pytest.mark.parametrize(
    "flags,expected",
    [
        (
            ["--first-name", "Test", "--last-name", "Tester"],
            {"givenName": "Test", "familyName": "Tester"},
        ),
        (["--first-name", "Test"], {"givenName": "Test"}),
        (["--last-name", "de la Tester"], {"familyName": "de la Tester"}),
    ],
)
def test_explicit_components(command, flags, expected, server, api, monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    args = [command, *flags]
    if command == "duplicate":
        args += ["--contact", "c123"]
    assert cli.main(args) == 0
    assert server.writes == 0
    output = capsys.readouterr().out
    for value in expected.values():
        assert value in output
    assert cli.main(args + ["--apply"]) == 0
    assert server.created["people/c456"]["names"] == [expected]


@pytest.mark.parametrize(
    "command,flags",
    [
        ("add-contact", ["--name", "Test Tester", "--first-name", "Test"]),
        ("duplicate", ["--name", "Test Tester", "--last-name", "Tester"]),
        ("duplicate", ["--clear-name", "--first-name", "Test"]),
        ("duplicate", ["--clear-name", "--last-name", "Tester"]),
        ("add-contact", ["--file", "unused.json", "--first-name", "Test"]),
        ("add-contact", ["--file", "unused.json", "--last-name", "Tester"]),
    ],
)
def test_name_option_conflicts(command, flags, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("connect"))
    with pytest.raises(SystemExit) as error:
        cli.main([command, *flags, *(["--contact", "c123"] if command == "duplicate" else [])])
    assert error.value.code == 2


@pytest.mark.parametrize(
    "command,flag,value",
    [
        ("add-contact", "--first-name", ""),
        ("add-contact", "--last-name", "\n"),
        ("duplicate", "--first-name", "\x7f"),
        ("duplicate", "--last-name", "   "),
    ],
)
def test_invalid_component_before_access(command, flag, value, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("connect"))
    assert (
        cli.main([command, flag, value, *(["--contact", "c123"] if command == "duplicate" else [])])
        == 1
    )


def test_unchanged_structured_name_allows_generated_full_name(server, api):
    plan = make_duplicate_plan(
        api.get_contact("people/c123", READ_FIELDS), api.people._rootDesc["schemas"]
    )
    api.duplicate(plan)
    saved = deepcopy(server.created["people/c456"])
    saved["names"][0]["unstructuredName"] = saved["names"][0]["givenName"]
    verify_duplicate(plan, saved, api.people._rootDesc["schemas"])


@pytest.mark.parametrize(
    "requested,saved",
    [
        ({"unstructuredName": "Test Tester"}, {"givenName": "Other", "displayName": "Other"}),
        (
            {"givenName": "Test", "familyName": "Tester"},
            {"givenName": "Test", "familyName": "Wrong"},
        ),
        ({"givenName": "Test"}, {"givenName": "Test", "familyName": "Old surname"}),
        ({"givenName": "Test", "middleName": "Middle"}, {"givenName": "Test"}),
    ],
)
def test_name_mismatch_rejected_by_both_verifiers(requested, saved, api):
    person = api.get_contact("people/c123", READ_FIELDS)
    plan = make_duplicate_plan(person, api.people._rootDesc["schemas"])
    plan.body["names"] = [requested]
    api.duplicate(plan)
    actual = api.get_contact("people/c456", READ_FIELDS)
    actual["names"] = [saved]
    with pytest.raises(SyncError):
        verify_duplicate(plan, actual, api.people._rootDesc["schemas"])
    with pytest.raises(SyncError):
        verify_created({"names": [requested]}, actual)
