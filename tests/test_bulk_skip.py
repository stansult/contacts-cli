"""Bulk skip is limited to selected, fully unchanged saved-contact matches."""

import pytest

from contacts_cli import cli

from .test_contact_merge import incoming, setup


@pytest.mark.parametrize("answer", ["", "y", "yes", "q", None])
def test_bulk_skip_default_and_cancel(api, server, monkeypatch, tmp_path, capsys, answer):
    args = setup(api, server, monkeypatch, tmp_path, [incoming(server)], [])

    def respond():
        output = capsys.readouterr().out
        assert "Already contain all supplied information: 1 input" in output
        assert "Skip these inputs? [Y/n]" in output
        if answer is None:
            raise EOFError
        return answer

    monkeypatch.setattr("builtins.input", respond)
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    assert ("Cancelled" in output) == (answer in ("q", None))
    assert "Choice [s]" not in output and server.writes == 0


def test_decline_retains_individual_review(api, server, monkeypatch, tmp_path, capsys):
    args = setup(api, server, monkeypatch, tmp_path, [incoming(server)], ["n", "s"])
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    assert "Skip these inputs? [Y/n]" in output and "Choice [s]" in output
    assert server.writes == 0


def test_skip_only_selected_and_keep_creation_approval(api, server, monkeypatch, tmp_path, capsys):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server), {"names": [{"givenName": "New"}]}],
        ["all", "", "n"],
    )
    assert cli.main(args) == 0 and server.writes == 0
    output = capsys.readouterr()
    assert "Skipped 1 unchanged input." in output.out
    assert "Contacts to create: 1" in output.out
    assert "Already-complete inputs skipped: 1" in output.out
    assert "Apply these changes?" in output.err


@pytest.mark.parametrize("apply", [False, True])
def test_noninteractive_never_bulk_skips(api, server, monkeypatch, tmp_path, capsys, apply):
    args = setup(api, server, monkeypatch, tmp_path, [incoming(server)], [])
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    assert cli.main(args + (["--apply"] if apply else [])) == (1 if apply else 0)
    assert "Skip these inputs?" not in capsys.readouterr().out
    assert server.writes == 0


def test_apply_still_asks_before_bulk_skip(api, server, monkeypatch, tmp_path, capsys):
    args = setup(api, server, monkeypatch, tmp_path, [incoming(server)], [""])
    assert cli.main(args + ["--apply"]) == 0
    assert "Skip these inputs? [Y/n]" in capsys.readouterr().out
    assert server.writes == 0


def test_unselected_unchanged_input_is_not_offered(api, server, monkeypatch, tmp_path, capsys):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server), {"names": [{"givenName": "New"}]}],
        ["2", "n"],
    )
    assert cli.main(args) == 0 and server.writes == 0
    assert "Skip these inputs?" not in capsys.readouterr().out


@pytest.mark.parametrize("case", ["all-saved", "useful", "conflict", "input", "invalid", "label"])
def test_every_target_must_be_unchanged_saved_contact(monkeypatch, case):
    from contacts_cli.contact_merge import skip_unchanged_inputs

    matches = {1: [("people/c1", {}, []), ("input #2" if case == "input" else "people/c2", {}, [])]}
    assessments = {
        1: {
            key: ("summary", False, case in {"all-saved", "input"} or key == "people/c1")
            for key, _, _ in matches[1]
        }
    }
    calls = []

    def answer():
        calls.append(True)
        return ""

    monkeypatch.setattr("builtins.input", answer)
    assert skip_unchanged_inputs([1], matches, assessments) == ([] if case == "all-saved" else [1])
    assert bool(calls) == (case == "all-saved")


def test_invalid_answer_reprompts_then_cancel(api, server, monkeypatch, tmp_path, capsys):
    args = setup(api, server, monkeypatch, tmp_path, [incoming(server)], ["wrong", "q"])
    assert cli.main(args) == 0 and server.writes == 0
    output = capsys.readouterr().out
    assert "Enter y to skip, n to review individually, or q to cancel." in output
    assert "Cancelled" in output


@pytest.mark.parametrize("kind", ["conflict", "new", "label", "input", "invalid"])
def test_ineligible_inputs_keep_individual_review(api, server, monkeypatch, tmp_path, capsys, kind):
    person = incoming(server)
    if kind == "conflict":
        person["names"] = [{"givenName": "Different"}]
    if kind == "new":
        person["urls"] = [{"value": "https://example.com/new"}]
    if kind == "invalid":
        server.person["birthdays"] = [{"date": {"month": 2, "day": 29}}]
        person["birthdays"] = [{"date": {"year": 2023}}]
    inputs = [person, person] if kind == "input" else [person]
    args = setup(
        api, server, monkeypatch, tmp_path, inputs, ["all", "q"] if kind == "input" else ["q"]
    )
    assert cli.main(args + (["--label", "New"] if kind == "label" else [])) == 0
    output = capsys.readouterr().out
    assert "Skip these inputs?" not in output
    assert ("Choose contacts to label" if kind == "label" else "Choice [s]") in output
    assert server.writes == 0


def test_multiple_unchanged_inputs_skipped_with_one_answer(
    api, server, monkeypatch, tmp_path, capsys
):
    from copy import deepcopy

    other = deepcopy(server.person)
    other["resourceName"] = "people/c999"
    other["metadata"]["sources"][0]["id"] = "999"
    other["names"] = [{"givenName": "Other"}]
    other["emailAddresses"] = [{"value": "other@example.com"}]
    for entries in other.values():
        if isinstance(entries, list):
            for entry in entries:
                source = entry.get("metadata", {}).get("source")
                if source:
                    source["id"] = "999"
    server.created["people/c999"] = other
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [incoming(server), {"emailAddresses": [{"value": "other@example.com"}]}],
        ["all", ""],
    )
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    assert "Already contain all supplied information: 2 inputs" in output
    assert "Skipped 2 unchanged inputs." in output
    assert output.count("Skip these inputs?") == 1
    assert "Choice [s]" not in output and server.writes == 0
