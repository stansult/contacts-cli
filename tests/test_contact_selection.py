"""Creation selects original input rows before any contact or label write."""

import json

import pytest

from contacts_cli import cli


def setup(api, server, monkeypatch, tmp_path, answers):
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
    file = tmp_path / "contacts.json"
    file.write_text(
        json.dumps([{"names": [{"unstructuredName": f"Person {i}"}]} for i in range(1, 5)])
    )
    return ["add-contact", "--file", str(file), "--label", "New"]


@pytest.mark.parametrize(
    "answers,expected",
    [
        (["2,4", "y"], [2, 4]),
        (["4,2-3,2", "y"], [2, 3, 4]),
        (["all", "n", "3", "y"], [3]),
        (["9", "2", "y"], [2]),
        (["q"], []),
        (["2", "q"], []),
        ([EOFError()], []),
        (["2", EOFError()], []),
        (None, []),
    ],
)
def test_selection(api, server, monkeypatch, tmp_path, capsys, answers, expected):
    args = setup(api, server, monkeypatch, tmp_path, answers)
    assert cli.main(args) == 0
    assert [p["names"][0]["unstructuredName"] for p in server.created.values()] == [
        f"Person {i}" for i in expected
    ]
    assert len(server.groups) == bool(expected)
    output = capsys.readouterr().out
    if expected:
        assert f"Created and verified {len(expected)} contact" in output
        for i in expected:
            assert f"input #{i}" in output
        for p in server.created.values():
            assert len(p["memberships"]) == 1
            assert p["userDefined"][-1]["key"] == "Created"
    else:
        assert server.writes == 0
    if expected == [2, 4]:
        selected = output.split("Selected contacts:", 1)[1].split("Create these", 1)[0]
        assert "2. Person 2" in selected and "4. Person 4" in selected
        assert "Person 1" not in selected and "Person 3" not in selected


def test_apply_skips_selection(api, server, monkeypatch, tmp_path):
    args = setup(api, server, monkeypatch, tmp_path, [])
    assert cli.main(args + ["--apply"]) == 0
    assert len(server.created) == 4 and len(server.groups) == 1


@pytest.mark.parametrize("interrupted", [False, True])
def test_subset_failure_uses_input_number_and_selected_counts(
    api, server, monkeypatch, tmp_path, capsys, interrupted
):
    args = setup(api, server, monkeypatch, tmp_path, ["2-4", "y"])
    original = api.write

    def fail(request, **kwargs):
        if len(server.created) == 1:
            if interrupted:
                raise KeyboardInterrupt
            server.create_status = 400
        return original(request, **kwargs)

    monkeypatch.setattr(api, "write", fail)
    assert cli.main(args) == (130 if interrupted else 1)
    output = capsys.readouterr().out
    assert "Contact #3" in output
    assert "1 created; 1 verified; 1 not attempted" in output
    assert len(server.created) == 1


def test_single_contact_keeps_simple_confirmation(api, server, monkeypatch, tmp_path, capsys):
    setup(api, server, monkeypatch, tmp_path, ["y"])
    assert cli.main(["add-contact", "--name", "Single"]) == 0
    output = capsys.readouterr()
    assert "Choose contacts" not in output.out
    assert "[y/N]" in output.err
    assert len(server.created) == 1


def test_all_selection_avoids_repeated_preview(api, server, monkeypatch, tmp_path, capsys):
    args = setup(api, server, monkeypatch, tmp_path, ["all", "y"])
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    assert "Selected contacts" not in output
    assert output.count("1. Person 1") == 1
    assert len(server.created) == 4


def test_invalid_input_cannot_be_skipped_by_selection(api, server, monkeypatch, tmp_path):
    args = setup(api, server, monkeypatch, tmp_path, [])
    (tmp_path / "contacts.json").write_text(
        json.dumps(
            [
                {"names": [{"unstructuredName": "Valid"}]},
                {"emailAddresses": [{"value": "invalid"}]},
            ]
        )
    )
    monkeypatch.setattr(
        cli, "connect_with_authorization", lambda *a: pytest.fail("Google accessed")
    )
    assert cli.main(args) == 1
    assert server.writes == 0
