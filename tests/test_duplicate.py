"""Copy semantics from the People create/photo APIs, exercised offline."""

import base64
import json
from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.duplicate import READ_FIELDS, download_photo, make_duplicate_plan
from contacts_cli.errors import SyncError, WriteUnverified

from .fake_google import FIXTURES
from .test_fixture_contract import fetch


def plan_for(api, name=None):
    return make_duplicate_plan(
        api.get_contact("people/c123", READ_FIELDS), api.people._rootDesc["schemas"], name
    )


def test_copy_fixture_independent_identity_storage_and_mask(server):
    original = deepcopy(server.person)
    body = {"names": [{"givenName": "Copy"}], "emailAddresses": [{"value": "copy@example.com"}]}
    status, created = fetch(server, "/v1/people:createContact", "POST", body)
    assert status == 200
    assert created["resourceName"] == "people/c456"
    assert created["metadata"]["sources"][0]["id"] == "1c8"
    body["names"][0]["givenName"] = "Changed locally"
    _, result = fetch(
        server,
        "/v1/people:batchGet?resourceNames=people/c456&personFields=names&sources=READ_SOURCE_TYPE_CONTACT",
    )
    assert result["responses"][0]["person"]["names"] == [{"givenName": "Copy"}]
    assert "emailAddresses" not in result["responses"][0]["person"]
    assert server.person == original
    _, absent = fetch(
        server,
        "/v1/people:batchGet?resourceNames=people/c999&personFields=names&sources=READ_SOURCE_TYPE_CONTACT",
    )
    assert absent["responses"][0]["status"]["code"] == 5
    _, photo = fetch(
        server, "/v1/people/c456:updateContactPhoto", "PATCH", {"photoBytes": "aW1hZ2U="}
    )
    assert photo["person"]["photos"][0]["default"] is False
    assert server.created["people/c456"]["photos"] == photo["person"]["photos"]


