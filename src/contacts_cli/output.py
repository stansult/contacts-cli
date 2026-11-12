"""Shared local wall-clock timestamps for operational output, not help or data."""

import sys
from contextvars import ContextVar
from datetime import datetime

ACTIVE_OUTPUT = ContextVar("operational_output", default=None)


def local_now():
    return datetime.now().astimezone()


class OperationalOutput:
    def __init__(self, clock=None):
        self.clock = clock or local_now
        self.start_date = None
        self.last_stream = None

    def __enter__(self):
        self.token = ACTIVE_OUTPUT.set(self)
        return self

    def __exit__(self, *exc):
        try:
            if self.start_date is not None:
                date = self.clock().strftime("%Y-%m-%d")
                if date != self.start_date:
                    print(f"[{date}]", file=self.last_stream, flush=True)
        finally:
            ACTIVE_OUTPUT.reset(self.token)

    def stamp(self, text, stream):
        now = self.clock()
        if self.start_date is None:
            self.start_date = now.strftime("%Y-%m-%d")
            print(f"[{self.start_date}]", file=stream, flush=True)
        self.last_stream = stream
        return f"[{now:%H:%M:%S}] {text}"


def stamp(text, stream):
    output = ACTIVE_OUTPUT.get()
    return output.stamp(text, stream) if output is not None else text


def emit(text, *, file=None, end="\n", flush=True, primary=True):
    stream = sys.stdout if file is None else file
    output = ACTIVE_OUTPUT.get()
    if output is not None:
        output.last_stream = stream
    if primary:
        lines = text.split("\n")
        for index, line in enumerate(lines):
            if line:
                lines[index] = stamp(line, stream)
                break
        text = "\n".join(lines)
    print(text, file=stream, end=end, flush=flush)
