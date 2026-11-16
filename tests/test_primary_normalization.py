"""Synthetic transport normalization reproduces #10 without live Google access."""

import json
from copy import deepcopy
from urllib.parse import urlsplit

import pytest

from contacts_cli import error_logs
from contacts_cli.core import CONTACT_FIELDS, Scan, make_plan, update_body


@pytest.fixture(params=["update response", "independent readback"])
def normalizing_server(server, monkeypatch, request):
    stage = request.param
    server.person["emailAddresses"] = [
        {"value": "remaining@example.com", "metadata": {"primary": True}}
    ]
    original_request = server.request

    def normalize():
        server.person["emailAddresses"][0]["metadata"]["sourcePrimary"] = True

    def transport(uri, method="GET", **kwargs):
        path = urlsplit(uri).path
        if method == "GET" and path == "/v1/people:batchGet" and server.writes:
            normalize()
        response, content = original_request(uri, method=method, **kwargs)
        if method == "PATCH" and path.endswith(":updateContact") and stage == "update response":
            assert response.status == 200
            normalize()
            content = json.dumps(server.person).encode()
        return response, content

    monkeypatch.setattr(server, "request", transport)
    return server, stage


def test_normalizing_transport_contract(normalizing_server):
    server, stage = normalizing_server
    _, people = server.clients()
    original = deepcopy(server.person)
    body = {
        "metadata": original["metadata"],
        "emailAddresses": original["emailAddresses"] + [{"value": "new@example.com"}],
    }
    saved = (
        people.people()
        .updateContact(
            resourceName=original["resourceName"], updatePersonFields="emailAddresses", body=body
        )
        .execute()
    )
    assert saved["emailAddresses"][0]["metadata"].get("sourcePrimary") == (
        True if stage == "update response" else None
    )
    result = (
        people.people()
        .getBatchGet(
            resourceNames=[original["resourceName"]],
            personFields=CONTACT_FIELDS,
            sources=["READ_SOURCE_TYPE_CONTACT"],
        )
        .execute()["responses"][0]["person"]
    )
    expected = deepcopy(body["emailAddresses"])
    expected[0]["metadata"]["sourcePrimary"] = True
    assert result["emailAddresses"] == expected
    assert "sourcePrimary" not in body["emailAddresses"][0]["metadata"]
    assert server.writes == 1


def test_apply_accepts_normalization_without_error_log(api, normalizing_server):
    server, _ = normalizing_server
    plan = make_plan(server.person, Scan(1, ("new@example.com",)))
    original_body = update_body(plan)
    assert api.apply(plan)
    assert server.writes == 1
    assert server.batch_reads == 2  # conflict check, then independent readback
    expected = deepcopy(original_body["emailAddresses"])
    expected[0]["metadata"]["sourcePrimary"] = True
    assert server.person["emailAddresses"] == expected
    assert not list(error_logs.log_directory().glob("verification-*.json"))
