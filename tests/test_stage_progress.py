"""Generic progress timing, rendering, and cleanup independent of Gmail."""

import io
import threading
from datetime import datetime

import pytest

from contacts_cli import progress as module
from contacts_cli.output import OperationalOutput, emit


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.mark.parametrize(
    "seconds,elapsed,duration",
    [(4.999, False, False), (5, True, False), (9.999, True, False), (10, True, True)],
)
def test_thresholds_and_fixed_start_timestamp(seconds, elapsed, duration):
    stream = Terminal()
    monotonic = [0.0]
    wall = [datetime(2026, 11, 15, 12, 0, 0)]
    with OperationalOutput(lambda: wall[0]):
        with module.StageProgress(stream, lambda: monotonic[0], background=False) as stage:
            stage.start("Working")
            monotonic[0] = seconds
            wall[0] = datetime(2026, 11, 15, 11, 0, 0)  # Wall clock moved backwards.
            stage.tick()
            live = stream.getvalue().split("\r")[-1]
            assert live.startswith("[12:00:00] Working")
            assert ("elapsed" in live) is elapsed
            stage.finish("Done")
    final = stream.getvalue().split("\r")[-1]
    assert final.startswith("[11:00:00] Done")
    assert ("took" in final) is duration
    assert stream.getvalue().count("[2026-11-15]") == 1


def test_redirected_output_and_final_details():
    stream = io.StringIO()
    now = [0]
    with module.StageProgress(stream, lambda: now[0]) as stage:
        stage.start("Counting", details="0 items", timestamp=False)
        now[0] = 12
        stage.update("9 items")
        stage.tick()
        stage.finish("Count finished")
    output = stream.getvalue()
    assert "\r" not in output and "\x1b" not in output
    assert output.endswith("Count finished: 9 items (took 12.0s).\n")
    assert stage.thread is None


@pytest.mark.parametrize(
    "error,status", [(RuntimeError("test"), "failed"), (KeyboardInterrupt(), "interrupted")]
)
def test_exception_stops_worker(error, status):
    stream = Terminal()
    stage = module.StageProgress(stream)
    with pytest.raises(type(error)), stage:
        stage.start("Working")
        assert stage.thread.is_alive()
        raise error
    assert stage.thread is None
    assert f"Working: {status}" in stream.getvalue()
    assert stream.getvalue().endswith("\n")


def test_spinner_updates_during_blocking_stage_and_stops_before_prompt():
    updated = threading.Event()

    class Observed(Terminal):
        def write(self, text):
            result = super().write(text)
            if "⠙" in text:
                updated.set()
            return result

    stream = Observed()
    with module.StageProgress(stream) as stage:
        stage.start("Waiting")
        assert updated.wait(2), "updater did not run while main thread was waiting"
        emit("Choose? ", file=stream, end="")
        assert stage.thread is None
        assert stream.getvalue().endswith("Choose? ")
    assert stage.thread is None


def test_midnight_completion_date():
    stream = Terminal()
    wall = [datetime(2026, 11, 15, 23, 59, 59)]
    with OperationalOutput(lambda: wall[0]):
        with module.StageProgress(stream, background=False) as stage:
            stage.start("Working")
            wall[0] = datetime(2026, 11, 16, 0, 0, 1)
            stage.finish("Done")
    assert stream.getvalue().endswith("[2026-11-16]\n")
    assert "[00:00:01] Done." in stream.getvalue()
