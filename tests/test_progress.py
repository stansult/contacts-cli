"""Progress observes real scan events without changing preview or write behavior."""

import pytest

from contacts_cli import cli
from contacts_cli.errors import SyncError


@pytest.mark.parametrize("failure", [None, "error", "interrupt"])
def test_scan_reports_progress_before_requests(api, server, monkeypatch, capsys, failure):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    request = server.request
    observed = []

    def intercepted(uri, method="GET", **kwargs):
        if "people:batchGet" in uri:
            assert "Reading contact" in capsys.readouterr().err
            observed.append("contact")
        elif uri.endswith("/labels?alt=json"):
            assert "Finding label" in capsys.readouterr().err
            observed.append("label")
        elif "/messages?" in uri and not observed.count("scan"):
            assert "Searching senders" in capsys.readouterr().err
            observed.append("scan")
            if failure == "error":
                raise SyncError("Synthetic read error")
            if failure == "interrupt":
                raise KeyboardInterrupt
        return request(uri, method=method, **kwargs)

    monkeypatch.setattr(server, "request", intercepted)
    result = cli.main(["sender-sync", "--label", "Example/Delivery", "--contact", "people/c123"])
    output = capsys.readouterr()
    assert observed == ["contact", "label", "scan"]
    assert server.writes == 0
    if failure is None:
        assert result == 0
        assert "Searching senders: 3 inspected, 3 new senders\nSearch finished." in output.err
        assert "Proposed additions: 3" in output.out
    else:
        assert result == (1 if failure == "error" else 130)
        assert "Search finished" not in output.err
        assert (
            "Synthetic read error" if failure == "error" else "no contact changes made"
        ) in output.err
    assert "\r" not in output.err and "\x1b" not in output.err


@pytest.mark.parametrize("terminal,interval", [(True, 1.0), (False, 10.0)])
def test_progress_rate_limit_and_line_cleanup(terminal, interval):
    import io

    from contacts_cli.progress import ScanProgress

    class Stream(io.StringIO):
        def isatty(self):
            return terminal

    stream = Stream()
    now = [0.0]
    with ScanProgress(stream, lambda: now[0]) as progress:
        progress("Searching senders")
        first = stream.getvalue()
        now[0] = interval / 2
        progress("Searching senders", 1, 1)
        assert stream.getvalue() == first
        now[0] = interval
        progress("Searching senders", 2, 1)
        assert "2 inspected, 1 new senders" in stream.getvalue()
        progress("Search finished", 3, 2)
    output = stream.getvalue()
    assert output.endswith("Searching senders: 3 inspected, 2 new senders\nSearch finished.\n")
    assert ("\r" in output) is terminal


def test_terminal_progress_finishes_line_on_exception():
    import io

    from contacts_cli.progress import ScanProgress

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    stream = Terminal()
    with pytest.raises(KeyboardInterrupt), ScanProgress(stream) as progress:
        progress("Searching senders", 4, 2)
        raise KeyboardInterrupt
    assert stream.getvalue().endswith("4 inspected, 2 new senders\n")
    assert "Search finished" not in stream.getvalue()


def test_scan_callback_counts_processed_messages_and_invalid_headers(api, server):
    server.mailbox["messages"][0]["payload"]["headers"] = [{"name": "From", "value": "broken"}]
    events = []
    scan = api.scan("Example/Delivery", progress=lambda *event: events.append(event))
    counts = [event[1] for event in events if event[0] == "Searching senders"]
    assert counts == [0]
    assert events[-1] == ("Search stopped", 1, 0, 1)
    assert len(scan.problems) == 1
    assert server.writes == 0


def test_empty_scan_reports_zero_counts(api, server):
    server.mailbox["messages"] = []
    events = []
    api.scan("Example/Delivery", progress=lambda *event: events.append(event))
    assert events[-1] == ("Search finished", 0, 0, 0)
