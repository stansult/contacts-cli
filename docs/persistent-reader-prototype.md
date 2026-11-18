# Persistent read worker: design and benchmark evidence

Status: integrated into normal CLI commands. Reads reuse a command-scoped worker;
the 15-second per-operation deadline and parent-side write transport remain unchanged. Explicitly
authorized read-only benchmarks preceded integration; results and limitations are below.

## Purpose and location

[persistent_reader.py](../src/contacts_cli/persistent_reader.py) manages a single sequential child
process whose [read session](../src/contacts_cli/read_worker.py) retains an
`AuthorizedHttp`/`httplib2.Http` connection cache while its parent enforces a fresh deadline for each read. This removes repeated process/import
startup and allows HTTP keep-alive without putting blocking DNS in the main process.

The persistent transport is POSIX-only: it uses nonblocking pipes and selectors, with Linux/macOS
as the intended test platforms. Windows support has not been established. A reader handles one request
at a time; it is not a shared concurrent transport.

## Contract

- Default request budget is 15 seconds, measured with a monotonic clock from before worker startup.
  Input pipe writes, output reads, and network waits share that budget.
- Requests and replies use newline-delimited JSON and monotonically increasing IDs. Credentials
  remain in anonymous pipes, never command arguments or local logs. Each request supplies its
  current credentials; refreshed credentials are returned for the caller to retain.
- The child rejects writes and explicit token-refresh actions. Read authorization may refresh a
  token through the existing authorized transport. Offline tests exercise expired synthetic
  credentials and verify their refreshed values reach
  subsequent reads and parent-side writes. Initial refresh still uses a disposable worker, with
  the existing token-file persistence and its own 15-second deadline.
- The child reuses its HTTP client and cached connections, updating connection/socket timeouts
  for each read. Requests remain sequential.
- Timeout, interruption, worker errors, malformed output, and mismatched response IDs invalidate
  the worker. Cleanup terminates it, waits up to 0.1 seconds, escalates to kill if necessary,
  reaps it, and closes all pipes. Cleanup adds a small overhead after the request deadline.
- Eligible read failures may retry through the existing client retry policy within the same
  operation budget. Transport errors discard the child; a retry starts a new child. HTTP retryable
  responses can reuse the child. DNS failures and exhausted deadlines do not retry.
- Command exit closes the child and parent HTTP transport, including cancellation and unexpected
  errors. Explicit close is terminal and idempotent. Each CLI invocation owns a separate transport.
- stderr is drained and discarded, preventing pipe backpressure without retaining sensitive text.
  Request and response frames have a 16-MiB cap.

## Offline verification

```sh
uv run --locked pytest tests/test_persistent_reader_probe.py
```

The child fixture starts an HTTP/1.1 server bound exclusively to `127.0.0.1`, on an ephemeral
port. It uses synthetic credentials and makes no external requests. It requires permission to
bind a local socket. Parent pytest sockets remain disabled; the fixture subprocess deliberately
uses loopback sockets to test real connection reuse.

The fixture is independently exercised through its raw protocol before testing the parent.
It records accepted TCP connections, proving that two reads used one connection, and observes
synthetic authorization headers to check credential changes. Markers inside stalled DNS resolution
and the slow-response handler establish that tests reach those operations.

Coverage includes repeated reads, independent per-read budgets, DNS and body stalls, partial
protocol responses, blocked input pipes, worker crashes, malformed/mismatched replies, noisy
stderr, SIGINT, a worker ignoring SIGTERM, restart after failure, explicit close, and the write
guard. Tests inspect child exit state and closed pipes. Controlled faults disabling reuse,
extending the deadline, and omitting pipe closure must each fail the relevant regression.

## Read-only Google benchmark

On November 17, 2026, an explicitly authorized isolated benchmark compared six reads per
transport, alternating which transport went first in each pair. Both used the same Gmail
`users.labels.list` GET request with `fields=labels(id)`, existing account credentials, and a
15-second deadline per request. All 12 requests returned HTTP 200 and identical label ID sets.
No Google data was changed. Responses and credentials were not retained in benchmark output.

| Measurement | Seconds |
| --- | ---: |
| Disposable worker median, six reads | 0.756 |
| Persistent worker first read | 0.667 |
| Persistent worker median, five subsequent reads | 0.341 |
| Persistent worker median, all six reads | 0.355 |

Warm persistent reads were about 55% faster than the disposable-worker median in this sample.
Times cover the complete parent request, including process startup where needed and network
work; these components were not individually instrumented. This small sequential benchmark
establishes successful live Google reads and reduced latency for this endpoint. It does not
measure a complete sender scan, prove Google reused a particular TCP connection, or establish
performance of message-search and header requests.

## Full sender-search benchmark

A second explicitly authorized read-only comparison on November 17 used the production scan
algorithm with the same contact snapshot and search for both transports. It included sending-address
exclusions, incremental message searches, and From-header reads. Only the isolated probe replaced
worker dispatch; normal CLI networking was unchanged. Existing per-operation budgets and retry
handling remained active.

| Measurement | Disposable worker | Persistent worker |
| --- | ---: | ---: |
| Complete scan time | 40.482 s | 14.706 s |
| Messages inspected / senders found | 27 / 27 | 27 / 27 |
| Sending-address reads | 1 | 1 |
| Message searches | 28 | 28 |
| Header reads | 27 | 27 |

All 56 requests per scan returned HTTP 200. Complete scan results, including addresses, display
labels, and problems, matched. The persistent worker exited and all its pipes were closed after
completion. Contact snapshot loading was outside the timed scans; the persistent worker started
cold inside its timed scan. No contacts or Gmail data were changed.

The persistent scan took about 64% less time (2.75 times as fast). This was one completed pair,
with the disposable worker first, not an order-balanced repeated trial; network variability and
service caching may affect the exact gain. The earlier label benchmark alternated ordering.

An initial benchmark attempt stopped because its literal-GET guard rejected the client library's
POST-with-GET-override encoding for long search queries. The probe was corrected to use the
production read-only predicate, and both scans were rerun fully. No runtime code was changed.

## User verification after integration

Two user-run searches on November 17 inspected 27 messages in 14.9 and 15.5 seconds, compared
with the original reported 44 seconds. One run cancelled at selection without changes; the other
selected 14 addresses and reported all 14 saved and verified. Active times were 16.0 and 17.2
seconds, excluding prompt waits. These observations confirm the integrated preview/cancellation
and selected-save paths in that account; they are not a latency guarantee.

## Integration and remaining limits

`DeadlineHTTP` owns the persistent reader. `GoogleAPI.close()` closes that shared transport, and
CLI command cleanup calls it on all exit paths. Failed client construction also closes its
transport. Read replies update the credentials held by the parent transport; writes continue
using that transport without worker dispatch or automatic replay. Initial authorization refresh
and token saving retain their existing behavior.

Retries, backoff, process startup, pipe I/O, DNS, and response download share the operation's
monotonic deadline. Structured worker errors still reach existing diagnostics; HTTP error bodies
reach the existing error logger. The isolated benchmark entry point delegates to the production
implementation, avoiding a separate copy of the transport.

Benchmark timing is evidence from one environment, not a latency guarantee. Offline tests do not
establish all proxy/TLS environments or service behavior. Linux is covered by the project's CI
matrix; the local integration checks run on macOS. No Windows support is claimed.
