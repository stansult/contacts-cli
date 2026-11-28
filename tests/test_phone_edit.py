"""Phone duplicate cleanup preserves individual occurrences and unrelated fields."""

from copy import deepcopy

import pytest

from contacts_cli import cli

from .test_contact_resolution import setup


def phones():
    return [
        {"value": "(202) 555-0142", "canonicalForm": "+12025550142", "type": "work"},
        {"value": "+1 202-555-0142", "type": "mobile", "metadata": {"primary": True}},
        {"value": "+12025550142", "type": "other"},
        {"value": "+12025550142 ext. 42", "type": "work"},
        {"value": "555-9999"},
    ]


@pytest.mark.parametrize("command", ["list-phone", "list-phones"])
def test_listing(command, api, server, monkeypatch, capsys):
    _, _, baseline = setup(api, server, monkeypatch)
    server.person["phoneNumbers"] = phones()
    before = deepcopy(server.person)
    assert cli.main([command, "--contact", "c123"]) == 0
    output = capsys.readouterr().out
    assert "Phone numbers: 5 entries" in output
    assert "[duplicate of #1]" in output and "(primary)" in output
    assert server.writes == baseline and server.person == before


@pytest.mark.parametrize(
    "apply,answers,removed",
    [
        (False, None, []),
        (False, ["q"], []),
        (False, ["1", "y"], [0]),
        (False, ["all", "y"], [0, 2]),
        (False, ["1", "n", "2", "y"], [2]),
        (True, None, [0, 2]),
    ],
)
def test_removal(apply, answers, removed, api, server, monkeypatch, capsys):
    _, _, baseline = setup(api, server, monkeypatch, answers)
    server.person["phoneNumbers"] = phones()
    before = deepcopy(server.person)
    args = ["remove-phone", "--contact", "c123", "--duplicates"] + (["--apply"] if apply else [])
    assert cli.main(args) == 0
    assert server.person["phoneNumbers"] == [
        p for i, p in enumerate(before["phoneNumbers"]) if i not in removed
    ]
    assert server.writes == baseline + bool(removed)
    for field in before.keys() - {"phoneNumbers", "metadata"}:
        assert server.person[field] == before[field]
    if removed:
        assert "Removed and verified" in capsys.readouterr().out


def test_missing_duplicates_flag():
    with pytest.raises(SystemExit) as exc:
        cli.main(["remove-phone", "--contact", "c123"])
    assert exc.value.code == 2


@pytest.mark.parametrize(
    "left,right,equal",
    [
        ({"value": "+1 (202) 555-0142"}, {"value": "12025550142"}, True),
        ({"value": "2025550142"}, {"value": "+12025550142"}, False),
        ({"value": "2025550142", "canonicalForm": "+12025550142"}, {"value": "+12025550142"}, True),
        ({"value": "+12025550142 x42"}, {"value": "+1 202 555 0142 ext. 42"}, True),
        (
            {"value": "2025550142 x42", "canonicalForm": "+12025550142"},
            {"value": "+12025550142"},
            False,
        ),
        ({"value": "+12025550142 x42"}, {"value": "+12025550142 x43"}, False),
        ({"value": "CALL-ME"}, {"value": "CALL-ME"}, False),
        ({"value": "123 x42", "canonicalForm": "+123 x43"}, {"value": "+123 x43"}, False),
    ],
)
def test_identity(left, right, equal):
    from contacts_cli.phone_edit import duplicate_phones

    removed, _ = duplicate_phones([left, right])
    assert bool(removed) == equal


@pytest.mark.parametrize("value", [[], [{"value": "123"}], [{"value": "bad"}, {"value": "bad"}]])
def test_no_duplicates(value, api, server, monkeypatch, capsys):
    _, _, baseline = setup(api, server, monkeypatch)
    server.person["phoneNumbers"] = value
    assert cli.main(["remove-phones", "--contact", "c123", "--duplicates", "--apply"]) == 0
    assert "No duplicate phone entries" in capsys.readouterr().out
    assert server.writes == baseline


@pytest.mark.parametrize("answer,write", [("y", True), ("n", False)])
def test_single_extra(answer, write, api, server, monkeypatch):
    _, _, baseline = setup(api, server, monkeypatch, [answer])
    server.person["phoneNumbers"] = [{"value": "123"}, {"value": "123", "type": "work"}]
    assert cli.main(["remove-phone", "--contact", "c123", "--duplicates"]) == 0
    assert server.writes == baseline + write
    assert len(server.person["phoneNumbers"]) == (1 if write else 2)


