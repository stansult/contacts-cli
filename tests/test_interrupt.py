"""Interruption messages distinguish reads from submitted contact writes."""

import sys

import pytest

from contacts_cli import cli


@pytest.mark.parametrize("stage", ["connect", "scan", "prompt", "prewrite", "write", "verify"])
def test_sync_interruption_message(stage, api, server, monkeypatch, capsys):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        cli, "connect_with_authorization", interrupt if stage == "connect" else lambda *a: api
    )
    if stage == "scan":
        monkeypatch.setattr(api, "scan", interrupt)
    elif stage == "prompt":
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            monkeypatch.setattr(stream, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", interrupt)
    elif stage in {"prewrite", "write", "verify"}:
        request = server.request

        def intercepted(uri, method="GET", **kwargs):
            if (
                stage == "prewrite"
                and "people:batchGet" in uri
                and server.batch_reads == 1
                or stage == "write"
                and method == "PATCH"
                or stage == "verify"
                and method == "GET"
                and server.writes
            ):
                raise KeyboardInterrupt
            return request(uri, method=method, **kwargs)

        monkeypatch.setattr(server, "request", intercepted)
    args = ["sender-sync", "--contact", "people/c123", "--label", "Example/Delivery"]
    if stage in {"prewrite", "write", "verify"}:
        args.append("--apply")
    assert cli.main(args) == 130
    error = capsys.readouterr().err
    if stage in {"write", "verify"}:
        assert "A contact write was started" in error
        assert "no contact changes made" not in error
    else:
        assert "Interrupted; no contact changes made." in error
        assert "inspect Google Contacts" not in error
        assert server.writes == 0


def test_duplicate_interrupted_after_creation_warns(api, server, monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    request = server.request

    def intercepted(uri, method="GET", **kwargs):
        if method == "GET" and server.writes:
            raise KeyboardInterrupt
        return request(uri, method=method, **kwargs)

    monkeypatch.setattr(server, "request", intercepted)
    assert cli.main(["duplicate", "--contact", "people/c123", "--apply"]) == 130
    assert server.writes == 1
    assert "A contact write was started" in capsys.readouterr().err
