"""Custom fields use exact selectors and preserve unrelated contact data."""

from copy import deepcopy

import pytest

from contacts_cli import cli

from .test_fixture_contract import fetch

ENTRIES = [
    {"key": "Pipeline ID", "value": "P-001"},
    {"key": "Pipeline ID", "value": "P-002"},
    {"key": "Pipeline ID", "value": "P-001"},
    {"key": "Created", "value": "Example timestamp"},
]


def test_custom_field_fixture_contract(server):
    server.person["userDefined"] = deepcopy(ENTRIES)
    original = deepcopy(server.person)
    path = "/v1/people/c123:updateContact?updatePersonFields=userDefined"
    body = {"metadata": {"sources": [{"etag": "wrong"}]}, "userDefined": []}
    assert fetch(server, path, "PATCH", body)[0] == 400
    assert server.person == original
    body["metadata"]["sources"][0]["etag"] = original["metadata"]["sources"][0]["etag"]
    assert fetch(server, path, "PATCH", body)[0] == 200
    assert server.person["userDefined"] == []
    for key, value in original.items():
        if key not in {"metadata", "userDefined"}:
            assert server.person[key] == value
    _, result = fetch(
        server,
        "/v1/people:batchGet?resourceNames=people/c123&personFields=userDefined&sources=READ_SOURCE_TYPE_CONTACT",
    )
    assert result["responses"][0]["person"].get("userDefined", []) == []


@pytest.mark.parametrize("plural", [False, True])
@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize(
    "action,value,expected",
    [
        ("add", "P-003", ENTRIES + [{"key": "Pipeline ID", "value": "P-003"}]),
        ("add", "P-001", ENTRIES),
        ("remove", "P-001", [ENTRIES[1], ENTRIES[3]]),
        ("remove", None, [ENTRIES[3]]),
    ],
)
def test_edits(action, value, expected, plural, apply, api, server, monkeypatch, capsys):
    server.person["userDefined"] = deepcopy(ENTRIES)
    original = deepcopy(server.person)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    args = [
        f"{action}-custom-field" + ("s" if plural else ""),
        "--contact",
        "c123",
        "--key",
        "Pipeline ID",
    ]
    if value is not None:
        args += ["--value", value]
    assert cli.main(args + (["--apply"] if apply else [])) == 0
    output = capsys.readouterr().out
    assert server.person["userDefined"] == (expected if apply else ENTRIES)
    for key, entry in original.items():
        if key not in {"metadata", "userDefined"}:
            assert server.person[key] == entry
    assert server.writes == int(apply and expected != ENTRIES)
    if expected != ENTRIES:
        assert "1. Pipeline ID —" in output
        assert ("Proposed" in output) == (not apply)
    patches = [call for call in server.calls if call[0] == "PATCH"]
    if patches:
        assert patches[0][2]["updatePersonFields"] == ["userDefined"]


