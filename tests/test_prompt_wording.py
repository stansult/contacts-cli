"""Multi-option prompts spell out defaults and the effect of email conflict choices."""

from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.contact_matches import choose_duplicate
from contacts_cli.selection import review_selection
from tests.test_email_selection import setup


@pytest.mark.parametrize("answer", ["", "k", "n"])
def test_keep_email_label_is_explicit(api, server, monkeypatch, capsys, answer):
    before = [{"value": "person@example.com", "type": "HOME"}]
    server.person["emailAddresses"] = deepcopy(before)
    setup(api, monkeypatch, [answer])
    assert cli.main(["add-email", "--contact", "c123", "--add", "person@example.com"]) == 0
    assert server.person["emailAddresses"] == before and server.writes == 0
    out = capsys.readouterr().err
    assert "\n     r   Remove the 'HOME' label\n" in out
    assert "     k   Keep the 'HOME' label" in out.splitlines()
    assert "Choose an option (Enter = keep existing entries): " in out
    assert "[n]:" not in out and "  a " not in out


@pytest.mark.parametrize(
    "value,expected", [("person@example.com", None), ("person@example.com — New", "New")]
)
def test_replace_email_label_uses_r(api, server, monkeypatch, capsys, value, expected):
    server.person["emailAddresses"] = [{"value": "person@example.com", "type": "HOME"}]
    setup(api, monkeypatch, ["r", "y"])
    assert cli.main(["add-email", "--contact", "c123", "--add", value]) == 0
    assert server.person["emailAddresses"][0].get("type") == expected
    assert server.writes == 1


def test_duplicate_consolidation_menu(api, server, monkeypatch, capsys):
    server.person["emailAddresses"] = [
        {"value": "person@example.com"},
        {"value": "PERSON@example.com", "type": "HOME"},
    ]
    setup(api, monkeypatch, ["k"])
    assert cli.main(["add-email", "--contact", "c123", "--add", "person@example.com"]) == 0
    assert server.writes == 0
    out = capsys.readouterr().err
    assert "\n  r   Combine 2 entries into one with no label\n" in out
    assert "  k   Keep all 2 existing entries" in out.splitlines()


def test_duplicate_default_wording(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda: "")
    assert choose_duplicate(allow_merge=True) == "s"
    assert "Choose an option (Enter = skip this input): " in capsys.readouterr().out


def test_selection_default_returns_to_selection(monkeypatch, capsys):
    answers = iter(["all", "", "q"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    assert (
        review_selection(
            [(1, "One"), (2, "Two")],
            noun="items",
            heading="Selected",
            unit=("item", "items"),
            question=lambda count: "Save?",
            action="Save",
        )
        is None
    )
    out = capsys.readouterr().out
    assert "Choose an option (Enter = return to selection): " in out
    assert out.count("Selection: ") == 2


@pytest.mark.parametrize("answer", ["a", "s"])
def test_batch_conflict_options_are_separate(api, server, monkeypatch, capsys, answer):
    server.person["emailAddresses"] = [
        {"value": "a@example.com", "type": "Old"},
        {"value": "b@example.com", "type": "Old"},
    ]
    setup(api, monkeypatch, [answer] + (["all", "y"] if answer == "a" else []))
    assert (
        cli.main(
            ["add-email", "--contact", "c123", "--add", "a@example.com", "--add", "b@example.com"]
        )
        == 0
    )
    assert server.writes == (1 if answer == "a" else 0)
    assert all(
        e.get("type") == (None if answer == "a" else "Old") for e in server.person["emailAddresses"]
    )
    out = capsys.readouterr().err
    assert "\n     r   Remove the 'Old' label\n" in out
    assert "\n\n  a   Use requested labels" in out
    assert "\n  s   Keep existing entries for this and remaining conflicts" in out
    assert out.count("Choose an option (Enter = keep existing entries):") == 1
