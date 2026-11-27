"""Duplicate-only removals retain one original occurrence per normalized address."""

from copy import deepcopy

import pytest

from contacts_cli import cli
from tests.test_email_selection import setup


def entries():
    return [
        {"value": "a@example.com", "type": "Work"},
        {"value": "unique@example.org"},
        {"value": "A@example.com", "type": "Home", "metadata": {"sourcePrimary": True}},
        {"value": "a@example.com", "displayName": "Example"},
        {"value": "b@example.com"},
        {"value": "b@example.com"},
        {"value": "a+tag@example.com"},
    ]


@pytest.mark.parametrize("selection,removed", [("all", [0, 3, 5]), ("2", [3]), ("1,3", [0, 5])])
def test_duplicate_selection_preserves_survivors(
    api, server, monkeypatch, capsys, selection, removed
):
    before = entries()
    server.person["emailAddresses"] = deepcopy(before)
    setup(api, monkeypatch, [selection, "y"])
    assert cli.main(["remove-email", "--contact", "c123", "--duplicates"]) == 0
    assert server.person["emailAddresses"] == [
        entry for i, entry in enumerate(before) if i not in removed
    ]
    assert server.writes == 1
    output = capsys.readouterr().out
    assert "Kept entries: 2 entries" in output
    assert "A@example.com — Home (primary)" in output
    assert "Informational only; these numbers cannot be selected." in output


@pytest.mark.parametrize("mode", ["apply", "preview", "cancel", "stale"])
def test_duplicate_modes(api, server, monkeypatch, mode):
    before = entries()
    server.person["emailAddresses"] = deepcopy(before)
    setup(api, monkeypatch, ["q"] if mode == "cancel" else ["all", "y"])
    if mode == "preview":
        monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    if mode == "stale":
        server.concurrent_edit = True
    args = ["remove-email", "--contact", "c123", "--duplicates"]
    if mode == "apply":
        args += ["--apply"]
    assert cli.main(args) == (1 if mode == "stale" else 0)
    assert server.writes == (1 if mode == "apply" else 0)
    if mode != "stale":
        assert server.person["emailAddresses"] == (
            [before[i] for i in [1, 2, 4, 6]] if mode == "apply" else before
        )


@pytest.mark.parametrize("values", [[], [{"value": "only@example.com"}]])
def test_no_duplicates_no_prompt(api, server, monkeypatch, capsys, values):
    server.person["emailAddresses"] = values
    setup(api, monkeypatch, [])
    assert cli.main(["remove-email", "--contact", "c123", "--duplicates"]) == 0
    assert server.writes == 0
    assert "No duplicate email entries found" in capsys.readouterr().out


@pytest.mark.parametrize("extra", [["--remove", "a@example.com"], ["--remove-file", "absent.txt"]])
def test_duplicate_mode_excludes_other_inputs(monkeypatch, capsys, extra):
    monkeypatch.setattr(
        cli, "connect_with_authorization", lambda *a: pytest.fail("Google accessed")
    )
    with pytest.raises(SystemExit) as exc:
        cli.main(["remove-email", "--contact", "c123", "--duplicates", *extra])
    assert exc.value.code == 2
    assert "--duplicates cannot be combined" in capsys.readouterr().err


@pytest.mark.parametrize("metadata", [None, {"primary": True}, {"sourcePrimary": True}])
def test_single_surplus_keeps_first_or_primary(api, server, monkeypatch, capsys, metadata):
    before = [
        {"value": "a@example.com", "type": "First"},
        {"value": "A@example.com", "type": "Second", "displayName": "Name"},
    ]
    if metadata:
        before[1]["metadata"] = metadata
    server.person["emailAddresses"] = deepcopy(before)
    setup(api, monkeypatch, ["y"])
    assert cli.main(["remove-emails", "--contact", "c123", "--duplicates"]) == 0
    assert server.person["emailAddresses"] == [before[1 if metadata else 0]]
    assert "Remove this email entry? [y/N]" in capsys.readouterr().out


def test_kept_numbers_invalid_and_return_to_selection(api, server, monkeypatch, capsys):
    before = entries()
    server.person["emailAddresses"] = deepcopy(before)
    setup(api, monkeypatch, ["4", "1", "n", "2", "y"])
    assert cli.main(["remove-email", "--contact", "c123", "--duplicates"]) == 0
    assert server.person["emailAddresses"] == before[:3] + before[4:]
    assert "Use only displayed item numbers." in capsys.readouterr().out
