"""Individual review shows current merge value before offering a merge action."""

import pytest

from contacts_cli import cli

from .test_contact_merge import incoming, setup


@pytest.mark.parametrize("kind", ["same", "conflict", "new", "label", "new-label"])
def test_review_shows_result_and_only_useful_merge(
    api, server, monkeypatch, tmp_path, capsys, kind
):
    fields = {}
    if kind == "conflict":
        fields["names"] = [{"givenName": "Different"}]
    if kind == "new":
        fields["urls"] = [{"value": "https://example.com/new"}]
    args = setup(api, server, monkeypatch, tmp_path, [incoming(server, **fields)], [])
    if kind in {"label", "new-label"}:
        if kind == "label":
            server.groups["contactGroups/test"] = {
                "resourceName": "contactGroups/test",
                "name": "Test",
                "groupType": "USER_CONTACT_GROUP",
            }
        args += ["--label", "Test"]

    def answer():
        output = capsys.readouterr().out
        if "Skip these inputs?" in output:
            return "n"
        review = output.split(" — possible match:\n")[-1]
        assert ("  m   Merge" in review) == (kind in {"new", "label", "new-label", "conflict"})
        expected = {
            "same": "Nothing new",
            "conflict": "Conflicts to resolve",
            "new": "New information available",
            "label": "labels to add: Test",
            "new-label": "labels to add: Test",
        }[kind]
        assert expected in review
        return "q"

    monkeypatch.setattr("builtins.input", answer)
    assert cli.main(args) == 0
    assert server.writes == 0


def test_only_useful_target_is_selectable(api, server, monkeypatch, capsys):
    from copy import deepcopy

    from contacts_cli.contact_merge import review_import

    original = deepcopy(server.person)
    other = deepcopy(original)
    other["resourceName"] = "people/c999"
    other["metadata"]["sources"][0]["id"] = "999"
    for entries in other.values():
        if isinstance(entries, list):
            for entry in entries:
                source = entry.get("metadata", {}).get("source")
                if source:
                    source["id"] = "999"
    other["urls"] = [{"value": "https://example.com/new"}]
    person = incoming(server, urls=other["urls"])
    monkeypatch.setattr("builtins.input", lambda: "m")
    review = review_import(
        [1], [person], [original, other], api, {p["resourceName"]: p for p in [original, other]}
    )
    assert list(review.merges) == [original["resourceName"]]
    output = capsys.readouterr().out
    assert "Nothing new" in output and "New information available" in output
    assert "Merge targets:" not in output
    assert server.batch_reads == 0 and server.writes == 0


def test_hidden_merge_is_not_accepted(api, server, monkeypatch, tmp_path, capsys):
    args = setup(api, server, monkeypatch, tmp_path, [incoming(server)], ["n", "m", "s"])
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    assert "Choose s, c, or q." in output
    assert "Merge input" not in output and server.writes == 0


def test_complete_josh_does_not_redirect_merge_to_name_only_match(api, server, monkeypatch, capsys):
    from contacts_cli.contact_merge import review_import

    incoming = {"names": [{"givenName": "Josh"}], "phoneNumbers": [{"value": "+12025550142"}]}
    complete = {
        **incoming,
        "resourceName": "people/c1",
        "metadata": {"sources": [{"type": "CONTACT", "id": "1", "etag": "v1"}]},
    }
    unrelated = {
        "names": [{"givenName": "Josh"}],
        "phoneNumbers": [{"value": "+12025550143"}],
        "resourceName": "people/c2",
        "metadata": {"sources": [{"type": "CONTACT", "id": "2", "etag": "v1"}]},
    }
    answers = iter(["m", "s"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    review = review_import(
        [1], [incoming], [complete, unrelated], api, {"people/c1": complete, "people/c2": unrelated}
    )
    output = capsys.readouterr().out
    assert "Nothing new" in output
    assert "c2" not in output
    assert "Choose s, c, or q." in output
    assert not review.merges and not review.creates
    assert server.writes == 0


@pytest.mark.parametrize("label", [False, True])
def test_prior_merge_makes_repeated_input_unnecessary(
    api, server, monkeypatch, tmp_path, capsys, label
):
    person = (
        incoming(server) if label else incoming(server, urls=[{"value": "https://example.com/new"}])
    )
    args = setup(api, server, monkeypatch, tmp_path, [person, person], ["all", "m", "s", "y"])
    if label:
        args += ["--label", "New"]
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    second = output.split("2. Unnamed contact — possible match:")[-1].split("Skipped input")[0]
    assert "Nothing new" in second
    assert "  m   Merge" not in second
    assert server.writes == (2 if label else 1)
