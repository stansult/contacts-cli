"""Possible duplicates are review signals; never silently merge or create them."""

import json
from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.contact_matches import (
    MATCH_FIELDS,
    MatchIndex,
    identity_keys,
    phone_key,
    read_match_contacts,
)

from .test_fixture_contract import fetch


def person(name=None, company=None, email=None, phone=None):
    result = {}
    for field, key, value in [
        ("names", "unstructuredName", name),
        ("organizations", "name", company),
        ("emailAddresses", "value", email),
        ("phoneNumbers", "value", phone),
    ]:
        if value is not None:
            result[field] = [{key: value}]
    return result


@pytest.mark.parametrize(
    "left,right,match",
    [
        (person(name=" Jane  Doe "), person(name="jane doe"), "name"),
        (person(name="Jane Doe"), {"names": [{"givenName": "Jane", "familyName": "Doe"}]}, "name"),
        (person(email="A+tag@example.com"), person(email="a+TAG@EXAMPLE.COM"), "email"),
        (person(email="a.b@example.com"), person(email="ab@example.com"), None),
        (person(company="Acme"), person(name=" ACME ", company="Acme"), "company"),
        (person(company="Acme"), person(name="Jane", company="Acme"), None),
        (person(name="Jane", company="Acme"), person(name="Bob", company="Acme"), None),
        (person(name="Jane", company="Acme"), person(name="Jane", company="Other"), None),
        (person(phone="+1 (202) 555-0142 ext. 42"), person(phone="+12025550142;ext=42"), "phone"),
        (person(phone="+1 202 555 0142"), person(phone="2025550142"), None),
        (person(phone="+12025550142 x42"), person(phone="+12025550142 x43"), None),
        (person(phone="+12025550142"), person(phone="+12025550142 x42"), None),
    ],
)
def test_matching_rules(left, right, match):
    index = MatchIndex()
    index.add("people/c1", left)
    matches = index.find(right)
    assert [m[2] for m in matches] == ([[match]] if match else [])
    assert bool(identity_keys(left) & identity_keys(right)) == bool(match)


def test_phone_does_not_guess_letters_or_country():
    assert phone_key("1-800-FLOWERS") is None
    assert phone_key("0012025550142") != phone_key("+12025550142")


@pytest.mark.parametrize(
    "name,eligible",
    [
        ({"unstructuredName": "Josh"}, False),
        ({"displayName": "Josh"}, False),
        ({"givenName": "Josh"}, False),
        ({"familyName": "Smith"}, False),
        ({"givenName": "Mary Jane"}, False),
        ({"givenName": "Josh", "honorificPrefix": "Dr."}, False),
        ({"givenName": "Josh", "displayName": "Dr. Josh"}, False),
        ({"givenName": "Josh", "familyName": "Smith"}, True),
        ({"unstructuredName": " Josh   Smith "}, True),
        ({"displayName": "Josh Smith"}, True),
    ],
)
def test_name_only_duplicate_requires_multiple_parts(name, eligible):
    index = MatchIndex()
    entry = {"names": [name]}
    index.add("people/c1", entry)
    assert bool(index.find(deepcopy(entry))) is eligible


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("emailAddresses", "josh@example.com", "email"),
        ("phoneNumbers", "+12025550142", "phone"),
    ],
)
def test_single_name_retains_strong_matches(field, value, reason):
    index = MatchIndex()
    index.add("people/c1", {"names": [{"givenName": "Josh"}], field: [{"value": value}]})
    assert [m[2] for m in index.find({field: [{"value": value}]})] == [[reason]]
    assert [
        m[2] for m in index.find({"names": [{"givenName": "Josh"}], field: [{"value": value}]})
    ] == [[reason]]


def test_single_names_in_same_input_do_not_match():
    from contacts_cli.contact_matches import duplicate_matches

    assert duplicate_matches([person(name="Josh"), person(name="Josh")], []) == {1: [], 2: []}


def test_connections_fixture_contract(server):
    server.connections = [
        dict(
            person(name=f"Person {i}"),
            resourceName=f"people/c{i}",
            biographies=[{"value": "private"}],
        )
        for i in range(3)
    ]
    base = (
        "/v1/people/me/connections?personFields="
        + MATCH_FIELDS
        + "&sources=READ_SOURCE_TYPE_CONTACT&pageSize=1000"
    )
    status, first = fetch(server, base)
    assert status == 200 and len(first["connections"]) == 2
    assert "biographies" not in first["connections"][0]
    _, second = fetch(server, base + "&pageToken=" + first["nextPageToken"])
    assert [p["resourceName"] for p in second["connections"]] == ["people/c2"]
    assert "nextPageToken" not in second


def setup(api, server, monkeypatch, tmp_path, inputs, existing=(), answers=None):
    server.connections = [
        dict(
            p,
            resourceName=f"people/c{i}",
            metadata={"sources": [{"type": "CONTACT", "id": str(i), "etag": "v1"}]},
        )
        for i, p in enumerate(existing, 1)
    ]
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (cli.sys.stdin, cli.sys.stdout, cli.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: answers is not None)
    iterator = iter(answers or [])

    def reply():
        assert server.writes == 0
        answer = next(iterator)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr("builtins.input", reply)
    path = tmp_path / "input.json"
    path.write_text(json.dumps(inputs))
    return ["add-contact", "--file", str(path), "--label", "New"]


@pytest.mark.parametrize("apply", [False, True])
def test_noninteractive_match_never_writes(api, server, monkeypatch, tmp_path, capsys, apply):
    args = setup(
        api, server, monkeypatch, tmp_path, [person(name="Jane Doe")], [person(name="Jane Doe")]
    )
    assert cli.main(args + (["--apply"] if apply else [])) == (1 if apply else 0)
    assert server.writes == 0
    assert "Add label New:" in capsys.readouterr().out


