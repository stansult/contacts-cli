"""Batch failures isolate rejected/unverified contacts without replaying writes."""

import json
from copy import deepcopy

import httplib2
import pytest

from contacts_cli import cli

from .test_contact_merge import incoming, setup


def wire_failure(
    server, monkeypatch, status=400, reason="badRequest", verification=False, read_status=None
):
    original = server.request
    attempts = []

    def request(uri, method="GET", *args, **kwargs):
        if method == "POST" and ":createContact" in uri:
            attempts.append(uri)
            if len(attempts) == 2 and not verification and read_status is None:
                return httplib2.Response({"status": status}), json.dumps(
                    {"error": {"errors": [{"reason": reason}]}}
                ).encode()
        if method == "GET" and "people:batchGet" in uri and len(attempts) == 2 and read_status:
            return httplib2.Response(
                {"status": read_status}
            ), b'{"error":{"message":"read failed"}}'
        response, content = original(uri, method, *args, **kwargs)
        if verification and method == "GET" and "people:batchGet" in uri and len(attempts) == 2:
            data = json.loads(content)
            data["responses"][0]["person"]["emailAddresses"] = []
            content = json.dumps(data).encode()
        return response, content

    monkeypatch.setattr(server, "request", request)
    return attempts


def args_for_create(api, server, monkeypatch, tmp_path):
    return setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [{"emailAddresses": [{"value": f"{i}@example.com"}]} for i in range(3)],
        [],
    ) + ["--apply"]


@pytest.mark.parametrize("verification", [False, True])
def test_contact_failure_continues_creations(
    api, server, monkeypatch, tmp_path, capsys, verification
):
    args = args_for_create(api, server, monkeypatch, tmp_path)
    attempts = wire_failure(server, monkeypatch, verification=verification)
    assert cli.main(args) == (3 if verification else 1)
    assert len(attempts) == 3
    assert len(server.created) == (3 if verification else 2)
    output = capsys.readouterr().out
    assert "Continuing with remaining contacts." in output
    assert "Contact #2" in output
    assert "0 not attempted" in output
    assert "2 verified" in output


@pytest.mark.parametrize(
    "status,reason",
    [
        (401, "authError"),
        (403, "rateLimitExceeded"),
        (429, "rateLimitExceeded"),
        (503, "backendError"),
        (400, "quotaExceeded"),
    ],
)
def test_batch_wide_http_failure_stops(api, server, monkeypatch, tmp_path, status, reason):
    args = args_for_create(api, server, monkeypatch, tmp_path)
    attempts = wire_failure(server, monkeypatch, status=status, reason=reason)
    assert cli.main(args) in {1, 3}
    assert len(attempts) == 2 and len(server.created) == 1


def test_readback_auth_failure_stops(api, server, monkeypatch, tmp_path):
    args = args_for_create(api, server, monkeypatch, tmp_path)
    attempts = wire_failure(server, monkeypatch, read_status=401)
    assert cli.main(args) == 3
    assert len(attempts) == 2 and len(server.created) == 2


def test_failed_merge_continues_to_new_contact(api, server, monkeypatch, tmp_path, capsys):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [
            incoming(server, urls=[{"value": "https://example.com/new"}]),
            {"names": [{"givenName": "New Person"}]},
        ],
        ["all", "m", "y"],
    )
    server.lose_additions = True
    assert cli.main(args) == 3
    assert len(server.created) == 1 and server.writes == 2
    output = capsys.readouterr().out
    assert "unverified" in output.lower() and "0 not attempted" in output


def test_concurrent_target_does_not_block_independent_create(api, server, monkeypatch, tmp_path):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [
            incoming(server, urls=[{"value": "https://example.com/new"}]),
            {"names": [{"givenName": "New Person"}]},
        ],
        [],
    )
    answers = iter(["all", "m", "y"])

    def answer():
        result = next(answers)
        if result == "y":
            server.person["metadata"]["sources"][0]["etag"] = "changed"
        return result

    monkeypatch.setattr("builtins.input", answer)
    before = deepcopy(server.person["emailAddresses"])
    assert cli.main(args) == 1
    assert len(server.created) == 1 and server.writes == 1
    assert server.person["emailAddresses"] == before


