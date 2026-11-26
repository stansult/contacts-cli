"""Partial selection saves only the displayed choices, preserving existing entries."""

from copy import deepcopy

import pytest

from contacts_cli import cli

from .test_exclude_other import ARGS, configure


@pytest.mark.parametrize(
    "answers,expected",
    [
        (["n", "2", "y"], ["trash@example.com"]),
        (["n", "2-100", "y"], ["trash@example.com"]),
        (["n", "1-2", "n", "2", "y"], ["trash@example.com"]),
        (["n", "all", "y"], ["new@example.com", "trash@example.com"]),
        (["n", "q"], []),
        (["n", None], []),
    ],
)
def test_grouped_partial_selection(api, server, monkeypatch, capsys, answers, expected):
    before = deepcopy(server.person["emailAddresses"])
    configure(api, server, monkeypatch, tty=True, answers=answers)
    assert cli.main(ARGS) == 0
    assert server.person["emailAddresses"] == before + [
        {"value": value, **({"type": "New sender"} if value == "new@example.com" else {})}
        for value in expected
    ]
    assert server.writes == bool(expected)
    output = capsys.readouterr().out
    assert "3-5,8   Select by number or range" in output
    if expected == ["trash@example.com"]:
        assert "Selected additions: 1 address\n  2. trash@example.com" in output
    if answers[1] == "all":
        assert "Selected additions:" not in output


def test_ungrouped_partial_selection(api, server, monkeypatch):
    query = "subject:delivery"
    configure(api, server, monkeypatch, tty=True, answers=["2", "y"], query=query)
    before = deepcopy(server.person["emailAddresses"])
    assert cli.main(["sender-sync", "--contact", "c123", "--search", query]) == 0
    assert server.person["emailAddresses"] == before + [{"value": "trash@example.com"}]


def test_excluded_numbers_cannot_be_selected(api, server, monkeypatch, capsys):
    query = "from:new@example.com OR from:spam@example.com OR subject:delivery"
    configure(api, server, monkeypatch, tty=True, answers=["y", "3", "2", "y"], query=query)
    server.search_results[query] = {"m2", "m4", "m5"}
    before = deepcopy(server.person["emailAddresses"])
    assert cli.main(["sender-sync", "--contact", "c123", "--search", query]) == 0
    assert server.person["emailAddresses"] == before + [{"value": "spam@example.com"}]
    assert "Use only displayed item numbers." in capsys.readouterr().out


@pytest.mark.parametrize("tty", [(False, True, True), (True, False, True), (True, True, False)])
def test_redirected_stream_prevents_selection(api, server, monkeypatch, tty):
    import sys

    configure(api, server, monkeypatch)
    for stream, value in zip((sys.stdin, sys.stdout, sys.stderr), tty, strict=True):
        monkeypatch.setattr(stream, "isatty", lambda value=value: value)
    assert cli.main(ARGS) == 0
    assert server.writes == 0


@pytest.mark.parametrize("answers", [["n", "all", "", "q"], ["n", "all", None], ["n", None]])
def test_confirmation_back_and_eof_cancel(api, server, monkeypatch, answers):
    configure(api, server, monkeypatch, tty=True, answers=answers)
    assert cli.main(ARGS) == 0
    assert server.writes == 0


def test_menu_and_confirmation_invalid_answers_retry(api, server, monkeypatch):
    configure(
        api, server, monkeypatch, tty=True, answers=["n", "", "wrong", "all", "wrong", " YES "]
    )
    assert cli.main(ARGS) == 0
    assert server.writes == 1


@pytest.mark.parametrize("number", [1, 7])
@pytest.mark.parametrize("answer", ["y", "n", "", "q", None])
def test_single_available_address_has_simple_confirmation(monkeypatch, capsys, number, answer):
    from contacts_cli.selection import review_address_additions

    def respond():
        output = capsys.readouterr().out
        assert "Add this address to this contact? [y/N] " in output
        assert "Cancel" not in output
        assert "Choose addresses" not in output
        if answer is None:
            raise EOFError
        return answer

    monkeypatch.setattr("builtins.input", respond)
    result = review_address_additions([(number, "one@example.com")])
    assert result == ([number] if answer == "y" else None)


def test_one_selected_from_many_retains_return_choice(monkeypatch, capsys):
    from contacts_cli.selection import review_address_additions

    answers = iter(["2", "n", "1", "y"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    assert review_address_additions([(1, "one@example.com"), (2, "two@example.com")]) == [1]
    output = capsys.readouterr().out
    assert "n   Return to selection" in output
    assert "n   Cancel" not in output
