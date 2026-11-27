"""Help stays a quick usage guide and points to the detailed behavior contract."""

import re
from pathlib import Path

import pytest

from contacts_cli import cli

COMMAND_SECTIONS = {
    "list-contact": "List-contact",
    "add-contact": "Add-contact",
    "duplicate": "Duplicate a contact",
    "sender-sync": "Sender-sync preview and apply",
    "list-email": "List-email",
    "add-email": "Add-email and remove-email",
    "remove-email": "Add-email and remove-email",
    "list-label": "List-label",
    "add-label": "Add-label",
    "remove-label": "Remove-label",
    "add-custom-field": "Add-custom-field and remove-custom-field",
    "remove-custom-field": "Add-custom-field and remove-custom-field",
    "validate-contact": "Validate-contact",
    "authorize": "Authorization",
}


@pytest.mark.parametrize("command,section", COMMAND_SECTIONS.items())
def test_command_help_links_to_existing_reference_section(command, section, capsys):
    with pytest.raises(SystemExit) as result:
        cli.main([command, "--help"])
    assert result.value.code == 0
    text = capsys.readouterr().out
    anchor = section.lower().replace(" ", "-")
    assert (
        f"https://github.com/stansult/contacts-cli/blob/main/docs/command-reference.md#{anchor}"
        in text
    )
    reference = Path("docs/command-reference.md").read_text()
    assert f"## {section}\n" in reference
    assert "contacts-cli --help" in text
    assert "options:" in text


def test_import_help_is_usage_summary(capsys):
    with pytest.raises(SystemExit):
        cli.main(["add-contact", "--help"])
    text = " ".join(capsys.readouterr().out.split())
    assert "Create contacts from inline fields or a JSON file." in text
    assert "skip, merge, or create separately" in text
    assert "duplicate and label choices still prompt" in text
    assert "Grouped email-label review" not in text
    assert "unrecovered quota" not in text


def test_documentation_url_stays_copyable_in_narrow_terminal(monkeypatch, capsys):
    monkeypatch.setenv("COLUMNS", "60")
    with pytest.raises(SystemExit):
        cli.main(["add-contact", "--help"])
    text = capsys.readouterr().out
    urls = re.findall(r"https://\S+", text)
    assert urls == [
        "https://github.com/stansult/contacts-cli/blob/main/docs/command-reference.md#add-contact"
    ]
