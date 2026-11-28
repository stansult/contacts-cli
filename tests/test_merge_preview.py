"""Upfront merge comparison reads only matched contacts and reuses run-local snapshots."""

from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.duplicate import READ_FIELDS
from contacts_cli.errors import SyncError

from .test_contact_merge import incoming, setup


@pytest.mark.parametrize(
    "kind,summary",
    [
        ("same", "Nothing new"),
        ("new", "New information available"),
        ("conflict", "Conflicts to resolve"),
        ("both", "New information and conflicts"),
    ],
)
def test_outcome_before_first_choice(api, server, monkeypatch, tmp_path, capsys, kind, summary):
    fields = {}
    if kind in {"new", "both"}:
        fields["urls"] = [{"value": "https://example.com/new"}]
    if kind in {"conflict", "both"}:
        fields["names"] = [{"givenName": "Different"}]
    args = setup(api, server, monkeypatch, tmp_path, [incoming(server, **fields)], ["q"])

    def answer():
        output = capsys.readouterr().out
        assert summary in output
        assert server.batch_reads == 1 and server.writes == 0
        return "q"

    monkeypatch.setattr("builtins.input", answer)
    assert cli.main(args) == 0 and server.writes == 0


def test_only_unique_matched_targets_read_and_reused(api, server, monkeypatch, tmp_path):
    other = deepcopy(server.person)
    other.update(
        resourceName="people/c999",
        names=[{"givenName": "Unrelated"}],
        emailAddresses=[{"value": "other@example.com"}],
        phoneNumbers=[],
    )
    server.created[other["resourceName"]] = other
    args = setup(
        api, server, monkeypatch, tmp_path, [incoming(server), incoming(server)], ["all", "s", "s"]
    )
    assert cli.main(args) == 0
    reads = [c for c in server.calls if c[1] == "/v1/people:batchGet"]
    assert len(reads) == 1
    assert reads[0][2]["resourceNames"] == [server.person["resourceName"]]
    assert reads[0][2]["personFields"] == [READ_FIELDS]
    assert server.writes == 0


@pytest.mark.parametrize("present", [False, True])
def test_label_comparison_upfront(api, server, monkeypatch, tmp_path, capsys, present):
    resource = "contactGroups/test"
    server.groups[resource] = {
        "resourceName": resource,
        "name": "Test",
        "groupType": "USER_CONTACT_GROUP",
    }
    if present:
        server.person["memberships"].append(
            {"contactGroupMembership": {"contactGroupResourceName": resource}}
        )
    args = setup(api, server, monkeypatch, tmp_path, [incoming(server)], ["q"])
    assert cli.main(args + ["--label", "Test"]) == 0
    output = capsys.readouterr().out
    preview = output.split("Choose an option (Enter = skip this input):")[0]
    assert ("Add label Test:" in preview) == (not present)
    assert ("Already complete:" in preview) == present


def test_detail_read_failure_stops_before_selection(api, server, monkeypatch, tmp_path):
    args = setup(api, server, monkeypatch, tmp_path, [incoming(server)], [])

    def fail(*a, **kw):
        raise SyncError("Synthetic detail read failure")

    monkeypatch.setattr(api, "get_contact", fail)
    assert cli.main(args) == 1 and server.writes == 0


def test_cached_details_do_not_bypass_concurrency_check(api, server, monkeypatch, tmp_path):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server, urls=[{"value": "https://example.com/new"}])],
        [],
    )
    answers = iter(["m", "y"])

    def answer():
        value = next(answers)
        if value == "y":
            server.person["metadata"]["sources"][0]["etag"] = "edited"
        return value

    monkeypatch.setattr("builtins.input", answer)
    assert cli.main(args) == 1 and server.writes == 0
    assert server.batch_reads == 2


def test_no_matches_no_detail_reads(api, server, monkeypatch, tmp_path):
    args = setup(
        api, server, monkeypatch, tmp_path, [{"names": [{"givenName": "New Person"}]}], ["n"]
    )
    assert cli.main(args) == 0 and server.batch_reads == 0 and server.writes == 0


def test_listed_contact_details_fixture_contract(api, server):
    """Explicit list fixtures must also serve full records through individual reads."""
    from .test_fixture_contract import fetch

    server.connections = [
        {
            "resourceName": "people/c919",
            "names": [{"givenName": "Fixture"}],
            "metadata": {"sources": [{"type": "CONTACT", "id": "919", "etag": "v1"}]},
            "urls": [{"value": "https://example.com/details"}],
        }
    ]
    status, response = fetch(
        server,
        "/v1/people:batchGet?resourceNames=people/c919&personFields=metadata,names,urls&sources=READ_SOURCE_TYPE_CONTACT",
    )
    assert status == 200
    assert response["responses"][0]["person"] == server.connections[0]
    status, response = fetch(
        server,
        "/v1/people:batchGet?resourceNames=people/c919&personFields=metadata,names&sources=READ_SOURCE_TYPE_CONTACT",
    )
    assert status == 200 and "urls" not in response["responses"][0]["person"]


def test_each_possible_target_has_its_own_result(api, server, monkeypatch, tmp_path, capsys):
    other = deepcopy(server.person)
    other["resourceName"] = "people/c999"
    other["metadata"]["sources"][0]["id"] = "999"
    for entries in other.values():
        if isinstance(entries, list):
            for entry in entries:
                source = entry.get("metadata", {}).get("source")
                if source:
                    source["id"] = "999"
    other["urls"] = [{"value": "https://example.com/new"}]
    server.created["people/c999"] = other
    args = setup(api, server, monkeypatch, tmp_path, [incoming(server, urls=other["urls"])], ["q"])
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    first = output.index("(c123)")
    second = output.index("(c999)")
    assert "New information available" in output[first:second]
    assert "Nothing new" in output[second:]
    assert server.batch_reads == 2 and server.writes == 0


def test_incoming_only_comparison_needs_no_google_detail_read(
    api, server, monkeypatch, tmp_path, capsys
):
    person = {"names": [{"givenName": "Brand", "familyName": "New"}]}
    args = setup(api, server, monkeypatch, tmp_path, [person, person], ["q"])
    assert cli.main(args) == 0
    assert "If combined with this input: Nothing new" in capsys.readouterr().out
    assert server.batch_reads == 0 and server.writes == 0


def test_incompatible_merge_can_still_be_skipped(api, server, monkeypatch, tmp_path, capsys):
    server.person["birthdays"] = [{"date": {"month": 2, "day": 29}}]
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server, birthdays=[{"date": {"year": 2023}}])],
        ["s"],
    )
    assert cli.main(args) == 0
    assert "Cannot merge:" in capsys.readouterr().out
    assert server.writes == 0


def test_new_labels_visible_before_choice(api, server, monkeypatch, tmp_path, capsys):
    args = setup(api, server, monkeypatch, tmp_path, [incoming(server)], ["q"])
    assert cli.main(args + ["--label", "New"]) == 0
    output = capsys.readouterr().out
    assert "Add label New:" in output
    assert server.writes == 0 and not server.groups


def test_matching_contact_completion_message(api, server, capsys):
    from contacts_cli.contact_merge import read_matched_details

    resource = server.person["resourceName"]
    result = read_matched_details({1: [(resource, "Example", ["email"])]}, api)
    assert result[resource]["resourceName"] == resource
    assert server.batch_reads == 1
    output = capsys.readouterr().err
    assert output.endswith("Finished reading matching contacts: 1 of 1.\n")
    assert "finished:" not in output
