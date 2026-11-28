"""Email updates state their effect once, with specific single-change confirmation."""

from copy import deepcopy

import pytest

from contacts_cli import cli
from tests.test_email_selection import setup


@pytest.mark.parametrize(
    "before,value,detail,question",
    [
        (
            [{"value": "a@example.com", "type": "Work"}],
            "a@example.com",
            "Remove label: Work",
            "Remove the 'Work' label from a@example.com?",
        ),
        (
            [{"value": "a@example.com", "type": "Work"}],
            "a@example.com - Personal",
            "Change label: Work → Personal",
            "Change the label on a@example.com from 'Work' to 'Personal'?",
        ),
        (
            [{"value": "a@example.com"}],
            "a@example.com - Work",
            "Add label: Work",
            "Add the 'Work' label to a@example.com?",
        ),
        (
            [{"value": "a@example.com", "type": "Old"}, {"value": "A@example.com"}],
            "a@example.com - Work",
            "Combine 2 entries into one\n     Resulting label: Work",
            "Combine 2 entries for a@example.com into one labeled 'Work'?",
        ),
        (
            [{"value": "a@example.com"}, {"value": "a@example.com"}],
            "a@example.com",
            "Combine 2 entries into one\n     Resulting label: none",
            "Combine 2 entries for a@example.com into one with no label?",
        ),
    ],
)
def test_single_update_detail_and_confirmation(
    api, server, monkeypatch, capsys, before, value, detail, question
):
    server.person["emailAddresses"] = deepcopy(before)
    setup(api, monkeypatch, ["n"])
    assert cli.main(["add-email", "--contact", "c123", "--add", value, "--replace-existing"]) == 0
    output = capsys.readouterr().out
    assert "  1. a@example.com\n     " + detail in output
    assert question + " [y/N]" in output
    assert "Proposed additions: 0" not in output and "entry(s)" not in output
    assert server.person["emailAddresses"] == before and server.writes == 0
    if detail.startswith("Remove"):
        assert "Proposed label removal: 1 email" in output


def test_update_selected_from_mixed_changes(api, server, monkeypatch, capsys):
    server.person["emailAddresses"] = [{"value": "old@example.com", "type": "Work"}]
    setup(api, monkeypatch, ["2", "y"])
    assert (
        cli.main(
            [
                "add-email",
                "--contact",
                "c123",
                "--add",
                "old@example.com",
                "--add",
                "new@example.com",
                "--replace-existing",
            ]
        )
        == 0
    )
    assert server.person["emailAddresses"] == [{"value": "old@example.com"}]
    assert server.writes == 1
    output = capsys.readouterr().out
    assert "Remove the 'Work' label from old@example.com?" in output
    assert "  2. old@example.com\n     Remove label: Work" in output


def test_apply_label_removal_heading(api, server, monkeypatch, capsys):
    server.person["emailAddresses"] = [{"value": "a@example.com", "type": "Work"}]
    setup(api, monkeypatch, [])
    assert (
        cli.main(
            [
                "add-email",
                "--contact",
                "c123",
                "--add",
                "a@example.com",
                "--replace-existing",
                "--apply",
            ]
        )
        == 0
    )
    assert server.person["emailAddresses"] == [{"value": "a@example.com"}]
    output = capsys.readouterr().out
    assert "Removing labels: 1 email" in output
    assert "Proposed" not in output and "Adding: 0" not in output
    assert server.writes == 1
