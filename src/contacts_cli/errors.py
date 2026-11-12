"""User-facing failures without raw API responses or credential contents."""


class SyncError(Exception):
    """A failure that should be reported without a traceback."""


class WriteUnverified(SyncError):
    """A write may have occurred, but its result could not be verified."""
