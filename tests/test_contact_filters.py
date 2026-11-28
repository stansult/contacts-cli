"""Explicit listing filters share pure matching and preserve read-only behavior."""

from copy import deepcopy

import pytest

from contacts_cli import cli

from .test_contact_resolution import setup


@pytest.mark.parametrize(
    "options,ids",
    [
        (["--name", "Jane"], ["c123"]),
        (["--name", "Jane", "--exact"], []),
        (["--name", " Jane  Example ", "--exact"], ["c123"]),
        (["--email", "JANE@example.com"], ["c123"]),
        (["--phone", "5550142"], ["c123", "c456"]),
        (["--phone", "5550142", "--exact"], []),
        (["--company", "acme"], ["c123", "c456"]),
        (["--company", " ACME ", "--exact"], ["c123"]),
        (["--name", "Jane", "--company", "acme"], ["c123"]),
        (["--name", "Jane", "--email", "other@example.com"], []),
        (["--search", "c123", "--company", "wrong"], []),
        (["--search", "acme"], []),
        (
            [
                "--name",
                "Jane",
                "--phone",
                "5550142",
                "--email",
                "jane@example.com",
                "--company",
                "acme",
            ],
            ["c123"],
        ),
    ],
)
def test_filters(options, ids, api, server, monkeypatch, capsys):
    other, _, baseline = setup(api, server, monkeypatch)
    server.person["organizations"] = [{"name": "Acme"}]
    other["organizations"] = [{"name": "Acme Labs"}]
    before = deepcopy([server.person, other])
    assert cli.main(["list-contact", *options]) == 0
    output = capsys.readouterr().out
    for resource in ("c123", "c456"):
        assert (f"({resource})" in output) == (resource in ids)
    assert server.writes == baseline
    assert [server.person, other] == before


@pytest.mark.parametrize(
    "options",
    [
        [],
        ["--exact"],
        ["--name", " "],
        ["--company", ""],
        ["--phone", "abc"],
        ["--email", "abc"],
        ["--label", "\n"],
        ["--search", "Jane", "--name", "Jane"],
        ["--search", "Jane", "--phone", "123"],
        ["--search", "Jane", "--email", "jane@example.com"],
    ],
)
def test_invalid_before_auth(options, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("authorization"))
    assert cli.main(["list-contact", *options]) == 1


@pytest.mark.parametrize(
    "label,answers,count,status",
    [
        ("Test", None, 1, 0),
        ("test", ["1"], 1, 0),
        ("test", ["q"], None, 0),
        ("test", None, None, 1),
        ("Missing", None, 0, 0),
    ],
)
def test_label_filter(label, answers, count, status, api, server, monkeypatch, capsys):
    other, resource, baseline = setup(api, server, monkeypatch, answers)
    server.person["memberships"] = [
        {"contactGroupMembership": {"contactGroupResourceName": resource}}
    ]
    other["memberships"] = []
    assert cli.main(["list-contact", "--label", label]) == status
    output = capsys.readouterr().out
    if count is not None:
        assert f"Matching contacts: {count} contact" in output
    else:
        assert "Matching contacts:" not in output
    assert server.writes == baseline


@pytest.mark.parametrize("search", ["Jane", "c123"])
def test_label_and_search_intersection(search, api, server, monkeypatch, capsys):
    other, resource, baseline = setup(api, server, monkeypatch)
    # Only the other contact has the requested label; neither search may return it.
    server.person["memberships"] = []
    other["memberships"] = [{"contactGroupMembership": {"contactGroupResourceName": resource}}]
    assert cli.main(["list-contact", "--search", search, "--label", "Test"]) == 0
    assert "Matching contacts: 0 contacts" in capsys.readouterr().out
    assert server.writes == baseline
    if search == "c123":
        assert not any(path.endswith("/connections") for _, path, _, _ in server.calls)


def test_label_on_later_page_and_large_contact(api, server, monkeypatch, capsys):
    _, resource, baseline = setup(api, server, monkeypatch)
    later = deepcopy(server.person)
    later["resourceName"] = "people/c789"
    later["metadata"]["sources"][0]["id"] = "789"
    later["names"] = [{"displayName": "Later Example"}]
    later["emailAddresses"] = [{"value": f"person{i}@example.com"} for i in range(101)]
    later["memberships"] = [{"contactGroupMembership": {"contactGroupResourceName": resource}}]
    server.created["people/c789"] = later
    assert cli.main(["list-contact", "--label", "Test", "--email", "person100@example.com"]) == 0
    output = capsys.readouterr().out
    assert "Matching contacts: 1 contact" in output and "(c789)" in output
    assert server.writes == baseline
    reads = [query for _, path, query, _ in server.calls if path.endswith("/connections")]
    assert len(reads) == 2 and all("memberships" in q["personFields"][0] for q in reads)


@pytest.mark.parametrize("bad", [None, [{}, {"contactGroupMembership": {}}], ["bad"]])
def test_bad_memberships_fail(api, server, monkeypatch, capsys, bad):
    setup(api, server, monkeypatch)
    server.person["memberships"] = bad
    assert cli.main(["list-contact", "--label", "Test"]) == 1
    assert "Matching contacts:" not in capsys.readouterr().out


def test_filter_predicate_is_reusable_without_io():
    from contacts_cli.contact_resolution import contact_filters

    person = {
        "names": [{"displayName": "123"}],
        "organizations": [{"name": "Old"}, {"name": "Acme Labs"}],
    }
    filters = contact_filters(name="123", company="ACME")
    assert filters.matches(person)
    assert not contact_filters(company="acme", exact=True).matches(person)
    assert not contact_filters(search="123").matches(person)


def test_filter_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["list-contact", "--help"])
    output = capsys.readouterr().out
    for option in ("--name", "--email", "--phone", "--company", "--label"):
        assert option in output
    assert "AND" in output


def test_membership_fixture_contract(server):
    from urllib.parse import urlencode

    from contacts_cli.contact_matches import MATCH_FIELDS

    from .test_fixture_contract import fetch

    server.person["memberships"] = [
        {"contactGroupMembership": {"contactGroupResourceName": "contactGroups/test"}}
    ]
    original = deepcopy(server.person)
    for include in (False, True):
        path = "/v1/people/me/connections?" + urlencode(
            dict(
                personFields=MATCH_FIELDS + (",memberships" if include else ""),
                pageSize=1000,
                sources="READ_SOURCE_TYPE_CONTACT",
            )
        )
        status, result = fetch(server, path)
        assert status == 200
        saved = result["connections"][0]
        assert ("memberships" in saved) == include
        if include:
            assert saved["memberships"] == original["memberships"]
        assert "biographies" not in saved
    assert server.person == original and server.writes == 0
