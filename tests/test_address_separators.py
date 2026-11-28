"""Keyboard separators work across shared inline and file address inputs."""

import pytest

from contacts_cli.address_inputs import edit_inputs, split_entry
from contacts_cli.cli import file_exclusions


@pytest.mark.parametrize("separator", [" - ", " – ", " — "])
def test_shared_separator_preserves_hyphens_and_label(separator):
    assert split_entry("first-last@sub-domain.example" + separator + "Work - Alerts — Team") == (
        "first-last@sub-domain.example",
        "Work - Alerts — Team",
    )


@pytest.mark.parametrize("option", ["--add", "--remove"])
@pytest.mark.parametrize("file_input", [False, True])
def test_keyboard_separator_all_sources(tmp_path, option, file_input):
    text = "first-last@sub-domain.example - Work - Alerts"
    path = tmp_path / "addresses.txt"
    path.write_text(text + "\n")
    values, paths = ([], [path]) if file_input else ([text], [])
    assert edit_inputs(values, paths, option)[0][:2] == (
        "first-last@sub-domain.example",
        "Work - Alerts",
    )


def test_unspaced_hyphen_is_not_a_separator():
    assert split_entry("first-last@sub-domain.example") == ("first-last@sub-domain.example", "")


def test_keyboard_separator_exclusion_file(tmp_path):
    path = tmp_path / "exclude.txt"
    path.write_text("first-last@sub-domain.example - Work\n*@example.com - Other\n")
    assert file_exclusions([path]) == {"first-last@sub-domain.example", "*@example.com"}
