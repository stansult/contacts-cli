"""Existing-email decisions are separate from new additions."""

from copy import deepcopy

import pytest

from contacts_cli import cli
from tests.test_email_selection import setup


@pytest.mark.parametrize("decision", ["k", ""])
@pytest.mark.parametrize("confirm", ["y", "n"])
def test_one_existing_decision_with_new_address(
    api, server, monkeypatch, capsys, decision, confirm
):
    before = [{"value": "saved@example.com", "type": "test"}]
    server.person["emailAddresses"] = deepcopy(before)
    setup(api, monkeypatch, [decision, confirm])
    assert (
        cli.main(
            [
                "add-email",
                "--contact",
                "c123",
                "--add",
                "saved@example.com",
                "--add",
                "new@example.com",
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    assert "  a   " not in output.err and "  s   " not in output.err
    assert "You supplied no label." in output.err
    assert "Unchanged: 1 entry\n  saved@example.com — test\n" in output.out
    assert "Skipped conflicts" not in output.out and "requested label:" not in output.out
    assert "Add new@example.com to this contact? [y/N]" in output.out
    assert server.person["emailAddresses"] == (
        before + [{"value": "new@example.com"}] if confirm == "y" else before
    )
    assert server.writes == (1 if confirm == "y" else 0)
    assert output.out.index("Unchanged:") < output.out.index("Proposed additions:")


def test_batch_choices_only_when_more_decisions_remain(api, server, monkeypatch, capsys):
    server.person["emailAddresses"] = [
        {"value": "a@example.com", "type": "Old"},
        {"value": "b@example.com", "type": "Old"},
        {"value": "c@example.com", "type": "Same"},
    ]
    setup(api, monkeypatch, ["k", "k", "n"])
    assert (
        cli.main(
            [
                "add-email",
                "--contact",
                "c123",
                "--add",
                "a@example.com",
                "--add",
                "b@example.com",
                "--add",
                "c@example.com - Same",
                "--add",
                "new@example.com",
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    assert output.err.count("  a   ") == 1
    assert output.err.count("  s   ") == 1
    assert "Unchanged: 2 entries" in output.out
    assert server.writes == 0
