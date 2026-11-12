# Local run metrics

Each parsed `sender-sync` invocation appends one JSON record to `.contacts-cli/runs.jsonl` in
this checkout, including failures and Ctrl+C interruptions. The directory is Git-ignored and
excluded from distribution archives. Nothing is uploaded. Current runs use `sender-exclusion-v1`.

Run the usual sync command to collect a baseline, then summarize it:

```sh
make metrics
```

To inspect another log:

```sh
uv run --locked python -m contacts_cli.metrics /path/to/runs.jsonl
```

An installed wheel stores metrics under `~/.local/state/contacts-cli/runs.jsonl` instead.
`CONTACTS_CLI_METRICS_DIR` overrides the directory for both recording and analysis. Keep any
override outside tracked files. Delete the log to reset the baseline. New directories/files use
owner-only permissions. A storage failure prints a warning and does not change the command result.

## Recorded fields

- UTC start time, schema version, package version, algorithm name, and a source-code fingerprint.
  The fingerprint distinguishes local code changes even when the package version is unchanged.
- Total elapsed seconds, including authorization and confirmation waits. API seconds exclude those
  waits and include library retry backoff; compare those when judging scan performance.
- Per-operation API calls, HTTP attempts, retries, and cumulative seconds: sending-address lookup, label lookup, message
  listing, header retrieval, contact reads, and contact writes. Attempts count calls to the Google
  client's HTTP transport, not lower-level redirects or token refresh requests. Read retry limits
  and the prohibition on write retries are unchanged.
- Processed messages, unique senders, invalid headers, existing email entries, and proposed additions.
  Unavailable counts are omitted. Interrupted scans retain the last completed message counts;
  `scan_complete` is false until the search returns no remaining matches.
- Exit code and outcome: `preview`, `applied`, `no_changes`, `failed`, `interrupted`, or
  `unverified_write`. Help/parser errors, standalone authorization, and duplication are not recorded.

Records never contain addresses, names, labels, contact/message IDs, queries, tokens, URLs, response
bodies, or error text. There is no account or label grouping identifier. The log still reveals run
times and mailbox-size statistics; review any findings before publishing them in this public repo.

## Comparing runs

The summary groups by algorithm, package version, code fingerprint, and outcome. It shows run count,
median elapsed and API seconds, and total API calls/retries. Invalid or truncated lines are skipped and
counted. Raw records retain per-operation timings and scan counts for closer analysis.

Compare completed scans with similar message/sender counts and separate interrupted runs. Total
elapsed time includes human waits; use API timings to explain the difference. Current
`sender-exclusion-v1` runs are grouped separately from any earlier `full-scan-v1` records.
For the new algorithm, messages count inspected headers and senders count new addresses; excluded
messages and existing senders are not counted.
Keep analysis code and metric definitions in Git. Only publish synthetic benchmarks or findings
that have been reviewed for privacy. Raw logs stay local.
