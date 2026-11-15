"""Gmail search input reuses the sender-exclusion workflow."""

import json
from urllib.parse import urlencode

import pytest

from contacts_cli import cli
from contacts_cli.api import exclusion_query
from contacts_cli.metrics import default_path

from .test_fixture_contract import fetch

QUERY = "subject:delivery OR subject:shipment"
ARGS = ["sender-sync", "--contact", "c123", "--search", QUERY]


def test_search_grouping():
    assert exclusion_query({"known@example.com"}, search=QUERY) == (
        '(subject:delivery OR subject:shipment) -from:"known@example.com"'
    )


@pytest.mark.parametrize("extra", [[], ["--label", "Example/Delivery", "--search", QUERY]])
def test_source_required_and_exclusive(extra):
    with pytest.raises(SystemExit) as error:
        cli.main(["sender-sync", "--contact", "c123", *extra])
    assert error.value.code == 2


@pytest.mark.parametrize("search", ["", "  ", "x" * 6001])
def test_invalid_search_before_authorization(search, monkeypatch, capsys):
    def forbidden(*args):
        pytest.fail("invalid search reached authorization")

    monkeypatch.setattr(cli, "connect_with_authorization", forbidden)
    assert cli.main(["sender-sync", "--contact", "c123", "--search", search]) == 1
    assert "Error:" in capsys.readouterr().err


def test_fixture_explicit_search_selection_and_exclusions(server):
    server.search_results[QUERY] = {"m2", "m4"}
    query = f'({QUERY}) -from:"new@example.com"'
    _, result = fetch(
        server, "/gmail/v1/users/me/messages?" + urlencode({"q": query, "includeSpamTrash": "true"})
    )
    assert [item["id"] for item in result["messages"]] == ["m4"]


@pytest.mark.parametrize("apply", [False, True])
def test_search_workflow(api, server, monkeypatch, capsys, apply):
    server.search_results[QUERY] = {"m2", "m4"}
    # Search mode does not require the selected messages to share a Gmail label.
    server.mailbox["messages"][1]["labelIds"] = []
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *args: api)
    assert cli.main(ARGS + (["--apply"] if apply else [])) == 0
    output = capsys.readouterr()
    assert f"Search: {QUERY!r}" in output.out
    assert "Finding label" not in output.err and "Label:" not in output.out
    searches = [call for call in server.calls if call[1].endswith("/messages")]
    assert len(searches) == 3
    assert all("labelIds" not in call[2] for call in searches)
    assert all(call[2]["q"][0].startswith(f"({QUERY}) ") for call in searches)
    assert not any(call[1].endswith("/labels") for call in server.calls)
    assert server.writes == int(apply)
    assert QUERY not in default_path().read_text()
    assert json.loads(default_path().read_text())["scan_complete"]


def test_search_manual_exclusions(api, server, monkeypatch, capsys, tmp_path):
    server.search_results[QUERY] = {"m2", "m4"}
    exclusions = tmp_path / "exclude.txt"
    exclusions.write_text("trash@example.com\n")
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *args: api)
    assert cli.main(ARGS + ["--exclude", "new@example.com", "--exclude-file", str(exclusions)]) == 0
    assert "Proposed additions: 0" in capsys.readouterr().out
    assert not any("/messages/" in call[1] for call in server.calls)
    assert server.writes == 0


def test_combined_search_limit_blocks_partial_apply(api, server, monkeypatch, capsys):
    from urllib.parse import quote

    from contacts_cli import api as api_module

    server.search_results[QUERY] = {"m2", "m4"}
    excluded = {entry["value"].lower() for entry in server.person["emailAddresses"]}
    excluded.update(entry["sendAsEmail"] for entry in server.send_as["sendAs"])
    size = len(quote(exclusion_query(excluded, search=QUERY), safe=""))
    monkeypatch.setattr(api_module, "MAX_QUERY_BYTES", size)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *args: api)
    assert cli.main(ARGS + ["--apply"]) == 1
    assert "exceeds the local" in capsys.readouterr().err
    assert len([call for call in server.calls if call[1].endswith("/messages")]) == 1
    assert server.writes == 0
