"""Conflict descriptions isolate differing properties from entry identity/context."""

from contacts_cli.contact_merge import merge_values
from contacts_cli.merge_conflicts import choose_conflict


def conflict(field, old, new):
    details = []
    merge_values({field: [old]}, {field: [new]}, details=details)
    assert len(details) == 1
    return details[0]


def test_email_label_display_omits_case_and_unsupplied_display_name(monkeypatch, capsys):
    item = conflict(
        "emailAddresses",
        {"value": "chris@example.com", "type": "work", "displayName": "chris@example.com"},
        {"value": "Chris@Example.COM", "type": "Event"},
    )
    text = item.describe()
    assert "Email: chris@example.com" in text
    assert "Label differs:" in text
    assert "Saved:    work" in text and "Incoming: Event" in text
    assert "Display name" not in text and "Chris@Example.COM" not in text
    monkeypatch.setattr("builtins.input", lambda: "r")
    assert choose_conflict(item) == "r"
    output = capsys.readouterr().out
    assert "Keep saved label" in output and "Use incoming label" in output
    assert "Keep both labels as two email entries" in output


def test_company_multiple_conflicts_only_show_differing_properties():
    item = conflict(
        "organizations",
        {"name": "Example", "title": "Engineer", "department": "Tools", "location": "Irvine"},
        {"name": "EXAMPLE", "title": "Senior Engineer", "department": "Tools", "location": "LA"},
    )
    text = item.describe()
    assert text.count("Company: Example") == 1
    assert "Title differs:" in text and "Location differs:" in text
    assert "Department" not in text and "Tools" not in text and "EXAMPLE" not in text


def test_supplied_display_name_conflict_is_not_hidden():
    item = conflict(
        "emailAddresses",
        {"value": "a@example.com", "displayName": "Old"},
        {"value": "A@example.com", "displayName": "New"},
    )
    assert "Display name differs:" in item.describe()
    assert "Saved:    Old" in item.describe() and "Incoming: New" in item.describe()


def test_multiple_saved_entries_keep_replacement_numbers(monkeypatch, capsys):
    from contacts_cli.merge_conflicts import Conflict

    item = Conflict(
        "emailAddresses",
        [1, 3],
        [{"value": "a@example.com", "type": "work"}, {"value": "A@example.com", "type": "home"}],
        {"value": "a@example.com", "type": "Event"},
        [],
    )
    answers = iter(["r", "2"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    assert choose_conflict(item) == ("r", 1)
    text = capsys.readouterr().out
    assert "Saved entry #1:" in text and "Saved entry #2:" in text
    assert "Saved:    work" in text and "Saved:    home" in text
    assert text.count("Email: a@example.com") == 1
    assert "as two email entries" not in text
    assert "add an email entry" in text
    assert "A@example.com" not in text


def test_singleton_display_explains_removed_unsupplied_properties():
    item = conflict(
        "names",
        {"givenName": "Old", "familyName": "Person"},
        {"unstructuredName": "New Different Person"},
    )
    text = item.describe()
    assert "Full name differs:" in text and "First name differs:" in text
    assert "(not supplied; removed by Replace)" in text
    assert "Replace uses the complete incoming entry." in text
    assert not item.both


def test_nested_date_changes_have_property_names():
    item = conflict(
        "birthdays",
        {"date": {"year": 1990, "month": 1, "day": 2}},
        {"date": {"year": 1991, "month": 1, "day": 2}},
    )
    text = item.describe()
    assert "Date / Year differs:" in text
    assert "Month" not in text and "Day" not in text


def test_multi_property_email_uses_values_choices(monkeypatch, capsys):
    item = conflict(
        "emailAddresses",
        {"value": "a@example.com", "type": "work", "displayName": "Old"},
        {"value": "A@example.com", "type": "home", "displayName": "New"},
    )
    monkeypatch.setattr("builtins.input", lambda: "k")
    assert choose_conflict(item) == "k"
    text = capsys.readouterr().out
    assert "Label differs:" in text and "Display name differs:" in text
    assert "Keep saved values" in text and "Use incoming values" in text
    assert "Keep both as separate email entries" in text
