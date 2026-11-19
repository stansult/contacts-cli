"""Shared label eligibility, identities, and paginated reads."""

import pytest

from contacts_cli.errors import SyncError
from contacts_cli.label_data import active_user_labels, contact_groups, label_identity

from .test_label_edit import group


def test_active_user_filter():
    active = {"groupType": "USER_CONTACT_GROUP", "name": "Keep"}
    deleted = {**active, "metadata": {"deleted": True}}
    system = {**active, "groupType": "SYSTEM_CONTACT_GROUP"}
    values = [system, deleted, active]
    assert active_user_labels(values) == [active]
    assert values == [system, deleted, active]


@pytest.mark.parametrize(
    "field,value",
    [("name", None), ("name", ""), ("resourceName", None), ("resourceName", "invalid")],
)
def test_invalid_identity(field, value):
    entry = {"name": "Example", "resourceName": "contactGroups/123", field: value}
    with pytest.raises(SyncError):
        label_identity(entry)


def test_identity_preserves_spelling():
    assert label_identity({"name": " eXample ", "resourceName": "contactGroups/123"}) == (
        " eXample ",
        "contactGroups/123",
    )


def test_shared_reader_paginates(api, server):
    for name in ("One", "Two", "Three"):
        group(server, name)
    assert [g["name"] for g in contact_groups(api)] == ["One", "Two", "Three"]
