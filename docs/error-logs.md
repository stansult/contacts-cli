# API error logs

When a Google API request ends with an HTTP error, the CLI saves its full response body and prints:

```text
Error details saved to: /path/to/contacts-cli/.contacts-cli/logs/error-2026-11-14-013320-abcdef.json
```

In a checkout, logs live in `.contacts-cli/logs/`, which is Git-ignored and excluded from package
archives. An installed copy uses `~/.local/state/contacts-cli/logs/`. Set
`CONTACTS_CLI_ERROR_LOG_DIR` to choose another directory. Each error gets a separate file, created
with owner-only read/write permissions. Logs remain until you remove them; there is no automatic
rotation.

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
A successful request does not create a log. These detailed error files are separate from the
aggregate [sender-sync metrics](metrics.md).
