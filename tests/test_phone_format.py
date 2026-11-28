"""Phone formatting changes presentation without losing numbers or extensions."""

from copy import deepcopy

import pytest

from contacts_cli import cli

from .test_contact_resolution import setup


@pytest.mark.parametrize(
    "apply,answers,selected",
    [
        (False, None, []),
        (False, ["q"], []),
        (False, ["1", "y"], [0]),
        (False, ["all", "y"], [0, 1]),
        (False, ["1", "n", "2", "y"], [1]),
        (True, None, [0, 1]),
    ],
)
def test_format_cli(apply, answers, selected, api, server, monkeypatch, capsys):
    _, _, baseline = setup(api, server, monkeypatch, answers)
    original = [
        {"value": "+12025550142", "type": "work", "metadata": {"primary": True}},
        {"value": "+442079460018 x0042", "type": "mobile"},
        {"value": "5550123", "type": "home"},
    ]
    server.person["phoneNumbers"] = deepcopy(original)
    before = deepcopy(server.person)
    args = ["format-phones", "--contact", "c123"] + (["--apply"] if apply else [])
    assert cli.main(args) == 0
    expected = deepcopy(original)
    targets = ["+1 202-555-0142", "+44 20 7946 0018 ext. 0042"]
    for i in selected:
        expected[i]["value"] = targets[i]
    assert server.person["phoneNumbers"] == expected
    assert server.writes == baseline + bool(selected)
    for field in before.keys() - {"phoneNumbers", "metadata"}:
        assert server.person[field] == before[field]
    output = capsys.readouterr().out
    assert "5550123" in output and "country" in output
    if selected:
        assert "Formatted and verified" in output


def test_format_help(capsys):
    with pytest.raises(SystemExit) as result:
        cli.main(["format-phone", "--help"])
    assert result.value.code == 0
    output = capsys.readouterr().out
    assert "--apply" in output and "extension" in output


@pytest.mark.parametrize(
    "entry,expected",
    [
        ({"value": "+12025550142"}, "+1 202-555-0142"),
        ({"value": "+442079460018"}, "+44 20 7946 0018"),
        ({"value": "+41446681800"}, "+41 44 668 18 00"),
        ({"value": "+39066982"}, "+39 06 6982"),
        ({"value": "+81312345678"}, "+81 3-1234-5678"),
        (
            {"value": "(202) 555-0142 x0042", "canonicalForm": "+12025550142"},
            "+1 202-555-0142 ext. 0042",
        ),
        ({"value": "+12025550142;ext=42"}, "+1 202-555-0142 ext. 42"),
        ({"value": "+1 202-555-0142 ext. 42"}, "+1 202-555-0142 ext. 42"),
        ({"value": "+12025550142", "canonicalForm": "+12025550142 x42"}, "+1 202-555-0142 ext. 42"),
    ],
)
def test_international_formats(entry, expected):
    from contacts_cli.phone_format import formatted_phone

    before = deepcopy(entry)
    assert formatted_phone(entry) == (expected, None)
    assert entry == before


@pytest.mark.parametrize(
    "entry,reason",
    [
        ({"value": "2025550142"}, "country code"),
        ({"value": "0012025550142"}, "country code"),
        ({"value": "+12025550142,42"}, "unsupported"),
        ({"value": "+1-800-FLOWERS"}, "unsupported"),
        ({"value": "+123"}, "length"),
        ({"value": "+999123456789"}, "unrecognized"),
        ({"value": "+12025550142", "canonicalForm": "+442079460018"}, "disagree"),
        ({"value": "+12025550142 x42", "canonicalForm": "+12025550142 x43"}, "extensions"),
        ({"value": "+12025550142", "canonicalForm": "nonsense"}, "canonical"),
        ({"value": "+44 (0)20 7946 0018"}, "digits"),
    ],
)
def test_ambiguous_numbers_are_skipped(entry, reason):
    from contacts_cli.phone_format import formatted_phone

    value, message = formatted_phone(entry)
    assert value is None and reason in message


