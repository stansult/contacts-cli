"""New-contact validation follows the supported Person contract without Google calls."""

import json
from pathlib import Path

import pytest
from googleapiclient.discovery_cache import get_static_doc

from contacts_cli import cli
from contacts_cli.contact_inputs import FIELDS, load_contact_inputs, validate_contacts
from contacts_cli.errors import SyncError

FIXTURE = Path(__file__).parent / "fixtures" / "new-contact.json"


def test_fixture_contract_and_preservation():
    person = json.loads(FIXTURE.read_text())
    schemas = json.loads(get_static_doc("people", "v1"))["schemas"]
    assert set(person) == FIELDS
    for field, entries in person.items():
        schema = schemas[schemas["Person"]["properties"][field]["items"]["$ref"]]
        assert entries
        assert all(
            key in schema["properties"] and not schema["properties"][key].get("readOnly")
            for entry in entries
            for key in entry
        )
    assert person["birthdays"] == [{"date": {"month": 2, "day": 29}}]
    assert person["phoneNumbers"][0]["value"].endswith("ext. 42")
    assert len(person["userDefined"]) == 2
    assert person["nicknames"] == [{"value": "J"}]
    result = validate_contacts(person)
    assert result == [person]
    result[0]["names"][0]["givenName"] = "Changed"
    assert person["names"][0]["givenName"] == "Jane"


@pytest.mark.parametrize(
    "field,entry,path",
    [
        ("emailAddresses", {"value": "bad"}, "emailAddresses[0].value"),
        ("emailAddresses", {"value": "email@1"}, "emailAddresses[0].value"),
        ("emailAddresses", {"value": "email@localhost"}, "emailAddresses[0].value"),
        ("phoneNumbers", {"value": "not a number"}, "phoneNumbers[0].value"),
        ("urls", {"value": "ftp://example.com"}, "urls[0].value"),
        ("urls", {"value": "https://[broken"}, "urls[0].value"),
        ("names", {"givenName": " "}, "names[0].givenName"),
        ("names", {"displayName": "Jane"}, "names[0].displayName"),
        (
            "emailAddresses",
            {"value": "a@example.com", "metadata": {}},
            "emailAddresses[0].metadata",
        ),
        ("userDefined", {"key": "Pipeline ID"}, "userDefined[0].value"),
        ("addresses", {"city": 123}, "addresses[0].city"),
        ("addresses", {"type": "work"}, "addresses[0]"),
        ("organizations", {"name": "Company", "current": "yes"}, "organizations[0].current"),
        ("birthdays", {"date": {"year": 2023, "month": 2, "day": 29}}, "birthdays[0].date"),
        ("events", {"date": {"month": True, "day": 1}}, "events[0].date.month"),
        ("events", {"date": {"month": 2}}, "events[0].date"),
        ("birthdays", {"text": "sometime"}, "birthdays[0].text"),
        ("nicknames", {"value": "J", "type": "invented"}, "nicknames[0].type"),
    ],
)
def test_invalid_values_report_exact_location(field, entry, path):
    person = {"names": [{"givenName": "Jane"}], field: [entry]}
    with pytest.raises(SyncError) as error:
        validate_contacts([{"emailAddresses": [{"value": "valid@example.com"}]}, person])
    assert f"Contact #2 → {path}:" in str(error.value)


@pytest.mark.parametrize(
    "person",
    [
        {},
        [],
        None,
        {"names": {}},
        {"names": [None]},
        {"resourceName": "people/c123"},
        {"names": [{"givenName": "A"}, {"givenName": "B"}]},
        {"userDefined": [{"key": "Key", "value": "Value"}]},
        {"names": [{"givenName": "Jane\u001b"}]},
        {"names": [{"givenName": "\ud800"}]},
    ],
)
def test_invalid_structure_and_identity(person):
    with pytest.raises(SyncError):
        validate_contacts(person)


