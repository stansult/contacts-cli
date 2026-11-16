"""Email preservation and primary normalization regressions (#10)."""

from copy import deepcopy

import pytest

from contacts_cli.core import Scan, make_plan, update_body, verify_saved
from contacts_cli.errors import SyncError, WriteUnverified


@pytest.mark.parametrize(
    "field,value", [("type", "Changed"), ("displayName", "Changed"), ("sourcePrimary", False)]
)
def test_named_before_after(server, field, value):
    plan = make_plan(server.person, Scan(1, ("new@example.com",)))
    saved = deepcopy(server.person)
    saved["emailAddresses"] = update_body(plan)["emailAddresses"]
    entry = saved["emailAddresses"][0]
    (entry["metadata"] if field == "sourcePrimary" else entry)[field] = value
    with pytest.raises(SyncError) as error:
        verify_saved(plan, saved)
    message = str(error.value)
    assert field in message and "Before:" in message and "Saved:" in message
    assert "Existing@Example.com" in message


@pytest.mark.parametrize("initial", [None, False])
def test_unrecorded_primary_can_become_explicit(server, initial):
    metadata = {"primary": True}
    if initial is not None:
        metadata["sourcePrimary"] = initial
    server.person["emailAddresses"] = [{"value": "remaining@example.com", "metadata": metadata}]
    plan = make_plan(server.person, Scan(1, ("new@example.com",)))
    saved = deepcopy(server.person)
    saved["emailAddresses"] = update_body(plan)["emailAddresses"]
    saved["emailAddresses"][0]["metadata"]["sourcePrimary"] = True
    verify_saved(plan, saved)


@pytest.mark.parametrize("replacement", [None, False])
def test_explicit_primary_loss_still_fails(server, replacement):
    plan = make_plan(server.person, Scan(1, ("new@example.com",)))
    saved = deepcopy(server.person)
    saved["emailAddresses"] = update_body(plan)["emailAddresses"]
    metadata = saved["emailAddresses"][0]["metadata"]
    if replacement is None:
        del metadata["sourcePrimary"]
    else:
        metadata["sourcePrimary"] = replacement
    saved["emailAddresses"][-1]["metadata"] = {"sourcePrimary": True}
    with pytest.raises(SyncError, match="sourcePrimary"):
        verify_saved(plan, saved)


@pytest.mark.parametrize("fault", ["value", "type", "displayName", "duplicate"])
def test_primary_normalization_does_not_hide_content_loss(server, fault):
    entry = {"value": "remaining@example.com", "type": "work", "displayName": "Team"}
    server.person["emailAddresses"] = [deepcopy(entry), deepcopy(entry)]
    plan = make_plan(server.person, Scan(1, ("new@example.com",)))
    saved = deepcopy(server.person)
    saved["emailAddresses"] = update_body(plan)["emailAddresses"]
    saved["emailAddresses"][0]["metadata"] = {"sourcePrimary": True}
    if fault == "duplicate":
        saved["emailAddresses"].pop(1)
    else:
        saved["emailAddresses"][1][fault] = "changed@example.com"
    with pytest.raises(SyncError, match="existing email"):
        verify_saved(plan, saved)


def test_missing_duplicate_reports_counts_without_pairing(server):
    server.person["emailAddresses"] *= 2
    plan = make_plan(server.person, Scan(1, ("new@example.com",)))
    saved = deepcopy(server.person)
    saved["emailAddresses"] = update_body(plan)["emailAddresses"]
    saved["emailAddresses"].pop(0)
    with pytest.raises(SyncError) as error:
        verify_saved(plan, saved)
    assert "Unmatched before entries" in str(error.value)
    assert "Existing@Example.com" in str(error.value)


@pytest.mark.parametrize("stage", ["update response", "independent readback"])
def test_failure_stage_is_identified(api, server, stage):
    plan = make_plan(server.person, Scan(1, ("new@example.com",)))
    calls = 0

    def verify(saved):
        nonlocal calls
        calls += 1
        if calls == (1 if stage == "update response" else 2):
            raise SyncError("Synthetic mismatch")

    with pytest.raises(WriteUnverified) as error:
        api.apply_email_change(plan.person, update_body(plan), verify)
    assert stage in str(error.value)
    assert server.writes == 1
