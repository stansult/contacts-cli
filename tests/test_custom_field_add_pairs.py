"""Explicit add pairs validate before access and select only new exact pairs."""

from copy import deepcopy

import pytest

from contacts_cli import cli


@pytest.mark.parametrize(
    "options",
    [
        ["--field", "One", "--field", "Two", "Value"],
        ["--field", "One"],
        [],
        ["--key", "One", "--value", "Value"],
        ["--field", "One", "Value", "--key", "Other"],
    ],
)
def test_usage_errors_before_access(monkeypatch, options):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("access"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["add-custom-field", "--contact", "c123", *options])
    assert exc.value.code == 2


@pytest.mark.parametrize("key,value", [("", "v"), ("k", ""), (" ", "v"), ("k", "bad\nvalue")])
def test_invalid_pair_before_access(monkeypatch, key, value):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("access"))
    assert cli.main(["add-custom-field", "--contact", "c123", "--field", key, value]) == 1


@pytest.mark.parametrize(
    "mode,answers,wanted",
    [
        ("subset", ["3,1", "y"], [0, 2]),
        ("reselect", ["all", "n", "2", "y"], [1]),
        ("cancel", ["q"], []),
        ("preview", None, []),
        ("apply", [], [0, 1, 2]),
    ],
)
def test_new_pairs_and_selection(api, server, monkeypatch, capsys, mode, answers, wanted):
    current = [{"key": "ID", "value": "old"}] * 2
    server.person["userDefined"] = deepcopy(current)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (cli.sys.stdin, cli.sys.stdout, cli.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: answers is not None)
    replies = iter(answers or [])

    def answer():
        assert server.writes == 0
        return next(replies)

    monkeypatch.setattr("builtins.input", answer)
    pairs = [("status", "active"), ("Status", "active"), ("Status", "Active")]
    args = ["add-custom-fields", "--contact", "c123"]
    for key, value in [("ID", "old"), *pairs, pairs[0]]:
        args += ["--field", key, value]
    if mode == "apply":
        args += ["--apply"]
    assert cli.main(args) == 0
    assert server.person["userDefined"] == current + [
        {"key": pairs[i][0], "value": pairs[i][1]} for i in wanted
    ]
    assert server.writes == bool(wanted)
    output = capsys.readouterr().out
    assert "3 entries" in output
    assert "Existing custom field entries" not in output
    assert "Remaining custom field entries" not in output
    if mode == "subset":
        assert "Selected custom field additions: 2 entries" in output
        assert "3. Status — Active" in output


@pytest.mark.parametrize("fault", ["concurrent", "readback"])
def test_selected_addition_preserves_verification(api, server, monkeypatch, fault):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (cli.sys.stdin, cli.sys.stdout, cli.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    replies = iter(["2", "y"])
    monkeypatch.setattr("builtins.input", lambda: next(replies))
    original = api.get_contact
    calls = 0

    def changed(*a, **kw):
        nonlocal calls
        calls += 1
        if fault == "concurrent" and calls == 2:
            server.person.setdefault("userDefined", []).append({"key": "Other", "value": "New"})
        saved = original(*a, **kw)
        if fault == "readback" and server.writes:
            saved["userDefined"] = []
        return saved

    monkeypatch.setattr(api, "get_contact", changed)
    assert cli.main(
        ["add-custom-field", "--contact", "c123", "--field", "A", "1", "--field", "B", "2"]
    ) == (1 if fault == "concurrent" else 3)
    assert server.writes == (0 if fault == "concurrent" else 1)
