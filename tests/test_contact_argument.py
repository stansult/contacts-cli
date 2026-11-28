"""Single-contact commands never silently discard an earlier target."""

import pytest

from contacts_cli import cli

SINGLE = [
    ("duplicate", []),
    ("sender-sync", ["--search", "from:example.com"]),
    ("add-email", ["--add", "new@example.com"]),
    ("remove-email", ["--duplicates"]),
    ("remove-phone", ["--duplicates"]),
    ("remove-label", ["--label", "Test"]),
    ("add-custom-field", ["--field", "Status", "Active"]),
    ("remove-custom-field", ["--key", "Status"]),
]


@pytest.mark.parametrize("command,options", SINGLE)
@pytest.mark.parametrize("second", ["c456", "c123"])
def test_repeated_target_rejected_before_auth(command, options, second, monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("authorization"))
    with pytest.raises(SystemExit) as error:
        cli.main([command, "--contact", "c123", f"--contact={second}", *options])
    assert error.value.code == 2
    assert "--contact can only be supplied once for this command" in capsys.readouterr().err


@pytest.mark.parametrize("command,options", SINGLE)
def test_single_target_still_parses(command, options):
    assert cli.parser().parse_args([command, "--contact", "c123", *options]).contact == "c123"


@pytest.mark.parametrize(
    "command,options",
    [
        ("list-email", []),
        ("list-phone", []),
        ("list-label", []),
        ("format-phone", []),
        ("add-label", ["--label", "Test"]),
    ],
)
def test_batch_targets_remain_repeatable(command, options):
    assert cli.parser().parse_args(
        [command, "--contact", "c123", "--contact", "c456", *options]
    ).contact == ["c123", "c456"]


def test_main_help_uses_plural_label_contacts(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "List account labels with contact counts, or labels on selected contacts" in out
    assert "Create labels or add them to contacts" in out
