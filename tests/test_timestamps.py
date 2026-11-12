"""Shared CLI timestamp convention, including midnight and continuation lines."""

import io
import re
from datetime import datetime

import pytest

from contacts_cli import cli
from contacts_cli.output import OperationalOutput, emit
from contacts_cli.progress import ScanProgress


def undecorated(text):
    text = re.sub(r"^\[\d{4}-\d{2}-\d{2}\]\n", "", text, flags=re.M)
    return re.sub(r"\[\d{2}:\d{2}:\d{2}\] ", "", text)


@pytest.mark.parametrize("cross_midnight", [False, True])
def test_dates_and_multiline_blocks(cross_midnight):
    stream = io.StringIO()
    now = [datetime(2026, 11, 12, 23, 59, 58)]
    with OperationalOutput(lambda: now[0]):
        emit("\nStarting\n  detail\n", file=stream)
        if cross_midnight:
            now[0] = datetime(2026, 11, 13, 0, 0, 2)
        emit("Finished", file=stream)
    expected = "[2026-11-12]\n\n[23:59:58] Starting\n  detail\n\n"
    expected += "[00:00:02] Finished\n[2026-11-13]\n" if cross_midnight else "[23:59:58] Finished\n"
    assert stream.getvalue() == expected


def test_empty_context_and_continuations_have_no_decoration():
    stream = io.StringIO()
    with OperationalOutput():
        emit("detail\n", file=stream, primary=False)
    assert stream.getvalue() == "detail\n\n"


@pytest.mark.parametrize("terminal", [False, True])
def test_terminal_final_counter_and_shared_stream_date(terminal):
    class Terminal(io.StringIO):
        def isatty(self):
            return terminal

    stream, other = Terminal(), io.StringIO()
    now = [datetime(2026, 11, 12, 1, 2, 3)]
    with OperationalOutput(lambda: now[0]):
        with ScanProgress(stream, lambda: 0) as progress:
            progress("Reading contact")
            progress("Searching senders", 8, 8)
            now[0] = datetime(2026, 11, 12, 1, 2, 4)
            progress("Search finished", 9, 9)
        emit("Proposed additions: 9\n  + example@example.com", file=other)
    assert stream.getvalue().count("[2026-11-12]") == 1
    assert "[01:02:03] Reading contact…" in stream.getvalue()
    assert "Searching senders: 9 inspected, 9 new senders\n" in stream.getvalue()
    assert not re.search(r"\[\d{2}:\d{2}:\d{2}\] Searching senders:", stream.getvalue())
    assert stream.getvalue().endswith("[01:02:04] Search finished.\n")
    assert other.getvalue() == "[01:02:04] Proposed additions: 9\n  + example@example.com\n"


def test_help_is_undecorated_and_error_is_timestamped(capsys):
    with pytest.raises(SystemExit) as result:
        cli.main(["--help"])
    assert result.value.code == 0
    help_text = capsys.readouterr().out
    assert help_text == undecorated(help_text)
    assert cli.main(["duplicate", "--contact", "bad"]) == 1
    error = capsys.readouterr().err
    assert re.match(r"\[\d{4}-\d{2}-\d{2}\]\n\[\d{2}:\d{2}:\d{2}\] Error:", error)


def test_interrupt_rollover_is_closed(monkeypatch, capsys):
    from contacts_cli import output

    now = [datetime(2026, 11, 12, 23, 59, 58)]
    monkeypatch.setattr(output, "local_now", lambda: now[0])

    def interrupted(*args):
        emit("Connecting", file=cli.sys.stderr)
        now[0] = datetime(2026, 11, 13, 0, 0, 2)
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "connect_with_authorization", interrupted)
    assert cli.main(["duplicate", "--contact", "people/c123"]) == 130
    assert capsys.readouterr().err.endswith(
        "[00:00:02] Interrupted; no contact changes made.\n[2026-11-13]\n"
    )
