"""Rate-limited scan status on stderr, leaving the preview on stdout."""

import sys
import time


class ScanProgress:
    def __init__(self, stream=None, clock=None):
        self.stream = stream if stream is not None else sys.stderr
        self.clock = clock if clock is not None else time.monotonic
        self.terminal = self.stream.isatty()
        self.interval = 1.0 if self.terminal else 10.0
        self.last_time = None
        self.last_stage = None
        self.width = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.finish_line()

    def finish_line(self):
        if self.width:
            print(file=self.stream, flush=True)
            self.width = 0

    def __call__(self, stage, processed=0, senders=0, problems=0):
        now = self.clock()
        changed = stage != self.last_stage
        if not changed and self.last_time is not None and now - self.last_time < self.interval:
            return
        if stage in {"Scanning messages", "Scan finished"}:
            message = f"{stage}: {processed} processed, {senders} unique senders"
            if problems:
                message += f", {problems} invalid headers"
        else:
            message = stage + "…"
        if self.terminal:
            if changed:
                self.finish_line()
            print(
                "\r" + message + " " * max(0, self.width - len(message)),
                end="",
                file=self.stream,
                flush=True,
            )
            self.width = len(message)
        else:
            print(message, file=self.stream, flush=True)
        self.last_time = now
        self.last_stage = stage