@pytest.mark.parametrize("verification", [False, True])
def test_failure_fixture_contract(server, monkeypatch, verification):
    from .test_fixture_contract import fetch

    attempts = wire_failure(server, monkeypatch, verification=verification)
    for i in range(3):
        status, result = fetch(
            server,
            "/v1/people:createContact",
            "POST",
            {"emailAddresses": [{"value": f"{i}@example.com"}]},
        )
        assert status == (400 if i == 1 and not verification else 200)
        if i == 1 and verification:
            resource = result["resourceName"]
            _, read = fetch(
                server,
                "/v1/people:batchGet?resourceNames="
                + resource
                + "&personFields=emailAddresses,metadata&sources=READ_SOURCE_TYPE_CONTACT",
            )
            assert read["responses"][0]["person"]["emailAddresses"] == []
            assert server.created[resource]["emailAddresses"] == [{"value": "1@example.com"}]
    assert len(attempts) == 3
    assert len(server.created) == (3 if verification else 2)


@pytest.mark.parametrize(
    "kind", ["rejected", "verification", "auth", "quota", "network", "interrupt"]
)
def test_merge_failure_scope(api, server, monkeypatch, tmp_path, kind):
    from googleapiclient.errors import HttpError

    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [
            incoming(server, urls=[{"value": "https://example.com/new"}]),
            {"names": [{"givenName": "New Person"}]},
        ],
        ["all", "m", "y"],
    )
    original = server.request
    updates = []

    def request(uri, method="GET", *args, **kwargs):
        if method == "PATCH" and ":updateContact" in uri:
            updates.append(uri)
            if kind == "network":
                raise OSError("synthetic connection failure")
            if kind == "interrupt":
                raise KeyboardInterrupt
            if kind in {"rejected", "auth", "quota"}:
                status = {"rejected": 400, "auth": 401, "quota": 429}[kind]
                raise HttpError(
                    httplib2.Response({"status": status}), b'{"error":{"message":"fixture"}}'
                )
            server.lose_additions = True
        return original(uri, method, *args, **kwargs)

    monkeypatch.setattr(server, "request", request)
    code = cli.main(args)
    assert (
        code
        == {
            "rejected": 1,
            "verification": 3,
            "auth": 1,
            "quota": 1,
            "network": 3,
            "interrupt": 130,
        }[kind]
    )
    assert len(updates) == 1
    assert len(server.created) == int(kind in {"rejected", "verification"})


def test_unverified_then_global_failure_retains_nonzero_outcomes(
    api, server, monkeypatch, tmp_path, capsys
):
    from contacts_cli.errors import SyncError

    args = args_for_create(api, server, monkeypatch, tmp_path)
    original = api.get_contact

    def read(resource, fields):
        saved = original(resource, fields)
        if len(server.created) == 1:
            saved["emailAddresses"] = []
        elif len(server.created) == 2:
            raise SyncError("Synthetic network read failure")
        return saved

    monkeypatch.setattr(api, "get_contact", read)
    assert cli.main(args) == 3 and len(server.created) == 2
    output = capsys.readouterr().out
    assert "2 created; 0 verified; 1 not attempted" in output
    assert "Contact #1" in output and "Contact #2" in output


def test_unverified_merge_then_global_failure_does_not_claim_no_changes(
    api, server, monkeypatch, tmp_path, capsys
):
    from contacts_cli.errors import SyncError

    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [
            incoming(server, urls=[{"value": "https://example.com/new"}]),
            {"emailAddresses": [{"value": "new@example.com"}]},
        ],
        ["all", "m", "y"],
    )
    server.lose_additions = True
    original = api.write

    def write(request, **kwargs):
        if ":createContact" in request.uri:
            raise SyncError("Synthetic authorization failure")
        return original(request, **kwargs)

    monkeypatch.setattr(api, "write", write)
    assert cli.main(args) == 3
    output = capsys.readouterr().out
    assert "No changes made." not in output
    assert "1 failed before saving; 1 unverified; 0 not attempted" in output