def test_formatter_library_contract():
    import phonenumbers as p

    number = p.parse("+39066982", None)
    assert p.is_possible_number(number)
    assert p.format_number(number, p.PhoneNumberFormat.E164) == "+39066982"
    assert p.format_number(number, p.PhoneNumberFormat.INTERNATIONAL) == "+39 06 6982"
    assert not p.is_possible_number(p.parse("+123", None))
    with pytest.raises(p.NumberParseException):
        p.parse("2025550142", None)


@pytest.mark.parametrize(
    "values", [[], ["+1 202-555-0142"], ["5550123"], ["+1 202-555-0142", "5550123"]]
)
def test_no_changes(values, api, server, monkeypatch, capsys):
    _, _, baseline = setup(api, server, monkeypatch)
    server.person["phoneNumbers"] = [{"value": v} for v in values]
    assert cli.main(["format-phone", "--contact", "c123", "--apply"]) == 0
    assert server.writes == baseline
    assert "No phone formatting changes needed" in capsys.readouterr().out


@pytest.mark.parametrize("answer,write", [("y", True), ("n", False)])
def test_single_change_and_stable_numbers(answer, write, api, server, monkeypatch, capsys):
    _, _, baseline = setup(api, server, monkeypatch, [answer])
    server.person["phoneNumbers"] = [{"value": "5550123"}, {"value": "+12025550142"}]
    assert cli.main(["format-phone", "--contact", "c123"]) == 0
    assert server.writes == baseline + write
    output = capsys.readouterr().out
    assert "2. +12025550142" in output and "1. 5550123" in output


def test_format_does_not_deduplicate(api, server, monkeypatch):
    _, _, baseline = setup(api, server, monkeypatch)
    server.person["phoneNumbers"] = [
        {"value": "+12025550142", "type": "home"},
        {"value": "+1 (202) 555-0142", "type": "work"},
    ]
    assert cli.main(["format-phone", "--contact", "c123", "--apply"]) == 0
    assert server.person["phoneNumbers"] == [
        {"value": "+1 202-555-0142", "type": "home"},
        {"value": "+1 202-555-0142", "type": "work"},
    ]
    assert server.writes == baseline + 1
    assert cli.main(["format-phone", "--contact", "c123", "--apply"]) == 0
    assert server.writes == baseline + 1


def test_concurrent_phone_change(api, server, monkeypatch):
    _, _, baseline = setup(api, server, monkeypatch)
    server.person["phoneNumbers"] = [{"value": "+12025550142"}]

    def confirm(*a):
        server.person["phoneNumbers"][0]["type"] = "changed"
        return True

    monkeypatch.setattr(cli, "confirm_apply", confirm)
    assert cli.main(["format-phone", "--contact", "c123"]) == 1
    assert server.writes == baseline


@pytest.mark.parametrize("stage", ["write", "readback"])
def test_verification_failure(stage, api, server, monkeypatch, capsys):
    _, _, baseline = setup(api, server, monkeypatch)
    server.person["phoneNumbers"] = [{"value": "+12025550142 x0042"}]
    if stage == "write":
        original = api.write

        def write(*a, **kw):
            result = original(*a, **kw)
            result["phoneNumbers"][0]["value"] = "+1 202-555-0142"
            return result

        monkeypatch.setattr(api, "write", write)
    else:
        original = api.get_contact
        calls = 0

        def read(*a, **kw):
            nonlocal calls
            calls += 1
            result = original(*a, **kw)
            if calls == 3:
                result["phoneNumbers"][0]["value"] = "+1 202-555-0142"
            return result

        monkeypatch.setattr(api, "get_contact", read)
    assert cli.main(["format-phone", "--contact", "c123", "--apply"]) == 3
    assert server.writes == baseline + 1
    assert "Formatted and verified" not in capsys.readouterr().out
