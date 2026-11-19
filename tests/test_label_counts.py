"""Account-only label counts use the existing paginated response."""

import pytest

from contacts_cli import cli

from .test_fixture_contract import fetch
from .test_label_edit import group
from .test_remove_label import apply_group


def test_count_fixture_field_mask(server):
    resource = group(server, "Example")
    server.groups[resource]["memberCount"] = 12
    _, result = fetch(server, "/v1/contactGroups?groupFields=name,memberCount")
    assert result["contactGroups"] == [
        {"resourceName": resource, "name": "Example", "memberCount": 12}
    ]
    _, result = fetch(server, "/v1/contactGroups?groupFields=name")
    assert result["contactGroups"] == [{"resourceName": resource, "name": "Example"}]


@pytest.mark.parametrize("scoped", [False, True])
def test_counts_account_only(scoped, api, server, monkeypatch, capsys):
    for name, count in [("Alpha", None), ("Beta", 1), ("Gamma", 12), ("Delta", 0)]:
        resource = group(server, name)
        if count is not None:
            server.groups[resource]["memberCount"] = count
        if count:
            apply_group(server, resource)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    baseline = server.writes
    server.calls.clear()
    assert cli.main(["list-label"] + (["--contact", "c123"] if scoped else [])) == 0
    output = capsys.readouterr().out
    if scoped:
        assert "1. Beta\n" in output and "2. Gamma\n" in output and "—" not in output
    else:
        assert "1. Alpha — 0 contacts" in output
        assert "2. Beta — 1 contact\n" in output
        assert "3. Delta — 0 contacts" in output
        assert "4. Gamma — 12 contacts" in output
    reads = [call for call in server.calls if call[1] == "/v1/contactGroups"]
    assert len(reads) == 4  # Fixture returns one group per page.
    assert all(("memberCount" in call[2]["groupFields"][0]) == (not scoped) for call in reads)
    assert not any(call[1].startswith("/v1/contactGroups/") for call in server.calls)
    assert server.writes == baseline


@pytest.mark.parametrize("count", [-1, "3", True, None])
def test_malformed_count_is_not_reported_as_zero(count, api, server, monkeypatch, capsys):
    resource = group(server, "Example")
    server.groups[resource]["memberCount"] = count
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    assert cli.main(["list-label"]) == 0
    assert "Example — count unavailable" in capsys.readouterr().out
