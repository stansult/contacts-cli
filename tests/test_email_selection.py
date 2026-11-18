"""Select whole address changes without losing skipped entries or duplicate metadata."""

from copy import deepcopy

import pytest

from contacts_cli import cli


def setup(api, monkeypatch, answers):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (cli.sys.stdin, cli.sys.stdout, cli.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    replies = iter(answers)
    monkeypatch.setattr("builtins.input", lambda: next(replies))


@pytest.mark.parametrize("selection", ["1", "2"])
def test_mixed_addition_and_update(api, server, monkeypatch, capsys, selection):
    server.person["emailAddresses"] = [{"value": "old@example.com", "type": "Old"}]
    setup(api, monkeypatch, ["y", selection, "y"])
    assert (
        cli.main(
            [
                "add-email",
                "--contact",
                "c123",
                "--add",
                "old@example.com — New",
                "--add",
                "new@example.com",
            ]
        )
        == 0
    )
    assert server.person["emailAddresses"] == (
        [{"value": "old@example.com", "type": "Old"}, {"value": "new@example.com"}]
        if selection == "1"
        else [{"value": "old@example.com", "type": "New"}]
    )
    output = capsys.readouterr().out
    assert "2. old@example.com:" in output


def test_grouped_removals_and_reselection(api, server, monkeypatch, capsys):
    server.person["emailAddresses"] = [
        {"value": "a@example.com", "type": "work", "metadata": {"sourcePrimary": True}},
        {"value": "A@example.com"},
        {"value": "b@example.com"},
        {"value": "B@example.com"},
    ]
    before = deepcopy(server.person["emailAddresses"])
    setup(api, monkeypatch, ["1", "n", "2", "y"])
    assert (
        cli.main(
            [
                "remove-email",
                "--contact",
                "c123",
                "--remove",
                "a@example.com",
                "--remove",
                "A@example.com",
                "--remove",
                "b@example.com",
            ]
        )
        == 0
    )
    assert server.person["emailAddresses"] == before[:2]
    output = capsys.readouterr().out
    assert "a@example.com — work (primary)" in output
    assert "A@example.com — (no label)" in output
    assert "B@example.com — (no label)" in output
    assert "Selected removals: 2 entries (1 address)" in output
    assert "2. b@example.com — 2 entries" in output


def test_single_group_removes_all_with_count(api, server, monkeypatch, capsys):
    server.person["emailAddresses"] = [{"value": "a@example.com"}, {"value": "A@example.com"}]
    setup(api, monkeypatch, ["y"])
    assert cli.main(["remove-email", "--contact", "c123", "--remove", "a@example.com"]) == 0
    output = capsys.readouterr().out
    assert "Remove these 2 email entries? [y/N]" in output
    assert "Remaining email entries: 0" in output
    assert server.person["emailAddresses"] == []


@pytest.mark.parametrize("select", ["1", "2"])
def test_consolidation_preserves_primary_or_all_unselected_duplicates(
    api, server, monkeypatch, select
):
    server.person["emailAddresses"] = [
        {"value": "a@example.com"},
        {"value": "A@example.com", "metadata": {"sourcePrimary": True}},
    ]
    before = deepcopy(server.person["emailAddresses"])
    setup(api, monkeypatch, ["y", select, "n", select, "y"])
    assert (
        cli.main(
            [
                "add-email",
                "--contact",
                "c123",
                "--add",
                "a@example.com — Work",
                "--add",
                "new@example.com",
            ]
        )
        == 0
    )
    assert server.person["emailAddresses"] == (
        before + [{"value": "new@example.com"}]
        if select == "1"
        else [{"value": "A@example.com", "metadata": {"sourcePrimary": True}, "type": "Work"}]
    )


def test_informational_numbers_rejected(api, server, monkeypatch, capsys):
    server.person["emailAddresses"] = [{"value": "a@example.com"}, {"value": "b@example.com"}]
    setup(api, monkeypatch, ["3", "1", "y"])
    assert (
        cli.main(
            [
                "remove-email",
                "--contact",
                "c123",
                "--remove",
                "a@example.com",
                "--remove",
                "b@example.com",
                "--remove",
                "missing@example.com",
            ]
        )
        == 0
    )
    assert server.person["emailAddresses"] == [{"value": "b@example.com"}]
    output = capsys.readouterr().out
    assert "3. missing@example.com" in output
    assert "Use only displayed item numbers." in output


@pytest.mark.parametrize("action", ["add", "remove"])
def test_selected_stale_preview_stops_without_write(api, server, monkeypatch, action):
    server.person["emailAddresses"] = [{"value": "a@example.com"}, {"value": "b@example.com"}]
    before = deepcopy(server.person["emailAddresses"])
    server.concurrent_edit = True
    setup(api, monkeypatch, ["1", "y"])
    values = (
        ["new@example.com", "other@example.com"]
        if action == "add"
        else ["a@example.com", "b@example.com"]
    )
    assert (
        cli.main(
            [
                f"{action}-email",
                "--contact",
                "c123",
                f"--{action}",
                values[0],
                f"--{action}",
                values[1],
            ]
        )
        == 1
    )
    assert server.writes == 0
    assert server.person["emailAddresses"] == before + [{"value": "concurrent@example.com"}]


def test_valid_subset_of_oversized_addition(api, server, monkeypatch):
    # Establish the guard using the real validator, rather than a mocked size limit.
    from contacts_cli.core import email_update_body
    from contacts_cli.errors import SyncError

    server.person["emailAddresses"] = [{"value": f"p{i}@example.com"} for i in range(496)]
    while True:
        try:
            email_update_body(
                server.person, server.person["emailAddresses"] + [{"value": "new@example.com"}]
            )
            break
        except SyncError:
            server.person["emailAddresses"].pop()
    before = deepcopy(server.person["emailAddresses"])
    additions = [{"value": f"new{i}@example.com"} for i in range(10)]
    with pytest.raises(SyncError, match="size guard"):
        email_update_body(server.person, before + additions)
    setup(api, monkeypatch, ["1", "y"])
    argv = ["add-email", "--contact", "c123"]
    for entry in additions:
        argv += ["--add", entry["value"]]
    assert cli.main(argv) == 0
    assert server.person["emailAddresses"] == before + additions[:1]


@pytest.mark.parametrize("action,answers", [("add", ["q"]), ("remove", ["1", "q"])])
def test_selection_cancel_preserves_everything(api, server, monkeypatch, action, answers):
    server.person["emailAddresses"] = [{"value": "a@example.com"}, {"value": "b@example.com"}]
    before = deepcopy(server.person)
    setup(api, monkeypatch, answers)
    values = (
        ["new@example.com", "other@example.com"]
        if action == "add"
        else ["a@example.com", "b@example.com"]
    )
    assert (
        cli.main(
            [
                f"{action}-email",
                "--contact",
                "c123",
                f"--{action}",
                values[0],
                f"--{action}",
                values[1],
            ]
        )
        == 0
    )
    assert server.person == before and server.writes == 0


def test_skipped_conflict_cannot_be_selected(api, server, monkeypatch, capsys):
    server.person["emailAddresses"] = [{"value": "old@example.com", "type": "Old"}]
    setup(api, monkeypatch, ["n", "3", "1", "y"])
    assert (
        cli.main(
            [
                "add-email",
                "--contact",
                "c123",
                "--add",
                "old@example.com — New",
                "--add",
                "new@example.com",
                "--add",
                "other@example.com",
            ]
        )
        == 0
    )
    assert server.person["emailAddresses"] == [
        {"value": "old@example.com", "type": "Old"},
        {"value": "new@example.com"},
    ]
    assert "Use only displayed item numbers." in capsys.readouterr().out
