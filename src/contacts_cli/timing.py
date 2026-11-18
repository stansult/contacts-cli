"""Command elapsed time, excluding interactive input and browser authorization waits."""

import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar

from .output import emit

ACTIVE_TIMER = ContextVar("command_timer", default=None)


class CommandTimer:
    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self.waited = 0.0
        self.wait_depth = 0

    def __enter__(self):
        self.started = self.clock()
        self.token = ACTIVE_TIMER.set(self)
        return self

    def __exit__(self, *exc):
        try:
            elapsed = max(0.0, self.clock() - self.started - self.waited)
            emit(f"Active time: {elapsed:.1f}s", file=sys.stderr)
        finally:
            ACTIVE_TIMER.reset(self.token)


@contextmanager
def waiting_for_input():
    timer = ACTIVE_TIMER.get()
    if timer is None:
        yield
        return
    outer = timer.wait_depth == 0
    started = timer.clock() if outer else None
    timer.wait_depth += 1
    try:
        yield
    finally:
        timer.wait_depth -= 1
        if outer:
            timer.waited += max(0.0, timer.clock() - started)


def read_input():
    with waiting_for_input():
        return input()
