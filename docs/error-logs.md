# API error and verification logs

When a Google API request ends with an HTTP error, the CLI saves its full response body and prints:

```text
Error details saved to: /path/to/contacts-cli/.contacts-cli/logs/error-2026-11-14-013320-abcdef.json
```

In a checkout, logs live in `.contacts-cli/logs/`, which is Git-ignored and excluded from package
archives. An installed copy uses `~/.local/state/contacts-cli/logs/`. Set
`CONTACTS_CLI_ERROR_LOG_DIR` to choose another directory. Each error gets a separate file, created
with owner-only read/write permissions. HTTP error logs remain until you remove them; they have no automatic rotation.

Each JSON record contains:

- `timestamp`: local time with its UTC offset.
- `command`: the command name, without its arguments.
- `operation`: the Google API method, or a generic operation if unavailable.
- `write`: whether the failed request was a mutation.
- `http_status`: Google's HTTP status code.
- `response_body`: the complete response, without truncation.
- `response_body_encoding`: `utf-8`, or `base64` if the bytes are not valid UTF-8.

The response body is stored as a string to preserve the original text, including non-JSON errors.
Request URLs, request headers, authorization tokens, and outgoing contact payloads are not logged.
Google's response may itself contain account-specific details, so review the file before sharing it.

For HTTP 429, the response may identify the rate or quota limit. Logging does not change retries,
write behavior, or exit codes. Reads retain their existing retries; the final failure response is
logged after those retries are exhausted. Writes are not automatically retried. Connection errors
without an HTTP response have no response body and are not recorded by this logger. OAuth setup
errors are also outside this API response logger.

If the log cannot be saved, the CLI reports that separately and still reports the original failure.
A successful request does not create an HTTP error log. These detailed error files are separate from the
aggregate [sender-sync metrics](metrics.md).


## Email verification failures

When a submitted email update cannot be verified, the CLI automatically writes a separate
`verification-<timestamp>-<unique>.json` file in the same directory and prints
`Verification details saved to: <path>`. No debug option is needed. This covers sender-sync
and add/remove-email updates, including failed independent readback after a write. It does not
add verification logging for creation, duplication, or other field updates.

Each record contains the command (without arguments), local timestamp, contact resource name,
verification stage, mismatch message, and before/expected/saved email entries, including their
metadata and labels. Other contact fields, credentials, Gmail messages, and search queries are
not included. If readback fails without a saved snapshot, `saved` is null; it is never replaced
with the earlier update response.

Files are created with owner-only permissions. These logs contain contact data: keep them local.
The checkout log directory is ignored by Git and excluded from package archives. If you override
the directory, choose a private location outside tracked files.

After successfully writing a log, the CLI retains it and the 19 newest other verification logs
by modification time. Older `verification-*.json` files are deleted automatically; HTTP error
logs and other filenames are untouched. Do not use this filename prefix for unrelated files.
A failed save or cleanup is reported separately and never masks the original verification error.
Cleanup failures can temporarily leave more than 20 files. Successful verification creates no log.
