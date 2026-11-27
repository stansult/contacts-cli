"""Range bounds filter displayed numbers without expanding the numeric span."""

import pytest

from contacts_cli import cli
from contacts_cli.selection import parse_selection, select_numbers


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("1-19", [18, 19]),
        ("37-100", [37, 39, 50, 59, 63]),
        ("59-64", [59, 63]),
        ("59-63", [59, 63]),
        ("60-62,18", [18]),
        ("18-18", [18]),
        ("1-100,18,37-100", [18, 19, 37, 39, 50, 59, 63]),
        ("0-999999999999999999999999999999", [18, 19, 37, 39, 50, 59, 63]),
    ],
)
def test_ranges_select_displayed_items(answer, expected):
    assert parse_selection(answer, [18, 19, 37, 39, 50, 59, 63]) == expected


@pytest.mark.parametrize(
    "answer", ["64", "18,64", "1-100,64", "19-1", "60-62", "1-17", "1-", "1--19"]
)
def test_invalid_explicit_numbers_and_empty_or_reversed_ranges(answer):
    with pytest.raises(ValueError):
        parse_selection(answer, [18, 19, 37, 39, 50, 59, 63])


def test_range_preserves_display_order_and_deduplicates():
    assert parse_selection("1-100,18-63", [63, 18, 50]) == [63, 18, 50]


def test_empty_range_reprompts(monkeypatch, capsys):
    answers = iter(["60-62", "59-100"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    assert select_numbers([18, 59, 63]) == [59, 63]
    assert "No displayed items fall within this selection." in capsys.readouterr().out


def test_top_level_help_points_to_selection_reference(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    text = " ".join(capsys.readouterr().out.split())
    assert "docs/command-reference.md" in text
