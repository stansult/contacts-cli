"""Case-only Gmail label selection through the offline CLI."""

import sys

import pytest

from contacts_cli import cli


def setup(api, server, monkeypatch, *, interactive=True, names=("Example/Delivery",)):
    server.mailbox["labels"] = [
        {"id": f"Label_{index}", "name": name} for index, name in enumerate(names, 1)
    ]
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: interactive)
    monkeypatch.setattr(cli, "review_address_additions", lambda rows: None)


ARGS = ["sender-sync", "--label", "example/delivery", "--contact", "c123"]


@pytest.mark.parametrize("apply", [False, True])
def test_single_case_match_default_yes(api, server, monkeypatch, capsys, apply):
    setup(api, server, monkeypatch)
    monkeypatch.setattr("builtins.input", lambda: "")
    assert cli.main(ARGS + (["--apply"] if apply else [])) == 0
    output = capsys.readouterr()
    assert "Use existing Gmail label 'Example/Delivery'? [Y/n]" in output.err
    assert "Label: 'Example/Delivery'" in output.out
    assert server.writes == int(apply)


@pytest.mark.parametrize("answer", ["n", "EOF"])
def test_decline_stops_before_search(api, server, monkeypatch, capsys, answer):
    setup(api, server, monkeypatch)

    def respond():
        if answer == "EOF":
            raise EOFError
        return answer

    monkeypatch.setattr("builtins.input", respond)
    assert cli.main(ARGS + ["--apply"]) == 0
    assert "Cancelled; no changes made." in capsys.readouterr().out
    assert not any(call[1].endswith("/messages") for call in server.calls)
    assert server.writes == 0


@pytest.mark.parametrize("apply", [False, True])
def test_noninteractive_shows_exact_alternatives(api, server, monkeypatch, capsys, apply):
    setup(api, server, monkeypatch, interactive=False)
    assert cli.main(ARGS + (["--apply"] if apply else [])) == 1
    error = capsys.readouterr().err
    assert "'Example/Delivery'" in error and "exact" in error
    assert server.writes == 0


def test_exact_match_wins(api, server, monkeypatch):
    setup(api, server, monkeypatch, names=("example/delivery", "Example/Delivery"))
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("unexpected choice"))
    assert cli.main(ARGS) == 0
    assert server.writes == 0


@pytest.mark.parametrize("answer", ["2", "3"])
def test_multiple_matches_choose_or_cancel(api, server, monkeypatch, capsys, answer):
    setup(api, server, monkeypatch, names=("EXAMPLE/DELIVERY", "Example/Delivery"))
    responses = iter(["invalid", answer])
    monkeypatch.setattr("builtins.input", lambda: next(responses))
    assert cli.main(ARGS) == 0
    output = capsys.readouterr()
    assert "Choose 1–3 (Enter = 1)" in output.err
    assert "Cancel command" in output.out
    assert "Create" not in output.out
    if answer == "2":
        assert "Label: 'Example/Delivery'" in output.out
        searches = [call for call in server.calls if call[1].endswith("/messages")]
        assert searches[0][2]["labelIds"] == ["Label_2"]
    else:
        assert "Cancelled" in output.out
    assert server.writes == 0


def test_missing_label_is_clear(api, server, monkeypatch, capsys):
    setup(api, server, monkeypatch, names=())
    assert cli.main(ARGS) == 1
    assert "Gmail label 'example/delivery' was not found" in capsys.readouterr().err
    assert server.writes == 0


@pytest.mark.parametrize("answer", ["", "EOF"])
def test_multiple_default_and_eof(api, server, monkeypatch, capsys, answer):
    setup(api, server, monkeypatch, names=("EXAMPLE/DELIVERY", "Example/Delivery"))

    def respond():
        if answer == "EOF":
            raise EOFError
        return answer

    monkeypatch.setattr("builtins.input", respond)
    assert cli.main(ARGS) == 0
    output = capsys.readouterr().out
    if answer == "EOF":
        assert "Cancelled" in output
    if answer == "":
        assert "Label: 'EXAMPLE/DELIVERY'" in output
    assert server.writes == 0


def test_single_invalid_answer_reprompts(api, server, monkeypatch, capsys):
    setup(api, server, monkeypatch)
    answers = iter(["maybe", "YES"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    assert cli.main(ARGS) == 0
    output = capsys.readouterr()
    assert "Enter y or n." in output.err
    assert "Label: 'Example/Delivery'" in output.out


@pytest.mark.parametrize(
    "labels",
    [
        [{"name": "Example/Delivery", "id": ""}],
        [
            {"name": "Example/Delivery", "id": "Label_1"},
            {"name": "Example/Delivery", "id": "Label_2"},
        ],
    ],
)
def test_selected_invalid_or_ambiguous_label_blocks_search(api, server, monkeypatch, labels):
    setup(api, server, monkeypatch)
    server.mailbox["labels"] = labels
    monkeypatch.setattr("builtins.input", lambda: "")
    assert cli.main(ARGS + ["--apply"]) == 1
    assert not any(call[1].endswith("/messages") for call in server.calls)
    assert server.writes == 0