@pytest.mark.parametrize("action", ["add", "remove"])
def test_case_only_notice_is_not_a_match(action, api, server, monkeypatch, capsys):
    server.person["userDefined"] = [{"key": "Created", "value": "Example"}]
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert (
        cli.main(
            [
                f"{action}-custom-field",
                "--contact",
                "c123",
                "--key",
                "created",
                "--value",
                "example",
                "--apply",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Similar entries (case differs): 1 entry" in output
    assert "Created — Example" in output
    assert len(server.person["userDefined"]) == (2 if action == "add" else 1)
    assert server.writes == int(action == "add")


@pytest.mark.parametrize("answer", [False, True])
def test_remove_final_entry_requires_confirmation(answer, api, server, monkeypatch):
    server.person["userDefined"] = [{"key": "Duplicate", "value": "Example"}]
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)

    def confirm(question):
        assert server.writes == 0
        assert question == "Remove 1 custom field entry?"
        return answer

    monkeypatch.setattr(cli, "confirm_apply", confirm)
    assert cli.main(["remove-custom-field", "--contact", "c123", "--key", "Duplicate"]) == 0
    assert server.person["userDefined"] == (
        [] if answer else [{"key": "Duplicate", "value": "Example"}]
    )


@pytest.mark.parametrize("key,value", [(" ", "x"), ("x", ""), ("x", "bad\nvalue")])
def test_invalid_input_before_auth(key, value, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("auth"))
    assert cli.main(["add-custom-field", "--contact", "c123", "--key", key, "--value", value]) == 1


@pytest.mark.parametrize("fault", ["response", "readback", "unrelated", "concurrent"])
def test_update_verification_and_conflicts(fault, api, server, monkeypatch, capsys):
    server.person["userDefined"] = deepcopy(ENTRIES)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    original_get = api.get_contact
    reads = 0

    def altered(*a, **k):
        nonlocal reads
        reads += 1
        saved = original_get(*a, **k)
        if fault == "concurrent" and reads == 2:
            saved["userDefined"].append({"key": "Other", "value": "Changed"})
        if fault == "readback" and reads == 3:
            saved["userDefined"] = deepcopy(ENTRIES)
        return saved

    monkeypatch.setattr(api, "get_contact", altered)
    original_write = api.write

    def write(*a, **k):
        result = original_write(*a, **k)
        if fault == "response":
            result["userDefined"] = deepcopy(ENTRIES)
        if fault == "unrelated":
            result["phoneNumbers"] = []
        return result

    monkeypatch.setattr(api, "write", write)
    assert cli.main(
        ["remove-custom-field", "--contact", "c123", "--key", "Pipeline ID", "--apply"]
    ) == (1 if fault == "concurrent" else 3)
    assert server.writes == (0 if fault == "concurrent" else 1)
    output = capsys.readouterr().err
    assert (
        "changed since preview" in output
        if fault == "concurrent"
        else "verification failed" in output
    )


@pytest.mark.parametrize("action", ["add", "remove"])
def test_global_options_and_singular_help(action):
    command = f"{action}-custom-field"
    args = [
        command,
        "--contact",
        "c123",
        "--key",
        "Created",
        "--token",
        "/tmp/token.json",
        "--auth-timeout",
        "5",
    ]
    if action == "add":
        args += ["--value", "Example"]
    parsed = cli.parser().parse_args(args)
    assert str(parsed.token) == "/tmp/token.json" and parsed.auth_timeout == 5
    assert command + "s" not in cli.parser().format_help()


@pytest.mark.parametrize("values", [None, [{}], [{"key": "Created", "value": 1}]])
def test_malformed_stored_entries_abort(values, api, server, monkeypatch):
    server.person["userDefined"] = values
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert (
        cli.main(["remove-custom-field", "--contact", "c123", "--key", "Created", "--apply"]) == 1
    )
    assert server.writes == 0


def test_size_guard_before_confirmation(api, server, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    monkeypatch.setattr(cli, "confirm_apply", lambda *a: pytest.fail("confirmation"))
    assert (
        cli.main(
            [
                "add-custom-field",
                "--contact",
                "c123",
                "--key",
                "Example",
                "--value",
                "x" * (128 * 1024),
            ]
        )
        == 1
    )
    assert server.writes == 0


def test_whitespace_is_significant(api, server, monkeypatch):
    server.person["userDefined"] = [{"key": " Created ", "value": "Example"}]
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert (
        cli.main(["remove-custom-field", "--contact", "c123", "--key", "Created", "--apply"]) == 0
    )
    assert server.writes == 0


def test_missing_add_value_is_usage_error():
    with pytest.raises(SystemExit) as exc:
        cli.main(["add-custom-field", "--contact", "c123", "--key", "Created"])
    assert exc.value.code == 2


def test_add_first_custom_field(api, server, monkeypatch):
    server.person.pop("userDefined", None)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert (
        cli.main(
            [
                "add-custom-field",
                "--contact",
                "c123",
                "--key",
                "Example",
                "--value",
                "First",
                "--apply",
            ]
        )
        == 0
    )
    assert server.person["userDefined"] == [{"key": "Example", "value": "First"}]
