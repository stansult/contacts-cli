"""Conservative continuation and outcome reporting for independent import operations."""

from .errors import ContactFailure, ContactVerificationFailure, WriteUnverified
from .output import emit, emit_list


def contact_specific(error):
    """Only known contact-local failures are safe to continue past."""
    if isinstance(error, (ContactFailure, ContactVerificationFailure)):
        return True
    # A missing contact during readback is unverified, but does not affect other targets.
    return isinstance(error, WriteUnverified) and isinstance(error.__cause__, ContactFailure)


class ImportFailures:
    def __init__(self):
        self.rows = []
        self.unverified = 0

    def record(self, target, error, *, location="", remaining=0, unverified=None, announce=True):
        uncertain = isinstance(error, WriteUnverified) if unverified is None else unverified
        self.unverified += int(uncertain)
        outcome = "unverified" if uncertain else "failed before saving"
        detail = f"{target}: {outcome}" + (f" — {location}" if location else "")
        self.rows.append(detail)
        if not announce:
            return
        emit(detail)
        emit(str(error), primary=False)
        if uncertain:
            emit("Inspect this contact before retrying; its write was not verified.", primary=False)
        if remaining:
            emit("Continuing with remaining contacts.")

    @property
    def exit_code(self):
        return 3 if self.unverified else (1 if self.rows else 0)

    def summary(self, remaining=0):
        if self.rows:
            emit(
                f"Import failures: {len(self.rows) - self.unverified} failed before saving; "
                f"{self.unverified} unverified; {remaining} not attempted."
            )
            emit_list(
                "Contacts needing review", enumerate(self.rows, 1), unit=("contact", "contacts")
            )