@pytest.mark.parametrize(
    "answers,created",
    [(["s"], 0), (["q"], 0), ([EOFError()], 0), (["bad", "c", "y"], 1), (["c", "n"], 0)],
)
def test_single_review(api, server, monkeypatch, tmp_path, answers, created):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [person(name="Jane Doe", email="jane@example.com")],
        [person(name="Jane Doe")],
        answers,
    )
    assert cli.main(args) == 0
    assert len(server.created) == created
    assert len(server.groups) == bool(created)


def test_batch_skip_then_compare_retained_inputs(api, server, monkeypatch, tmp_path):
    inputs = [person(name="Jane Doe"), person(name="Jane Doe"), person(name="Other")]
    args = setup(api, server, monkeypatch, tmp_path, inputs, answers=["all", "s", "y"])
    assert cli.main(args) == 0
    assert [p["names"][0]["unstructuredName"] for p in server.created.values()] == [
        "Jane Doe",
        "Other",
    ]


def test_unselected_match_does_not_prompt(api, server, monkeypatch, tmp_path):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [person(name="Jane Doe"), person(name="Other")],
        [person(name="Jane Doe")],
        ["2", "y"],
    )
    assert cli.main(args) == 0
    assert len(server.created) == 1
    assert next(iter(server.created.values()))["names"][0]["unstructuredName"] == "Other"


def test_apply_still_resolves_duplicate(api, server, monkeypatch, tmp_path):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [person(name="Jane Doe", email="jane@example.com")],
        [person(name="Jane Doe")],
        ["c"],
    )
    assert cli.main(args + ["--apply"]) == 0
    assert len(server.created) == 1


def test_read_all_pages(api, server):
    server.connections = [
        dict(person(name=f"Person {i}"), resourceName=f"people/c{i}") for i in range(5)
    ]
    before = deepcopy(server.connections)
    assert read_match_contacts(api) == before
    assert len(server.calls) == 3 and server.writes == 0


@pytest.mark.parametrize(
    "response",
    [
        [],
        {"connections": None},
        {"connections": [{}]},
        {"connections": [{"resourceName": "people/c1", "names": None}]},
        {"connections": [], "nextPageToken": 42},
    ],
)
def test_incomplete_contact_list_blocks_creation(api, server, monkeypatch, response):
    import httplib2

    original = server.request

    def broken(uri, *args, **kwargs):
        if "/connections?" in uri:
            return httplib2.Response({"status": "200"}), json.dumps(response).encode()
        return original(uri, *args, **kwargs)

    monkeypatch.setattr(server, "request", broken)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(["add-contact", "--name", "Jane", "--apply"]) == 1
    assert server.writes == 0


def test_cancel_after_prior_choice_writes_nothing(api, server, monkeypatch, tmp_path):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [person(name="Jane Doe"), person(name="Bob Smith")],
        [person(name="Jane Doe"), person(name="Bob Smith")],
        ["all", "c", "q"],
    )
    assert cli.main(args) == 0
    assert server.writes == 0


def test_skipped_input_does_not_block_later_input(api, server, monkeypatch, tmp_path):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [
            person(name="Jane Doe", email="shared@example.com"),
            person(name="Other", email="shared@example.com"),
        ],
        [person(name="Jane Doe")],
        ["all", "s", "y"],
    )
    assert cli.main(args) == 0
    assert len(server.created) == 1
    assert next(iter(server.created.values()))["names"][0]["unstructuredName"] == "Other"


def test_noninteractive_incoming_duplicates_stop_apply(api, server, monkeypatch, tmp_path):
    args = setup(
        api, server, monkeypatch, tmp_path, [person(name="Jane Doe"), person(name="Jane Doe")]
    )
    assert cli.main(args + ["--apply"]) == 1
    assert server.writes == 0


def test_multiple_matches_and_reasons():
    index = MatchIndex()
    index.add("people/c1", person(name="Jane Doe", email="a@example.com"))
    index.add("people/c2", person(name="Other", email="a@example.com"))
    assert [
        (item[0], item[2]) for item in index.find(person(name="Jane Doe", email="a@example.com"))
    ] == [("people/c1", ["email", "name"]), ("people/c2", ["email"])]


@pytest.mark.parametrize("repeat_identity", [True, False])
def test_pagination_loop_stops(api, server, monkeypatch, repeat_identity):
    import httplib2

    from contacts_cli.errors import SyncError

    def broken(*args, **kwargs):
        response = {
            "connections": (
                [dict(person(name="Jane Doe"), resourceName="people/c1")] if repeat_identity else []
            ),
            "nextPageToken": "same",
        }
        return httplib2.Response({"status": "200"}), json.dumps(response).encode()

    monkeypatch.setattr(server, "request", broken)
    with pytest.raises(SyncError, match="repeated"):
        read_match_contacts(api)
    assert server.writes == 0


@pytest.mark.parametrize("field", ["emailAddresses", "phoneNumbers"])
def test_list_email_limit_fixture_and_complete_lookup(api, server, field):
    server.person[field] = [
        {"value": f"person{i}@example.com" if field == "emailAddresses" else f"+1202555{i:04d}"}
        for i in range(101)
    ]
    result = (
        api.people.people()
        .connections()
        .list(
            resourceName="people/me",
            pageSize=1000,
            personFields=MATCH_FIELDS,
            sources=["READ_SOURCE_TYPE_CONTACT"],
        )
        .execute()
    )
    assert len(result["connections"][0][field]) == 100
    assert len(api.get_contact(server.person["resourceName"])[field]) == 101
    assert len(read_match_contacts(api)[0][field]) == 101