@pytest.mark.parametrize("damage", ["value", "type", "primary", "other", "count", "source"])
def test_verification_damage(damage, api, server, monkeypatch, capsys):
    _, _, baseline = setup(api, server, monkeypatch)
    server.person["phoneNumbers"] = phones()
    original_write = api.write

    def write(*a, **kw):
        saved = original_write(*a, **kw)
        if damage == "primary":
            saved["phoneNumbers"][0].pop("metadata", None)
        elif damage in ("value", "type"):
            saved["phoneNumbers"][0][damage] = "changed"
        elif damage == "other":
            saved["emailAddresses"] = []
        elif damage == "count":
            saved["phoneNumbers"].append(deepcopy(saved["phoneNumbers"][0]))
        else:
            saved["metadata"]["sources"][0]["id"] = "wrong"
        return saved

    monkeypatch.setattr(api, "write", write)
    assert cli.main(["remove-phone", "--contact", "c123", "--duplicates", "--apply"]) == 3
    assert server.writes == baseline + 1
    assert "Removed and verified" not in capsys.readouterr().out


def test_changed_since_preview(api, server, monkeypatch):
    _, _, baseline = setup(api, server, monkeypatch)
    server.person["phoneNumbers"] = phones()[:2]

    def confirm(*a):
        server.person["metadata"]["sources"][0]["etag"] = "changed"
        return True

    monkeypatch.setattr(cli, "confirm_apply", confirm)
    assert cli.main(["remove-phone", "--contact", "c123", "--duplicates"]) == 1
    assert server.writes == baseline


def test_independent_readback_failure(api, server, monkeypatch):
    _, _, baseline = setup(api, server, monkeypatch)
    server.person["phoneNumbers"] = phones()
    read = api.get_contact
    calls = 0

    def get(*a, **kw):
        nonlocal calls
        calls += 1
        saved = read(*a, **kw)
        if calls == 3:
            saved["phoneNumbers"] = []
        return saved

    monkeypatch.setattr(api, "get_contact", get)
    assert cli.main(["remove-phone", "--contact", "c123", "--duplicates", "--apply"]) == 3
    assert calls == 3 and server.writes == baseline + 1


def test_phone_fixture_contract(server):
    from .test_fixture_contract import fetch

    original = deepcopy(server.person)
    retained = [{"value": "+12025550142", "type": "work"}]
    body = {"metadata": {"sources": original["metadata"]["sources"]}, "phoneNumbers": retained}
    assert (
        fetch(
            server, "/v1/people/c123:updateContact?updatePersonFields=phoneNumbers", "PATCH", body
        )[0]
        == 200
    )
    assert server.person["phoneNumbers"] == retained
    for field in original.keys() - {"phoneNumbers", "metadata"}:
        assert server.person[field] == original[field]
    # The stale snapshot must be rejected on a second request.
    assert (
        fetch(
            server, "/v1/people/c123:updateContact?updatePersonFields=phoneNumbers", "PATCH", body
        )[0]
        == 400
    )


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [{"value": 123}],
        [{"value": "123", "canonicalForm": []}],
        [{"value": "123", "metadata": {"source": {"type": "PROFILE", "id": "other"}}}],
    ],
)
def test_invalid_phone_data_blocks_writes(bad, api, server, monkeypatch):
    _, _, baseline = setup(api, server, monkeypatch)
    server.person["phoneNumbers"] = bad
    assert cli.main(["remove-phone", "--contact", "c123", "--duplicates", "--apply"]) == 1
    assert server.writes == baseline


def test_kept_entry_not_selectable(api, server, monkeypatch, capsys):
    _, _, baseline = setup(api, server, monkeypatch, ["3", "q"])
    server.person["phoneNumbers"] = phones()
    assert cli.main(["remove-phone", "--contact", "c123", "--duplicates"]) == 0
    assert "Use only displayed item numbers" in capsys.readouterr().out
    assert server.writes == baseline


def test_generated_phone_metadata_is_allowed(api, server, monkeypatch):
    from contacts_cli.phone_edit import verify_phones

    setup(api, server, monkeypatch)
    person = deepcopy(server.person)
    expected = [{"value": "+12025550142", "type": "work"}]
    saved = deepcopy(person)
    saved["phoneNumbers"] = [
        dict(
            expected[0],
            canonicalForm="+12025550142",
            formattedType="Work",
            metadata={"primary": True},
        )
    ]
    verify_phones(person, expected, saved)


def test_help_documents_duplicates(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["remove-phone", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "--duplicates" in output and "--apply" in output
    assert "extensions stay separate" in output
    assert "primary or first entry" in output
