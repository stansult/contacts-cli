"""User-facing failures without raw API responses or credential contents."""


class SyncError(Exception):
    """A failure that should be reported without a traceback."""


class MissingToken(SyncError):
    """No saved token file exists; interactive authorization may be offered."""


class InsufficientScopes(SyncError):
    """Saved credentials lack required permissions; reauthorization may be offered."""


class WriteUnverified(SyncError):
    """A write may have occurred, but its result could not be verified."""
