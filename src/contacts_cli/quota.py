"""Command-local People API pacing and bounded retries of explicit rate rejections."""

import json
import random
import time
from collections import deque
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from googleapiclient.errors import HttpError

from .output import emit

PEOPLE_REQUESTS_PER_MINUTE = 80
WINDOW_SECONDS = 60
MAX_RATE_RETRIES = 3
MAX_RETRY_WAIT = 120


class PeopleQuota:
    """Conservative request budget shared by reads and writes in one command.

    This is not a complete model of Google's multiple quota buckets. In particular,
    create/update also consume critical reads. Other processes are not counted.
    """

    def __init__(self, *, clock=None, sleep=None):
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.sent = deque()

    def wait(self, seconds, message):
        emit(f"{message} Waiting {seconds:.1f}s; Ctrl+C cancels.")
        self.sleep(seconds)

    def acquire(self):
        while True:
            now = self.clock()
            while self.sent and now - self.sent[0] >= WINDOW_SECONDS:
                self.sent.popleft()
            if len(self.sent) < PEOPLE_REQUESTS_PER_MINUTE:
                self.sent.append(now)
                return
            self.wait(
                max(0, WINDOW_SECONDS - (now - self.sent[0])), "Pacing Google Contacts requests."
            )


def retry_delay(error, retry):
    """Only explicit per-minute/rate rejections qualify, not daily exhaustion."""
    if error.resp.status != 429:
        return None
    try:
        details = json.loads(error.content)["error"]["details"]
        rate = any(
            d.get("@type", "").endswith("google.rpc.ErrorInfo")
            and d.get("reason") == "RATE_LIMIT_EXCEEDED"
            and "day" not in str(d.get("metadata", {})).casefold()
            for d in details
            if isinstance(d, dict)
        )
    except (ValueError, KeyError, TypeError):
        return None
    if not rate:
        return None
    delay = 30 * 2**retry + random.uniform(0, 1)
    header = error.resp.get("retry-after")
    if header:
        try:
            requested = float(header)
        except ValueError:
            try:
                requested = (parsedate_to_datetime(header) - datetime.now(UTC)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                return None
        delay = max(delay, requested)
    # Do not shorten Google's requested delay; stop if it exceeds our bounded wait.
    return delay if delay <= MAX_RETRY_WAIT + 1 else None


def with_quota(request, attempt):
    quota = getattr(request.http, "contacts_quota", None)
    if not isinstance(quota, PeopleQuota):
        quota = PeopleQuota()
    for retry in range(MAX_RATE_RETRIES + 1):
        quota.acquire()
        try:
            return attempt()
        except HttpError as error:
            delay = retry_delay(error, retry) if retry < MAX_RATE_RETRIES else None
            if delay is None:
                raise
            quota.wait(
                delay, f"Google Contacts rate limit reached. Retry {retry + 1}/{MAX_RATE_RETRIES}."
            )
