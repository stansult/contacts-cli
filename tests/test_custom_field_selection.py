"""Remove selected exact key/value groups without changing other custom fields."""

from copy import deepcopy

import pytest

from contacts_cli import cli

VALUES = [
    {"key": "ID", "value": "A"},
    {"key": "ID", "value": "B"},
    {"key": "ID", "value": "A"},
    {"key": "ID", "value": "b"},
    {"key": "id", "value": "C"},
    {"key": "Other", "value": "Keep"},
]


def setup(api, server, monkeypatch, answers):
    server.person["userDefined"] = deepcopy(VALUES)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (cli.sys.stdin, cli.sys.stdout, cli.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: answers is not None)
    replies = iter(answers or [])

    def answer():
        assert server.writes == 0
        value = next(replies)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr("builtins.input", answer)
    return ["remove-custom-field", "--contact", "c123", "--key", "ID"]


@pytest.mark.parametrize(
    "answers,removed",
    [
        (["1", "y"], {"A"}),
        (["3,1-2,1", "y"], {"A", "B", "b"}),
        (["all", "n", "2", "y"], {"B"}),
        (["9", "3", "y"], {"b"}),
        (["2,4", "y"], {"B", "C"}),
        (["q"], set()),
        (["1", "q"], set()),
        ([EOFError()], set()),
        (["1", EOFError()], set()),
        (None, set()),
    ],
)
def test_selection(api, server, monkeypatch, capsys, answers, removed):
    args = setup(api, server, monkeypatch, answers)
    before = deepcopy(server.person)
    assert cli.main(args) == 0
    assert server.person["userDefined"] == [
        e for e in VALUES if not (e["key"].casefold() == "id" and e["value"] in removed)
    ]
    for key in before.keys() - {"userDefined", "metadata"}:
        assert server.person[key] == before[key]
    assert server.writes == bool(removed)
    output = capsys.readouterr().out
    assert "1. ID — A (2 entries)" in output
    assert "4. id — C" in output
    assert "Informational only" not in output
    assert "Exact matches: 4 entries" in output
    assert "Similar entries (case differs): 1 entry" in output
    assert "Existing custom field entries:" not in output
    assert "Remaining custom field entries:" not in output
    if removed == {"A"}:
        assert "Selected custom field removals: 2 entries" in output
        assert "Removed and verified 2 custom field entries" in output
    if removed == {"b"}:
        assert "Use only displayed item numbers" in output


def test_apply_all_without_prompt(api, server, monkeypatch):
    args = setup(api, server, monkeypatch, [])
    assert cli.main(args + ["--apply"]) == 0
    assert server.person["userDefined"] == VALUES[5:]


def test_one_duplicate_group_confirms_entry_count(api, server, monkeypatch, capsys):
    args = setup(api, server, monkeypatch, ["y"])
    assert cli.main(args + ["--value", "A"]) == 0
    output = capsys.readouterr()
    assert "Choose" not in output.out
    assert "Remove 2 custom field entries?" in output.err
    assert server.person["userDefined"] == [e for e in VALUES if e["value"] != "A"]


def test_concurrent_change_rejects_selected_write(api, server, monkeypatch):
    args = setup(api, server, monkeypatch, ["1", "y"])
    original = api.get_contact
    calls = 0

    def changed(*a, **kw):
        nonlocal calls
        calls += 1
        if calls == 2:
            server.person["userDefined"].append({"key": "New", "value": "Concurrent"})
        return original(*a, **kw)

    monkeypatch.setattr(api, "get_contact", changed)
    assert cli.main(args) == 1
    assert server.writes == 0


def test_interrupt_selection_makes_no_write(api, server, monkeypatch):
    args = setup(api, server, monkeypatch, [KeyboardInterrupt()])
    assert cli.main(args) == 130
    assert server.person["userDefined"] == VALUES
    assert server.writes == 0


def test_empty_stored_value_is_one_group_and_other_metadata_survives(api, server, monkeypatch):
    args = setup(api, server, monkeypatch, ["1", "y"])
    kept = {"key": "ID", "value": "Keep", "metadata": {"primary": False}}
    server.person["userDefined"] = [{"key": "ID", "value": ""}, kept, {"key": "ID", "value": ""}]
    assert cli.main(args) == 0
    assert server.person["userDefined"] == [kept]


@pytest.mark.parametrize("value", [None, "c"])
def test_only_case_different_matches(api, server, monkeypatch, capsys, value):
    args = setup(api, server, monkeypatch, ["y"])
    server.person["userDefined"] = [{"key": "id", "value": "C"}]
    if value is not None:
        args += ["--value", value]
    assert cli.main(args) == 0
    assert server.person["userDefined"] == []
    output = capsys.readouterr().out
    assert "Similar entries (case differs): 1 entry" in output
    assert "Informational only" not in output
