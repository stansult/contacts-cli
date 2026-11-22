# Diagnostic logs

The CLI records HTTP errors, malformed message headers, email-verification failures, and
sender-sync run traces separately.
The sections below describe when each is written and how long it is kept.

## Google API HTTP errors

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
Cleanup failures can temporarily leave more than 20 files. Successful verification creates no
verification log.


## Sender-sync run diagnostics

`sender-sync --diagnostics` creates a private `run-<unique>.jsonl` file in the same
log directory. Normal runs do not create these traces. The terminal prints its path at startup and prints
`Run finished (exit code N). Diagnostics: <path>` when the command returns. This is separate
from the HTTP-error and verification logs above, and includes successful runs.

Use `--diagnostics` when investigating slow or failing requests. HTTP-error and email-verification
logs remain automatic without this option.

Each line is an event flushed to disk immediately: command start (process ID and code fingerprint),
API request start, transport attempt start/end/error, request completion/error, and command exit.
Events include local timestamps and elapsed seconds. Requests record the API method, configured
retry limit, available transport timeout, attempt/retry totals, and durations. A null timeout
means the wrapper could not obtain a numeric timeout, not that the request cannot time out.
A `read_deadline` event records the overall read budget. Transport timeout values describe socket
settings; the overall deadline also covers worker startup, DNS, and retry delays. Worker-reported
failures add a `read_worker_error` event with the underlying exception details.
Time between attempts includes the client's retry backoff. Attempts are counted at the Google
client transport boundary; internal credential refreshes or redirects are not separate events.

Non-HTTP failures include exception types, messages, errno, chained causes, and stack locations,
without stack locals. URLs and common credential values are redacted. Arguments, request headers,
request/response bodies, filter contents, and contact data are not deliberately recorded. Exception
messages can still contain contextual details; keep these files local.

While a request is stalled, its attempt-start event is already on disk. An exit event distinguishes
a completed command from an unfinished log; its absence can also mean forced termination or a
logging failure. These logs cannot explain text entered or printed by the shell after CLI exit.

The current file and 19 newest previous `run-*.jsonl` files are retained; other log types are
untouched. Storage/cleanup failures report a warning without changing the command result. There
is no per-file size cap; file size grows with the number of API attempts in that run.


## Malformed message headers

Sender-sync automatically saves `malformed-<timestamp>-<unique>.json` when it skips a message
whose `From` header is missing, duplicated, malformed, or unsupported. No diagnostic flag is
needed. The warning identifies the message and log path. Valid senders can still be added.

Each file contains the local timestamp, command, failure reason and underlying parser reason
when available, plus returned message metadata: ID, thread ID, label IDs, history ID, internal
date, size estimate, and header data. Only fields already returned are recorded. The request asks
for `From` only; no extra message read is made. Message bodies, snippets, credentials, and search
queries are not saved. `Reply-To` collection remains deferred.

Files use the same private log directory and owner-only permissions as HTTP error logs. They
remain until manually removed. One file is written per skipped message per run, even if a later
API failure stops that run; rerunning can create another file for the same message. A failed save
is reported in the skip warning and does not block otherwise valid additions. Raw headers can
contain personal data; review these local files before sharing them.
