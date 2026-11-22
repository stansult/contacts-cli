"""Duplicate overrides replace whole fields without changing the source."""

from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.duplicate import READ_FIELDS, make_duplicate_plan, verify_duplicate
from contacts_cli.errors import SyncError

from .test_fixture_contract import fetch


def test_empty_copy_fields_fixture_contract(server):
    original = deepcopy(server.person)
    status, created = fetch(
        server,
        "/v1/people:createContact",
        "POST",
        {
            "userDefined": [
                {"key": "Duplicate", "value": "Synthetic marker"},
            ]
        },
    )
    assert status == 200
    _, result = fetch(
        server,
        "/v1/people:batchGet?resourceNames=people/c456&personFields="
        "names,emailAddresses,phoneNumbers,photos&sources=READ_SOURCE_TYPE_CONTACT",
    )
    saved = result["responses"][0]["person"]
    for field in ("names", "emailAddresses", "phoneNumbers", "photos"):
        assert not saved.get(field)
        assert not created.get(field)
    assert server.person == original


@pytest.mark.parametrize(
    "flags,expected",
    [
        (
            [
                "--name",
                "New Name",
                "--email",
                "new@example.com",
                "--email",
                "second@example.com",
                "--phone",
                "+1 202 555 0142 ext. 42",
                "--phone",
                "+44 20 7946 0958",
            ],
            {
                "names": [{"unstructuredName": "New Name"}],
                "emailAddresses": [{"value": "new@example.com"}, {"value": "second@example.com"}],
                "phoneNumbers": [
                    {"value": "+1 202 555 0142 ext. 42"},
                    {"value": "+44 20 7946 0958"},
                ],
            },
        ),
        (["--clear-name", "--clear-email", "--clear-phone"], {}),
        (
            ["--clear-name", "--email", "new@example.com", "--clear-phone"],
            {"emailAddresses": [{"value": "new@example.com"}]},
        ),
    ],
)
def test_overrides_preview_and_apply(flags, expected, server, api, monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    original = deepcopy(server.person)
    argv = ["duplicate", "--contact", "c123", *flags]
    assert cli.main(argv) == 0
    assert server.writes == 0
    preview = capsys.readouterr().out
    for option, label in (("name", "Name"), ("email", "Emails"), ("phone", "Phones")):
        if "--clear-" + option in flags:
            assert label + ": clear" in preview
    for entries in expected.values():
        for item in entries:
            assert next(iter(item.values())) in preview
    assert cli.main(argv + ["--apply"]) == 0
    saved = server.created["people/c456"]
    for field in ("names", "emailAddresses", "phoneNumbers"):
        assert saved.get(field, []) == expected.get(field, [])
    for field in ("biographies", "memberships"):
        assert saved[field] == original[field]
    assert saved["userDefined"][:-1] == original["userDefined"]
    assert saved["userDefined"][-1]["key"] == "Duplicate"
    assert server.person == original


@pytest.mark.parametrize(
    "photos",
    [
        [{"url": "https://lh3.googleusercontent.com/a=s100", "default": False}],
        [{"default": False}, {"default": False}],
        [],
    ],
)
def test_no_photo_skips_download_and_upload(photos, server, api, monkeypatch, capsys):
    server.person["photos"] = photos
    original = deepcopy(server.person)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    monkeypatch.setattr("contacts_cli.api.download_photo", lambda *a: pytest.fail("download"))
    assert cli.main(["duplicate", "--contact", "c123", "--no-photo", "--apply"]) == 0
    assert "Photo: use default avatar (--no-photo)" in capsys.readouterr().out
    assert not server.created["people/c456"].get("photos")
    assert not any(":updateContactPhoto" in call[1] for call in server.calls)
    assert server.person == original


@pytest.mark.parametrize(
    "flags",
    [
        ["--name", "New", "--clear-name"],
        ["--email", "new@example.com", "--clear-email"],
        ["--phone", "+1 202 555 0142", "--clear-phone"],
    ],
)
def test_conflicting_options_before_access(flags, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("connect"))
    with pytest.raises(SystemExit) as error:
        cli.main(["duplicate", "--contact", "c123", *flags])
    assert error.value.code == 2


@pytest.mark.parametrize(
    "option,value",
    [
        ("--name", ""),
        ("--email", ""),
        ("--phone", ""),
        ("--email", "bad"),
        ("--email", "a@localhost"),
        ("--email", "*@example.com"),
        ("--email", "Jane <a@example.com>"),
        ("--phone", "abc"),
        ("--phone", "123\n456"),
    ],
)
def test_invalid_replacements_before_access(option, value, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("connect"))
    assert cli.main(["duplicate", "--contact", "c123", option, value]) == 1


@pytest.mark.parametrize("field", ["names", "emailAddresses", "phoneNumbers"])
def test_cleared_fields_verified(field, server, api):
    plan = make_duplicate_plan(
        api.get_contact("people/c123", READ_FIELDS),
        api.people._rootDesc["schemas"],
        clear_name=True,
        clear_email=True,
        clear_phone=True,
    )
    api.duplicate(plan)
    saved = deepcopy(server.created["people/c456"])
    saved[field] = [
        {key: value for key, value in entry.items() if key != "metadata"}
        for entry in deepcopy(server.person[field])
    ]
    with pytest.raises(SyncError, match="does not match"):
        verify_duplicate(plan, saved, api.people._rootDesc["schemas"])


def test_no_photo_verified(server, api):
    plan = make_duplicate_plan(
        api.get_contact("people/c123", READ_FIELDS), api.people._rootDesc["schemas"], no_photo=True
    )
    api.duplicate(plan)
    saved = deepcopy(server.created["people/c456"])
    saved["photos"] = [{"default": False, "url": "https://lh3.googleusercontent.com/a=s100"}]
    with pytest.raises(SyncError, match="photo"):
        verify_duplicate(plan, saved, api.people._rootDesc["schemas"])


def test_duplicate_help(capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["duplicate", "--help"])
    assert error.value.code == 0
    help_text = capsys.readouterr().out
    for flag in (
        "--email",
        "--phone",
        "--clear-name",
        "--clear-email",
        "--clear-phone",
        "--no-photo",
    ):
        assert flag in help_text
    assert "repeatable" in help_text


@pytest.mark.parametrize(
    "option,field,value",
    [
        ("email", "emailAddresses", "new@example.com"),
        ("phone", "phoneNumbers", "+1 202 555 0142"),
    ],
)
def test_one_override_preserves_other_fields(option, field, value, api, monkeypatch):
    monkeypatch.setattr(
        "contacts_cli.duplicate.duplicate_marker",
        lambda: {"key": "Duplicate", "value": "Synthetic fixed time"},
    )
    person = api.get_contact("people/c123", READ_FIELDS)
    schemas = api.people._rootDesc["schemas"]
    original = make_duplicate_plan(person, schemas)
    changed = make_duplicate_plan(person, schemas, **{option: [value]})
    assert changed.body[field] == [{"value": value}]
    assert {k: v for k, v in changed.body.items() if k != field} == {
        k: v for k, v in original.body.items() if k != field
    }


@pytest.mark.parametrize(
    "field,options",
    [
        ("names", {"name": "New Name"}),
        ("emailAddresses", {"email": ["new@example.com"]}),
        ("phoneNumbers", {"phone": ["+1 202 555 0142"]}),
    ],
)
def test_lost_replacement_is_unverified(field, options, server, api):
    from contacts_cli.errors import WriteUnverified

    plan = make_duplicate_plan(
        api.get_contact("people/c123", READ_FIELDS), api.people._rootDesc["schemas"], **options
    )
    server.drop_copy_field = field
    with pytest.raises(WriteUnverified, match="does not match"):
        api.duplicate(plan)
    assert server.writes == 1


@pytest.mark.parametrize("answer,created", [("y", True), ("n", False)])
def test_interactive_override_confirmation(answer, created, server, api, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (cli.sys.stdin, cli.sys.stdout, cli.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: answer)
    assert cli.main(["duplicate", "--contact", "c123", "--clear-email", "--no-photo"]) == 0
    assert bool(server.created) is created
    if created:
        assert not server.created["people/c456"].get("emailAddresses")
    else:
        assert server.writes == 0
