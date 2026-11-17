"""Group selection must change the saved plan, not merely its preview (#8)."""

import sys
from copy import deepcopy

import pytest

from contacts_cli import cli

QUERY = "from:new@example.com OR subject:delivery"
ARGS = ["sender-sync", "--contact", "c123", "--search", QUERY]


def configure(api, server, monkeypatch, *, tty=False, answers=(), query=QUERY):
    server.search_results[query] = {"m2", "m4"}
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: tty)
    replies = iter(answers)

    def answer():
        result = next(replies)  # An unexpected extra prompt fails the test.
        if result is None:
            raise EOFError
        return result

    monkeypatch.setattr("builtins.input", answer)


@pytest.mark.parametrize(
    "answers,expected",
    [
        (["y", "y"], {"new@example.com"}),
        (["n", "all", "y"], {"new@example.com", "trash@example.com"}),
        (["", "all", "y"], {"new@example.com", "trash@example.com"}),
        (["invalid", "yes", "y"], {"new@example.com"}),
        (["y", "n"], set()),
        ([None], set()),
        (["y", None], set()),
    ],
)
def test_interactive_selection(api, server, monkeypatch, capsys, answers, expected):
    original = deepcopy(server.person["emailAddresses"])
    configure(api, server, monkeypatch, tty=True, answers=answers)
    assert cli.main(ARGS) == 0
    output = capsys.readouterr()
    assert "Exclude Other senders? [y/N]" in output.err
    saved = server.person["emailAddresses"]
    assert saved[: len(original)] == original
    assert {entry["value"] for entry in saved[len(original) :]} == expected
    assert server.writes == bool(expected)
    if expected:
        count = len(expected)
        noun = "addition" if count == 1 else "additions"
        assert f"Saved and verified {count} {noun}." in output.out
    if answers[0] in {"n", ""}:
        assert "Available from both groups: 2 addresses." in output.out
        assert "Add these 2 addresses to this contact?" in output.out
    if answers[0] == "y":
        assert "Available from only Matching address criteria: 1 address." in output.out
        assert "Will skip Other senders: 1 address." in output.out
        assert "Add this address to this contact?" in output.out
        if not expected:
            assert "Cancelled; no changes made." in output.out


@pytest.mark.parametrize(
    "tty,apply,flag,expected",
    [
        (False, False, False, set()),
        (False, False, True, set()),
        (False, True, False, {"new@example.com", "trash@example.com"}),
        (False, True, True, {"new@example.com"}),
        (True, True, False, {"new@example.com", "trash@example.com"}),
        (True, True, True, {"new@example.com"}),
    ],
)
def test_flags_and_noninteractive(api, server, monkeypatch, capsys, tty, apply, flag, expected):
    configure(api, server, monkeypatch, tty=tty)
    original = deepcopy(server.person["emailAddresses"])
    assert (
        cli.main(ARGS + (["--apply"] if apply else []) + (["--exclude-other"] if flag else [])) == 0
    )
    output = capsys.readouterr()
    assert "Exclude Other senders?" not in output.err
    assert {
        entry["value"] for entry in server.person["emailAddresses"][len(original) :]
    } == expected
    assert server.person["emailAddresses"][: len(original)] == original
    if flag:
        assert "Other senders (excluded): 1 address" in output.out
        assert ("Adding: 1 entry" if apply else "Proposed additions: 1 entry") in output.out
        assert "Both groups are included." not in output.out
    assert server.writes == bool(expected)


@pytest.mark.parametrize(
    "source",
    [
        ["--search", "subject:delivery"],
        ["--search", "from:example"],
        ["--search=-from:example.com"],
    ],
)
def test_unusable_criteria_fail_before_auth(monkeypatch, capsys, source):
    monkeypatch.setattr(
        cli, "connect_with_authorization", lambda *a: pytest.fail("authorization reached")
    )
    assert cli.main(["sender-sync", "--contact", "c123", *source, "--exclude-other"]) == 1
    assert "--exclude-other requires full addresses or domains" in capsys.readouterr().err


def test_all_other_selected_out_is_noop(api, server, monkeypatch, capsys):
    query = "from:elsewhere.example.com OR subject:delivery"
    configure(api, server, monkeypatch, tty=True, answers=["y"], query=query)
    assert cli.main(["sender-sync", "--contact", "c123", "--search", query]) == 0
    output = capsys.readouterr()
    assert "No additions selected; no update made." in output.out
    assert "to this contact?" not in output.err
    assert server.writes == 0


def test_no_other_does_not_ask_group_question(api, server, monkeypatch, capsys):
    query = "to:example.com"
    configure(api, server, monkeypatch, tty=True, answers=["q"], query=query)
    assert cli.main(["sender-sync", "--contact", "c123", "--search", query]) == 0
    assert "Exclude Other senders?" not in capsys.readouterr().err
    assert server.writes == 0


def test_flag_still_requires_final_confirmation(api, server, monkeypatch, capsys):
    configure(api, server, monkeypatch, tty=True, answers=["y"])
    assert cli.main(ARGS + ["--exclude-other"]) == 0
    output = capsys.readouterr()
    assert "Exclude Other senders?" not in output.err
    assert "Add this address to this contact?" in output.out
    assert server.writes == 1
    assert "trash@example.com" not in {e["value"] for e in server.person["emailAddresses"]}


def test_manual_exclusion_can_leave_only_other(api, server, monkeypatch, capsys):
    configure(api, server, monkeypatch)
    assert cli.main(ARGS + ["--exclude", "new@example.com", "--exclude-other", "--apply"]) == 0
    assert "No additions selected" in capsys.readouterr().out
    assert server.writes == 0


def test_excluding_does_not_bypass_verification(api, server, monkeypatch):
    configure(api, server, monkeypatch)
    server.lose_additions = True
    assert cli.main(ARGS + ["--exclude-other", "--apply"]) == 3
    assert server.writes == 1


def test_bad_header_blocks_selection_and_write(api, server, monkeypatch, capsys):
    configure(api, server, monkeypatch, tty=True)
    server.mailbox["messages"][3]["payload"]["headers"] = []
    assert cli.main(ARGS + ["--exclude-other", "--apply"]) == 1
    assert "Preview is incomplete" in capsys.readouterr().err
    assert server.writes == 0


def test_empty_results_skip_both_questions(api, server, monkeypatch, capsys):
    configure(api, server, monkeypatch, tty=True)
    server.search_results[QUERY] = set()
    assert cli.main(ARGS + ["--exclude-other"]) == 0
    output = capsys.readouterr()
    assert "No additions needed" in output.out
    assert "Exclude Other senders?" not in output.err
    assert "to this contact?" not in output.err
    assert server.writes == 0
