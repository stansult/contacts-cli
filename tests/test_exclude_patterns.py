"""Wildcard exclusions filter locally while advancing Gmail by concrete sender addresses."""

from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.errors import SyncError

from .test_exclude import ARGS


@pytest.mark.parametrize("search", [False, True])
@pytest.mark.parametrize("apply", [False, True])
def test_patterns_and_files(search, apply, api, server, monkeypatch, tmp_path, capsys):
    path = tmp_path / "exclude.txt"
    path.write_text(
        "# no shell quotes in files\nNEW*@EXAMPLE.COM — ignored label\n\nspam*@example.com\n"
    )
    original = deepcopy(server.person["emailAddresses"])
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    args = ARGS.copy()
    if search:
        args[1:3] = ["--search", "subject:example"]
        server.search_results["subject:example"] = ["m1", "m2", "m3", "m4", "m5"]
    assert (
        cli.main(
            args
            + [
                "--exclude",
                "new*@example.com",
                "--exclude",
                "spam@example.com",
                "--exclude-file",
                str(path),
            ]
            + (["--apply"] if apply else [])
        )
        == 0
    )
    output = capsys.readouterr()
    assert "1. trash@example.com" in output.out
    assert "1. new@example.com" not in output.out
    assert "Search finished: 2 inspected, 1 new senders" in output.err
    searches = [c for c in server.calls if c[1].endswith("/messages")]
    assert len(searches) == 3
    assert all("*" not in c[2]["q"][0] for c in searches)
    assert '-from:"spam@example.com"' in searches[0][2]["q"][0]
    assert '-from:"new@example.com"' not in searches[0][2]["q"][0]
    assert '-from:"new@example.com"' in searches[1][2]["q"][0]
    assert all(e in server.person["emailAddresses"] for e in original)
    assert server.writes == int(apply)


@pytest.mark.parametrize(
    "pattern,expected",
    [
        ("*", []),
        ("*@example.com", []),
        ("*EXAMPLE.COM", []),
        ("new**@example.com", ["spam@example.com", "trash@example.com"]),
        ("*@*.example.com", ["new@example.com", "spam@example.com", "trash@example.com"]),
        ("*missing.com", ["new@example.com", "spam@example.com", "trash@example.com"]),
    ],
)
def test_all_or_no_pattern_matches(pattern, expected, api, server):
    events = []
    scan = api.scan(
        "Example/Delivery",
        existing_emails=["existing@example.com"],
        excluded_emails=[pattern],
        progress=lambda *args: events.append(args),
    )
    assert list(scan.senders) == expected
    assert scan.messages == 3
    assert not scan.problems
    assert events[-1][0] == "Search finished"
    assert events[-1][1:3] == (3, len(expected))
    assert len([c for c in server.calls if "/messages/" in c[1]]) == 3
    assert server.writes == 0


def test_many_matching_messages_one_header_read(api, server):
    template = deepcopy(server.mailbox["messages"][1])
    server.mailbox["messages"] = [{**deepcopy(template), "id": f"m{i}"} for i in range(100)]
    scan = api.scan("Example/Delivery", excluded_emails=["new*@example.com"])
    assert scan.senders == () and scan.messages == 1
    assert len([c for c in server.calls if c[1].endswith("/messages")]) == 2


@pytest.mark.parametrize(
    "value", ["*a?@example.com", "*a[b]@example.com", "'*@example.com'", "Name <*@example.com>"]
)
def test_invalid_patterns_before_auth(value, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: pytest.fail("network"))
    with pytest.raises(SystemExit):
        cli.main(ARGS + ["--exclude", value])
    path = tmp_path / "bad.txt"
    path.write_text(value)
    assert cli.main(ARGS + ["--exclude-file", str(path)]) == 1


def test_discovered_exclusions_still_have_query_limit(api, monkeypatch):
    from contacts_cli import api as api_module

    original = api_module.exclusion_query

    def limited(addresses, **kwargs):
        if "new@example.com" in addresses:
            raise SyncError("synthetic query limit")
        return original(addresses, **kwargs)

    monkeypatch.setattr(api_module, "exclusion_query", limited)
    with pytest.raises(SyncError, match="query limit"):
        api.scan(
            "Example/Delivery", existing_emails=["existing@example.com"], excluded_emails=["new*"]
        )


def test_all_excluded_apply_is_noop(api, server, monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    before = deepcopy(server.person)
    assert cli.main(ARGS + ["--exclude", "*", "--apply"]) == 0
    output = capsys.readouterr()
    assert "Proposed additions: 0" in output.out or "Adding: 0" in output.out
    assert "No additions needed" in output.out
    assert server.person == before and server.writes == 0