def test_preview_and_apply_via_cli(server, api, monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    original = deepcopy(server.person)
    argv = ["duplicate", "--contact", "people/c123", "--name", "Delivery backup"]
    assert cli.main(argv) == 0
    assert server.writes == 0
    assert "Preview only" in capsys.readouterr().out
    assert cli.main(argv + ["--apply"]) == 0
    assert "https://contacts.google.com/person/c456" in capsys.readouterr().out
    assert server.created["people/c456"]["names"] == [{"givenName": "Delivery backup"}]
    assert server.person == original
    assert not any("/gmail/" in call[1] for call in server.calls)


def test_all_fields_and_full_email_list(server, api):
    extra = json.loads((FIXTURES / "duplicate-fields.json").read_text())
    server.person.update(deepcopy(extra))
    server.person["emailAddresses"].extend({"value": f"person{i}@example.com"} for i in range(150))
    original = deepcopy(server.person)
    plan = plan_for(api)
    assert "displayName" not in plan.body["names"][0]
    assert "formattedType" not in plan.body["addresses"][0]
    assert plan.body["emailAddresses"][0]["metadata"] == {"sourcePrimary": True}
    assert api.duplicate(plan).endswith("/c456")
    saved = server.created["people/c456"]
    assert len(saved["emailAddresses"]) == 152
    for field, values in extra.items():
        expected = deepcopy(values)
        if field == "addresses":
            expected[0].pop("formattedType")
        assert saved[field] == expected
    assert saved["phoneNumbers"] == original["phoneNumbers"]
    assert saved["biographies"] == original["biographies"]
    assert saved["userDefined"][:-1] == original["userDefined"]
    assert saved["userDefined"][-1]["key"] == "Duplicate"
    assert saved["memberships"] == original["memberships"]
    assert server.person == original


def test_source_change_aborts(server, api):
    plan = plan_for(api)
    server.person["phoneNumbers"][0]["value"] = "+1 202-555-0199"
    with pytest.raises(SyncError, match="changed since preview"):
        api.duplicate(plan)
    assert server.writes == 0


@pytest.mark.parametrize("field", ["emailAddresses", "phoneNumbers", "names", "memberships"])
def test_missing_copied_field_is_unverified(server, api, field):
    server.drop_copy_field = field
    with pytest.raises(WriteUnverified, match="https://contacts.google.com/person/c456"):
        api.duplicate(plan_for(api))
    assert server.writes == 1


@pytest.mark.parametrize(
    "status,exception", [(400, SyncError), (403, SyncError), (503, WriteUnverified)]
)
def test_create_failures_never_retry(server, api, status, exception):
    server.create_status = status
    with pytest.raises(exception):
        api.duplicate(plan_for(api))
    assert sum(call[1].endswith(":createContact") for call in server.calls) == 1


def test_photo_copy_and_partial_failure(server, api, monkeypatch):
    server.person["photos"] = [
        {"url": "https://lh3.googleusercontent.com/source", "default": False}
    ]
    monkeypatch.setattr("contacts_cli.api.download_photo", lambda url: b"image")
    assert api.duplicate(plan_for(api)).endswith("/c456")
    assert server.created["people/c456"]["photos"]
    server.photo_status = 400
    with pytest.raises(WriteUnverified, match="https://contacts.google.com/person/c457"):
        api.duplicate(plan_for(api))
    assert "people/c457" in server.created
    assert sum(call[1].endswith(":updateContactPhoto") for call in server.calls) == 2


def test_photo_download_before_creation(server, api, monkeypatch):
    server.person["photos"] = [
        {"url": "https://lh3.googleusercontent.com/source", "default": False}
    ]

    def fail(url):
        raise SyncError("Synthetic download failure")

    monkeypatch.setattr("contacts_cli.api.download_photo", fail)
    with pytest.raises(SyncError, match="download failure"):
        api.duplicate(plan_for(api))
    assert server.writes == 0


@pytest.mark.parametrize(
    "url",
    [
        "http://lh3.googleusercontent.com/a",
        "https://example.com/a",
        "https://googleusercontent.com.example.com/a",
    ],
)
def test_photo_download_rejects_untrusted_urls(url):
    with pytest.raises(SyncError, match="Unsupported"):
        download_photo(url)


def test_photo_download_contract(monkeypatch):
    class Response:
        status_code = 200
        headers = {"Content-Type": "image/png"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_content(self, size):
            assert size == 65536
            return iter([b"photo", b"bytes"])

    def get(url, **kwargs):
        assert kwargs == {"stream": True, "timeout": (10, 30), "allow_redirects": False}
        return Response()

    monkeypatch.setattr("contacts_cli.duplicate.requests.get", get)
    assert download_photo("https://lh3.googleusercontent.com/a=s100") == b"photobytes"


def test_invalid_name_before_connect(monkeypatch):
    monkeypatch.setattr(
        cli, "connect_with_authorization", lambda *a: pytest.fail("must not connect")
    )
    assert cli.main(["duplicate", "--contact", "people/c123", "--name", "   "]) == 1


def test_unsupported_system_group_aborts(server, api):
    server.person["memberships"] = [
        {"contactGroupMembership": {"contactGroupResourceName": "contactGroups/friends"}}
    ]
    with pytest.raises(SyncError, match="system group"):
        api.duplicate(plan_for(api))
    assert server.writes == 0


def test_verification_allows_generated_primary_but_preserves_requested_primary(server, api):
    from contacts_cli.duplicate import verify_duplicate

    plan = plan_for(api, "Backup")
    api.duplicate(plan)
    saved = deepcopy(server.created["people/c456"])
    saved["names"][0]["metadata"] = {"sourcePrimary": True, "primary": True}
    verify_duplicate(plan, saved, api.people._rootDesc["schemas"])
    saved["emailAddresses"][0].pop("metadata")
    with pytest.raises(SyncError, match="primary"):
        verify_duplicate(plan, saved, api.people._rootDesc["schemas"])


def test_failed_verification_exit_code_and_link(server, api, monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    server.fail_verification = True
    assert cli.main(["duplicate", "--contact", "people/c123", "--apply"]) == 3
    error = capsys.readouterr().err
    assert "Unverified copy" in error
    assert "https://contacts.google.com/person/c456" in error
    assert server.writes == 1


def test_rename_preserves_every_other_field(server, api, monkeypatch):
    monkeypatch.setattr(
        "contacts_cli.duplicate.duplicate_marker",
        lambda: {"key": "Duplicate", "value": "Created by contacts-cli at a fixed test time"},
    )
    unchanged = plan_for(api)
    renamed = plan_for(api, "Backup")
    assert {k: v for k, v in unchanged.body.items() if k != "names"} == {
        k: v for k, v in renamed.body.items() if k != "names"
    }


def test_default_photo_needs_no_download(server, api, monkeypatch):
    server.person["photos"] = [
        {"url": "https://lh3.googleusercontent.com/default", "default": True}
    ]
    monkeypatch.setattr(
        "contacts_cli.api.download_photo", lambda url: pytest.fail("default avatar")
    )
    api.duplicate(plan_for(api))
    assert server.writes == 1


def test_duplicate_marker_preserves_existing_fields_and_is_verified(server, api):
    original = deepcopy(server.person)
    server.person["userDefined"].append({"key": "Duplicate", "value": "Earlier copy"})
    existing = deepcopy(server.person["userDefined"])
    plan = plan_for(api)
    assert plan.body["userDefined"][:-1] == existing
    marker = plan.body["userDefined"][-1]
    assert marker["key"] == "Duplicate"
    assert marker["value"].startswith("Created by contacts-cli on ")
    assert " at " in marker["value"] and "(UTC" in marker["value"]
    api.duplicate(plan)
    assert server.created["people/c456"]["userDefined"] == existing + [marker]
    assert server.person["userDefined"] == existing
    from contacts_cli.duplicate import verify_duplicate

    saved = deepcopy(server.created["people/c456"])
    saved["userDefined"].pop()
    with pytest.raises(SyncError, match="editable fields"):
        verify_duplicate(plan, saved, api.people._rootDesc["schemas"])
    assert server.person["names"] == original["names"]


@pytest.mark.parametrize(
    "hour,offset,expected",
    [
        (14, -8, "November 11, 2026 at 2:30 PM (UTC−08:00)"),
        (0, 0, "November 11, 2026 at 12:30 AM (UTC+00:00)"),
        (12, 5.5, "November 11, 2026 at 12:30 PM (UTC+05:30)"),
    ],
)
def test_duplicate_marker_readable_time(hour, offset, expected):
    from datetime import datetime, timedelta, timezone

    from contacts_cli.duplicate import duplicate_marker

    now = datetime(2026, 11, 11, hour, 30, tzinfo=timezone(timedelta(hours=offset)))
    assert duplicate_marker(now) == {
        "key": "Duplicate",
        "value": "Created by contacts-cli on " + expected,
    }


@pytest.mark.parametrize(
    "suffix,expected",
    [
        ("/s100/photo.png", "/s0/photo.png"),
        ("=s100", "=s0"),
        ("=s100-c", "=s0-c"),
        ("/s0/photo.png?sz=100&other=keep", "/s0/photo.png?other=keep"),
    ],
)
def test_full_size_photo_bytes_are_uploaded(server, api, monkeypatch, suffix, expected):
    from pathlib import Path

    root = Path(__file__).parent / "fixtures"
    full = (root / "photo-full.png").read_bytes()
    thumb = (root / "photo-thumbnail.png").read_bytes()
    source = "https://lh3.googleusercontent.com/synthetic" + suffix
    target = "https://lh3.googleusercontent.com/synthetic" + expected
    server.person["photos"] = [{"url": source, "default": False}]
    requested = []

    class Response:
        status_code = 200
        headers = {"Content-Type": "image/png"}

        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_content(self, size):
            return iter([self.data])

    def get(url, **kwargs):
        requested.append(url)
        return Response(full if url == target else thumb)

    monkeypatch.setattr("contacts_cli.duplicate.requests.get", get)
    api.duplicate(plan_for(api))
    assert requested == [target]
    photo_calls = [call for call in server.calls if call[1].endswith(":updateContactPhoto")]
    assert base64.b64decode(photo_calls[0][3]["photoBytes"]) == full


def test_unknown_photo_size_stops_before_download(monkeypatch):
    monkeypatch.setattr(
        "contacts_cli.duplicate.requests.get", lambda *a, **k: pytest.fail("download")
    )
    with pytest.raises(SyncError, match="full-size"):
        download_photo("https://lh3.googleusercontent.com/unknown")
