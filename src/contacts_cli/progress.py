"""Shared stage animation, timing, and output cleanup; domain events supply text."""

import sys
import threading
import time

from .output import ACTIVE_PROGRESS, stamp

ELAPSED_AFTER = 5.0
DURATION_AFTER = 10.0
SPINNER_INTERVAL = 0.1
DETAIL_INTERVAL = 1.0
REDIRECTED_INTERVAL = 10.0
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class StageProgress:
    def __init__(self, stream=None, clock=None, *, background=True):
        self.stream = stream if stream is not None else sys.stderr
        self.clock = clock or time.monotonic
        self.terminal = self.stream.isatty()
        self.background = background
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.label = None
        self.width = 0
        self.frame = 0

    def __enter__(self):
        self.token = ACTIVE_PROGRESS.set(self)
        return self

    def __exit__(self, kind, error, tb):
        try:
            status = "interrupted" if kind and issubclass(kind, KeyboardInterrupt) else "failed"
            self.finish(status=status if kind else "finished")
        finally:
            self._stop()
            ACTIVE_PROGRESS.reset(self.token)

    def _stop(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join()
            self.thread = None

    def _animate(self):
        while not self.stop.wait(SPINNER_INTERVAL):
            self.tick()

    def start(self, label, *, details="", timestamp=True):
        self.finish()
        with self.lock:
            self.label, self.details = label, details
            self.display_details = details
            self.started = self.clock()
            self.last_update = self.started
            prefix = stamp("", self.stream)
            self.prefix = prefix if timestamp else ""
            self.frame = 0
            self._render()
        if self.terminal and self.background:
            self.stop.clear()
            self.thread = threading.Thread(target=self._animate, name="stage-progress", daemon=True)
            self.thread.start()

    def _render(self):
        text = (
            self.prefix
            + self.label
            + (f": {self.display_details}" if self.display_details else "…")
        )
        if self.terminal:
            text += " " + SPINNER[self.frame % len(SPINNER)]
            elapsed = max(0, self.clock() - self.started)
            if elapsed >= ELAPSED_AFTER:
                text += f" · elapsed {int(elapsed)}s"
            print(
                "\r" + text + " " * max(0, self.width - len(text)),
                end="",
                file=self.stream,
                flush=True,
            )
            self.width = len(text)
        else:
            print(text, file=self.stream, flush=True)

    def tick(self):
        with self.lock:
            if self.label is not None and self.terminal:
                self.frame += 1
                if self.clock() - self.last_update >= DETAIL_INTERVAL:
                    self.display_details = self.details
                    self.last_update = self.clock()
                self._render()

    def update(self, details, *, force=False):
        with self.lock:
            self.details = details
            interval = DETAIL_INTERVAL if self.terminal else REDIRECTED_INTERVAL
            if force or self.clock() - self.last_update >= interval:
                self.display_details = details
                self._render()
                self.last_update = self.clock()

    def pause(self):
        """Stop before other output or a prompt, retaining the stage's timing."""
        self._stop()
        with self.lock:
            if self.width:
                print(file=self.stream, flush=True)
                self.width = 0

    def finish(self, text=None, *, status="finished"):
        self._stop()
        with self.lock:
            if self.label is None:
                return
            elapsed = max(0, self.clock() - self.started)
            if self.width:
                print("\r" + " " * self.width + "\r", end="", file=self.stream, flush=True)
                self.width = 0
            text = text or f"{self.label}: {status}"
            if self.details:
                text += f": {self.details}"
            if elapsed >= DURATION_AFTER:
                text += f" (took {elapsed:.1f}s)"
            print(stamp(text + ".", self.stream), file=self.stream, flush=True)
            self.label = None


class ScanProgress(StageProgress):
    """Translate scan events into generic stages; all rendering is shared."""

    def finish_line(self):
        self.finish()

    def __call__(self, stage, processed=0, senders=0, problems=0, *, force=False):
        noun = "sender" if senders == 1 else "senders"
        details = f"{processed} inspected, {senders} new {noun}"
        if problems:
            details += f", {problems} invalid headers"
        if stage in {"Search finished", "Search stopped"}:
            self.details = details
            self.finish(stage)
        elif stage == "Searching senders":
            if self.label != stage:
                self.start(stage, details=details, timestamp=False)
            else:
                self.update(details, force=force)
        else:
            self.start(stage)
