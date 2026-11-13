from copy import deepcopy

import pytest

from contacts_cli.core import (
    Scan,
    contact_resource,
    make_plan,
    parse_from,
    update_body,
    verify_saved,
)
from contacts_cli.errors import SyncError


@pytest.mark.parametrize(
    "value",
    [
        "people/c123",
        "c123",
        "https://contacts.google.com/person/c123",
        "https://contacts.google.com/u/2/person/c123?hl=en",
    ],
)
def test_contact_identifiers(value):
    assert contact_resource(value) == "people/c123"


@pytest.mark.parametrize(
    "value",
    [
        "people/me",
        "people/123",
        "http://contacts.google.com/person/c123",
        "https://contacts.google.com.evil.invalid/person/c123",
        "https://contacts.google.com@evil.invalid/person/c123",
        "https://contacts.google.com/person/c123/unexpected",
        "c",
        "123",
        "c123abc",
        "c123/extra",
    ],
)
def test_reject_contact_identifiers(value):
    with pytest.raises(SyncError):
        contact_resource(value)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ('"Delivery, Example" <Case@Example.com>', ("Case@Example.com",)),
        ("=?UTF-8?B?Sm9zw6k=?= <sender@example.com>", ("sender@example.com",)),
        ("sender@example.com (Delivery)", ("sender@example.com",)),
        ("One <one@example.com>, Two <two@example.com>", ("one@example.com", "two@example.com")),
        ("Sender\r\n <sender@example.com>", ("sender@example.com",)),
        ('"quoted local"@example.com', ('"quoted local"@example.com',)),
    ],
)
def test_parse_from(header, expected):
    assert parse_from([header]) == expected


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [""],
        ["broken"],
        ["sender@"],
        ["a@example.com", "b@example.com"],
        ["valid@example.com, broken"],
        ["a@example.com\nBcc: injected@example.com"],
        ["a\x1b@example.com"],
        [None],
    ],
)
def test_malformed_from_rejected_whole(headers):
    with pytest.raises(SyncError):
        parse_from(headers)


def test_comparison_preserves_dot_plus_variants_and_existing_entries(server):
    original = deepcopy(server.person)
    scan = Scan(6, ("existing@example.com", "a.b@gmail.com", "ab@gmail.com", "ab+x@gmail.com"))
    plan = make_plan(original, scan)
    assert plan.additions == ("a.b@gmail.com", "ab+x@gmail.com", "ab@gmail.com")
    body = update_body(plan)
    assert body["emailAddresses"][:2] == original["emailAddresses"]
    assert set(body) == {"resourceName", "metadata", "emailAddresses"}
    body["emailAddresses"][0]["value"] = "mutated fixture"
    assert plan.person == original
    assert server.person == original


def test_contact_without_existing_emails(server):
    del server.person["emailAddresses"]
    plan = make_plan(server.person, Scan(1, ("new@example.com",)))
    assert update_body(plan)["emailAddresses"] == [{"value": "new@example.com"}]


@pytest.mark.parametrize("fault", ["source", "etag", "deleted", "mixed", "email", "multiple"])
def test_incomplete_or_ambiguous_contact_blocks_plan(server, fault):
    if fault == "source":
        server.person["metadata"]["sources"] = []
    elif fault == "etag":
        del server.person["metadata"]["sources"][0]["etag"]
    elif fault == "deleted":
        server.person["metadata"]["deleted"] = True
    elif fault == "mixed":
        server.person["emailAddresses"][0]["metadata"]["source"]["type"] = "PROFILE"
    elif fault == "email":
        del server.person["emailAddresses"][0]["value"]
    else:
        server.person["metadata"]["sources"].append({"type": "CONTACT", "id": "456", "etag": "x"})
    with pytest.raises(SyncError):
        make_plan(server.person, Scan(0, ()))


def test_local_contact_entry_limit(server):
    server.person["emailAddresses"] = [{"value": f"old{i}@example.com"} for i in range(500)]
    plan = make_plan(server.person, Scan(1, ("new@example.com",)))
    with pytest.raises(SyncError, match="size guard"):
        update_body(plan)


def test_local_contact_size_limit(server):
    server.person["biographies"][0]["value"] = "x" * (128 * 1024)
    plan = make_plan(server.person, Scan(1, ("new@example.com",)))
    with pytest.raises(SyncError, match="size guard"):
        update_body(plan)


@pytest.mark.parametrize("fault", ["label", "email", "primary", "phone", "addition"])
def test_verification_detects_lost_data(server, fault):
    plan = make_plan(server.person, Scan(1, ("new@example.com",)))
    saved = deepcopy(server.person)
    saved["emailAddresses"].append({"value": "new@example.com"})
    if fault == "label":
        saved["emailAddresses"][0]["type"] = "other"
    elif fault == "email":
        saved["emailAddresses"].pop(0)
    elif fault == "primary":
        saved["emailAddresses"][0]["metadata"]["sourcePrimary"] = False
    elif fault == "phone":
        saved["phoneNumbers"] = []
    else:
        saved["emailAddresses"].pop()
    with pytest.raises(SyncError):
        verify_saved(plan, saved)


def test_verification_tolerates_order_and_new_metadata(server):
    plan = make_plan(server.person, Scan(1, ("new@example.com",)))
    saved = deepcopy(server.person)
    saved["emailAddresses"].append({"value": "new@example.com"})
    saved["emailAddresses"].reverse()
    saved["phoneNumbers"][0]["metadata"] = {"primary": True}
    saved["metadata"]["sources"][0]["etag"] = "new"
    verify_saved(plan, saved)


def test_malformed_contact_url_is_user_error():
    with pytest.raises(SyncError):
        contact_resource("https://[broken")