@pytest.mark.parametrize(
    "date",
    [
        {"year": 2024, "month": 2, "day": 29},
        {"month": 2, "day": 29},
        {"year": 2000},
        {"year": 2000, "month": 5},
    ],
)
def test_supported_partial_dates(date):
    person = {"names": [{"givenName": "Jane"}], "events": [{"date": date}]}
    assert validate_contacts(person) == [person]


def test_size_guards():
    person = {"names": [{"givenName": "Jane"}], "userDefined": [{"key": "k", "value": "v"}] * 500}
    with pytest.raises(SyncError, match="500-entry"):
        validate_contacts(person)
    with pytest.raises(SyncError, match="128-KiB"):
        validate_contacts(
            {"names": [{"givenName": "Jane"}], "biographies": [{"value": "x" * 131072}]}
        )


@pytest.mark.parametrize("content", [b"\xff", b"{", b'{"names":[],"names":[]}', b'{"names":NaN}'])
def test_bad_files(tmp_path, content):
    file = tmp_path / "bad.json"
    file.write_bytes(content)
    with pytest.raises(SyncError):
        load_contact_inputs(file=file)


def test_missing_file(tmp_path):
    with pytest.raises(SyncError, match="could not read"):
        load_contact_inputs(file=tmp_path / "missing.json")


@pytest.mark.parametrize("command", ["add-contact", "add-contacts"])
def test_invalid_file_cli_is_offline(command, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("connection"))
    data = json.loads(FIXTURE.read_text())
    data["emailAddresses"] = [{"value": "invalid"}]
    file = tmp_path / "contacts.json"
    file.write_text(json.dumps([json.loads(FIXTURE.read_text()), data]))
    assert cli.main([command, "--file", str(file)]) == 1
    assert "Contact #2" in capsys.readouterr().err


@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--file", "x", "--name", "Jane"],
        ["--file", "x", "--email", "a@example.com"],
    ],
)
def test_invalid_cli_combinations(extra):
    with pytest.raises(SystemExit) as error:
        cli.main(["add-contact", *extra])
    assert error.value.code == 2


@pytest.mark.parametrize("address", ["email@1", "email@localhost", "a.b@localhost"])
def test_shared_address_requires_dotted_domain(address):
    from contacts_cli.address_inputs import bare_address

    with pytest.raises(SyncError, match="dotted domain"):
        bare_address(address)


@pytest.mark.parametrize("address", ["email@example.com", "email@sub.example.com"])
def test_shared_address_accepts_dotted_domain(address):
    from contacts_cli.address_inputs import bare_address

    assert bare_address(address) == address


@pytest.mark.parametrize("command", ["validate-contact", "validate-contacts"])
def test_validate_command_is_local(command, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("connection"))
    monkeypatch.setattr(cli, "authorize", lambda *a, **k: pytest.fail("authorization"))
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("prompt"))
    assert cli.main([command, "--file", str(FIXTURE)]) == 0
    assert "Valid: 1 contact." in capsys.readouterr().out
    file = tmp_path / "contacts.json"
    person = json.loads(FIXTURE.read_text())
    file.write_text(json.dumps([person, person]))
    assert cli.main([command, "--file", str(file)]) == 0
    assert "Valid: 2 contacts." in capsys.readouterr().out
    person["emailAddresses"] = [{"value": "bad"}]
    file.write_text(json.dumps([json.loads(FIXTURE.read_text()), person]))
    assert cli.main([command, "--file", str(file)]) == 1
    output = capsys.readouterr()
    assert "Contact #2 → emailAddresses[0].value" in output.err
    assert "Valid:" not in output.out
    assert cli.main([command, "--file", str(tmp_path / "missing.json")]) == 1


@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--file", "x", "--name", "Jane"],
        ["--file", "x", "--apply"],
        ["--file", "x", "--label", "New"],
    ],
)
def test_validate_requires_file_only(extra):
    with pytest.raises(SystemExit) as error:
        cli.main(["validate-contact", *extra])
    assert error.value.code == 2


def test_validate_alias_help_is_singular(capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["validate-contacts", "--help"])
    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "validate-contact " in output
    assert "validate-contacts" not in output
