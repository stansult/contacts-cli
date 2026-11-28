# Regression coverage and evidence

[Testing guide](testing.md) covers running checks and validating external calls. This reference
records fixture contracts, regression sensitivity, and the limits of automated and live evidence.
Issue lifecycle status belongs in GitHub Issues.

Each topic separates tested behavior, fixture checks, regression evidence, and limits where
recorded. Live evidence describes specific authorized checks; it does not establish behavior
for other accounts or future service versions. Historical test counts describe checks performed
at the time of a change, not current suite totals.

## Contents

- [Contact input and importing](#contact-input-and-importing)
- [Duplication](#duplication)
- [Contact lookup and labels](#contact-lookup-and-labels)
- [Email and custom-field editing](#email-and-custom-field-editing)
- [Gmail sender searches](#gmail-sender-searches)
- [Presentation and interaction](#presentation-and-interaction)
- [Transport and diagnostics](#transport-and-diagnostics)

## Contact input and importing

### New-contact inputs

**Coverage**

- `test_contact_inputs.py` covers Person field/schema and value validation, partial dates,
  generated fields, singleton and size limits, malformed files, precise locations, inline/file
  exclusivity, and rejection before authorization.
- `test_contact_create.py` covers preview-only behavior, confirmation, label
  pagination/reuse/creation, sequential contact creation, independent readback, partial failures
  and no mutation retries.
- Creation-output tests cover readable previews, requested/saved mismatches, definite rejection,
  unknown write outcomes, interruptions during writing versus verification, partial batches, and
  labels created before contact processing stops.
- These cases verify that each failure prints one outcome without a second generic error from the
  CLI.
- Local validation command tests exercise one object, arrays, missing files, invalid field paths,
  file-only options and the silent plural alias.

**Fixture checks**

- The synthetic full-field fixture is checked independently against the bundled discovery schema
  and explicit expected values.
- The label fixture has independent storage, pagination, and duplicate-name conflict checks.
- All account interactions use the offline HTTP fixture.
- Authorization, connection and input functions are replaced with failing sentinels to verify
  validation remains offline and noninteractive.

### Contact creation selection

**Coverage**

- `test_contact_selection.py` exercises the shared number/range selector through `add-contact`:
  subsets, original input order/numbers, overlaps, invalid selections, reselection, cancellation,
  and end-of-input before any label or contact writes.
- It checks selected contact fields, labels, and absence of automatic custom fields, plus original
  input numbers and selected-only counts after failure or interruption.
- Single-contact confirmation, noninteractive previews, and `--apply` retain their existing
  behavior; validation still covers the full input.

**Regression evidence**

- Six subset/failure cases failed against the original all-or-nothing implementation before the
  change.

### Shared name input and verification

**Coverage**

- `test_name_options.py` covers full names and explicit first/last names in creation and
  duplication, including individual components, input conflicts, blank/control-character values,
  previews, and apply.
- Verification tests reject changed, lost, or unexpected explicit name components while accepting
  generated full names.

**Fixture checks**

- The name tests replay the synthetic readbacks in `fixtures/name-parsing.json` from the live
  probe below.
- The fake transport's configurable name response is independently checked for response/readback
  agreement and deep copying.

**Regression evidence**

- Sixteen cases failed against the previous code; existing duplicate expectations now require
  `unstructuredName` for `--name`.

### Live full-name parsing probe

**Live evidence**

- On 2026-11-21, an authorized isolated People API probe created four synthetic contacts using
  only `unstructuredName` for their names, read each back, then deleted each returned contact ID
  and verified a 404 on readback.
- All four retained the full `unstructuredName`.
- Requests were sequential, used 15-second operation bounds and no retries, and reused the CLI's
  credentials and transport.

| Supplied full name | Observed components |
| --- | --- |
| `Test Tester` | First: `Test`; last: `Tester` |
| `Test Middle Tester` | First: `Test`; middle: `Middle`; last: `Tester` |
| `Test` | First: `Test` only |
| `Test Tester-Smith` | Last: `Tester-Smith` retained |

**Limits**

- These observations establish those examples for the tested account, not a universal parsing rule
  for all cultures or compound surnames.

### Possible duplicates before contact creation

**Coverage**

- `test_contact_matches.py` covers normalized names, restricted company matching, email case and
  plus/dot distinctions, phone formatting with country/extension preservation, multiple matching
  contacts/reasons, and paginated reads.
- Invalid identities, malformed matching fields, and repeated identities/tokens stop creation.
- Command tests cover incoming duplicates, skip/create-separately/cancel, invalid answers and EOF,
  partial selection, skipped inputs, cancellation after earlier choices, and noninteractive
  preview versus apply.
- Every interactive test asserts no writes before each answer.
- The integrated read uses the existing bounded-read/retry policy, with progress across all pages.
- `test_duplicate_presentation.py` checks original input numbers with sparse matching inputs,
  inline matches with dash markers, retained match identities/reasons, and the separate numbered
  merge-target list.
- It also checks the import prompt and omission of redundant full names while preserving
  structured and phonetic names.

**Fixture checks**

- The contact-matching fixture contract checks the requested contact-only source, field mask, page
  size, and page traversal.
- Older partial-failure tests now use distinct synthetic contacts so they still reach their
  intended write/verification failure, rather than stopping at duplicate review.
- Existing independent contact-list fixture checks continue to cover the source matching data.

**Regression evidence**

- Nine command cases failed before integration.
- Temporarily disabling index lookup produced eight expected failures, including unsafe
  noninteractive creation; restoring lookup passed all 36 focused cases.
- The three updated presentation regressions failed against the previous output before
  implementation; the command case also verifies cancellation makes no writes.

**Live evidence**

- An authorized read-only probe on 2026-11-25 tested `people.connections.list` before integration,
  using the normal credentials/transport, contact-only sources, `pageSize=1000`, and
  `personFields=metadata,names,organizations,emailAddresses,phoneNumbers`.
- Two pages returned 1,000 records each in 0.93s and 0.71s, with a continuation token and valid
  resource names.
- The probe used one attempt per page and a 15-second deadline; it saved no contact details.

**Limits**

- This validates list access and request shape, not a live creation or duplicate-choice workflow.

### Duplicate name matching

**Coverage**

- Duplicate-name regressions cover single-part names, compound given names, honorifics, full
  names, email/phone evidence, company-only identity, and inputs within the same import.
- The two-Josh review test verifies that an unchanged phone match cannot redirect a merge to an
  unrelated name-only match.

**Regression evidence**

- Restoring the old name rule made that regression fail; the corrected rule passes.

### Contact merge review

**Coverage**

- `test_contact_merge.py` covers additive property fills, conflict retention, repeated custom
  keys, Created preservation, no-op reruns, target choice/cancellation, input-to-input
  consolidation, multiple inputs sharing one target, label preservation, concurrency, partial
  failures, interrupts, primary choices, and readback loss.
- Merge outcome regressions also cover unchanged inputs and skipped/kept conflicts without final
  approval, existing/new/already-applied labels, mixed creation and unchanged targets, and
  repeated inputs that must retain earlier planned changes.
- Changes plus conflicts remain visible together.
- Prompt assertions inspect stderr as well as stdout; exhausted scripted answers detect unwanted
  extra prompts.

**Fixture checks**

- The independent fixture check exercises multi-field replacement on a second contact, proving
  that only the selected target and fields change and that its etag advances.
- Existing single-field update suites exercise the same fixture.
- Existing fixture contract tests independently verify target-specific updates and label
  membership writes.

**Regression evidence**

- A separate contract check reproduces the list API's 100-email/phone cap and verifies the
  complete individual read fallback; that regression failed before the fallback was added.
- Six command regressions failed before integration.
- Controlled faults that overwrite conflicting values without approval, bypass the pre-write
  reread, and skip verification caused one, one, and five intended test failures respectively.
- All faults were removed before the passing checks.
- Generated address properties and unexpected extra entries have a separate regression: it failed
  before permitting generated properties in changed fields while retaining expected values and
  entry counts.
- Eleven merge-outcome cases failed against the earlier behavior before implementation.

**Live evidence**

- Authorized isolated probes on 2026-11-25 used one synthetic contact each, updating names,
  emails, phones, organizations, addresses, websites, custom fields, Notes, birthdays, events,
  nicknames, and memberships together.
- The first update succeeded in 0.52s but exact verification rejected Google's standard URL label
  normalization from `Profile` to `profile`.
- After correcting that expectation, the second update took 0.52s and independent readback 0.09s;
  verification passed.
- Both synthetic contacts were deleted and their absence verified.
- Existing contacts were untouched.
- Each operation had a 15-second deadline and no retries.

**Limits**

- This establishes the [multi-field request shape](https://developers.google.com/people/api/rest/v1/people/updateContact) ; final CLI review and mixed-batch behavior are
  covered offline and await user live testing.

#### Comparison before review

**Coverage**

- `test_merge_preview.py` checks outcomes before the first choice, one full detail read per
  matched saved contact, no detail reads for unmatched contacts or input-only matches, snapshot
  reuse, per-target results, labels, read failures, local merge validation, and fresh concurrency
  checks.

**Fixture checks**

- The existing matching-list fixture verifies its limited field mask.
- An independently failing fixture contract test was added before enabling individual full reads
  for explicit list records; it checks identity and requested-field filtering.
- The fixture now supplies source metadata for those records, as real saved contacts do.

**Regression evidence**

- Seven regressions failed before integration.

#### Partial failures

**Coverage**

- `test_import_failures.py` verifies default continuation for rejected creations, merge/content
  verification failures and stale targets; stopping for authorization, rate/quota, server/network
  errors and interruption; retained partial results, no write replay, and nonzero final status.
- Shared-label failures and pre-write checks retain their existing coverage.
- Unknown failures stop conservatively; verification mismatches use an explicit contact-specific
  exception distinct from failed network reads after submission.
- A controlled regression also verifies that an unverified merge followed by a batch-wide failure
  never reports “No changes made.”

**Fixture checks**

- The failure-injection fixture is independently checked through direct HTTP calls, including a
  readback mismatch that preserves the stored contact.

**Regression evidence**

- Four continuation regressions failed against the previous stop-first behavior before
  implementation.

#### Useful merge targets

**Coverage**

- `test_merge_choices.py` checks comparison results at the individual decision prompt, omitted
  Merge choices for unchanged inputs, label-only eligibility, filtered target choices, and
  rejection of a hidden Merge action.
- Existing tests also cover accumulated merge decisions, identical inputs, cached reads, and final
  approval after skipping unchanged inputs.

**Regression evidence**

- Two choice regressions failed before implementation; disabling review summaries then failed all
  five prompt-summary cases, confirming they inspect the individual review rather than the
  preview.

#### Skipping unchanged inputs

**Coverage**

- `test_bulk_skip.py` covers default/explicit Yes, No, cancellation and end-of-input, invalid
  replies, selected-only counts, unchanged-only eligibility across all targets,
  label/conflict/input-match exclusions, retained final approval, interactive apply and
  noninteractive behavior.
- Existing individual-review tests explicitly decline bulk skipping when they need to exercise the
  later choices.

**Regression evidence**

- Seven tests failed before integration.

#### Conflict decisions

**Coverage**

- `test_merge_conflicts.py` covers saved/incoming details before the decision, conflict-only
  Merge, Keep/Replace/Keep both outcomes, complete-entry preservation, atomic singleton
  replacement, duplicate-entry target selection, primary metadata, final approval/decline,
  cancellation and EOF, interactive apply, combined inputs, and rejection of incomplete
  verification.
- Email-case regressions verify that capitalization alone needs no resolution and replacing a
  label retains saved address spelling, display name, and primary metadata.
- Additional regressions cover Ctrl+C after earlier conflict choices, Keep both exceeding the
  500-entry limit before writes, and mixed Keep/Replace/Keep both decisions with a complete saved
  contact comparison.

**Fixture checks**

- The existing fixture round-trips replacements and duplicate entries; its update behavior is
  independently exercised by the fixture contract tests.

**Regression evidence**

- Seven regressions failed before implementation.
- Both casing directions and the saved result/final preview are covered; three regressions failed
  before the preservation fix.
- Controlled faults in interruption status, the size guard, and replacement handling each failed
  the intended test; all faults were restored before final checks.

#### Conflict presentation

**Coverage**

- `test_conflict_display.py` covers property-focused Saved/Incoming details, omitted email casing
  and unchanged/unsupplied properties, label-specific choices, multiple differing properties,
  ambiguous saved-entry numbering, nested dates, and properties removed by atomic replacement.

**Regression evidence**

- Three display regressions failed before implementation; data-resolution tests remain unchanged
  except for assertions on the approved wording.

#### Grouped email-label review

**Coverage**

- `test_grouped_email_labels.py` exercises grouped Replace/Keep/cancel and default individual
  review.
- Selection: original numbers/ranges, repeated subset decisions, remaining groups, explicit
  individual review, singleton fallback, rejection of already-decided numbers, and return to
  selection.
- Presentation: single blank-line menu separation; available/reviewing/selected wording;
  cumulative replacement counts excluding Keep; transitions to individual review; saving reminders
  with and without `--apply`.
- Safety and integration: cancellation after partial planning, mixed
  grouped/individual/new-contact imports, final decline, EOF, invalid input, interactive apply,
  noninteractive safety, stale targets, and cached read counts.
- Eligibility tests exclude other property changes, additions, multiple matches/entries/conflicts,
  input matches, shared targets, and missing contact labels; incoming label spelling remains
  exact.
- Different saved labels share a group; row labels stay visible during subset review.
- Empty saved labels remain additions rather than replacements.
- Keep-name summaries omit storage details; missing email labels use human-readable descriptions
  in both available and selected plans.

**Fixture checks**

- The multi-contact fixture has an independent direct-HTTP read/update contract confirming
  distinct targets and preservation of the untouched contact.

**Regression evidence**

- Four regressions failed before integration.
- Disabling the structural label-only check caused the display-name exclusion test to fail.

### Individual merge review and anchored names

**Coverage**

- `test_name_merge_review.py` checks Andrew → Drew against an existing surname, compound surnames,
  Keep/Replace preservation, ambiguous-name fallback, meaningful previews, additions visible
  before Merge, numbered name/email decisions, and verified writes through the existing fake
  Google server.
- Existing atomic-name tests retain ambiguous inputs so whole-entry replacement remains covered.
- No new Google API operation is introduced.

**Regression evidence**

- Five regressions failed before implementation.

### Grouped conflict-free merges

**Coverage**

- `test_grouped_additions.py` exercises Merge/Skip/cancel, direct subset selection, remaining
  groups, individual and singleton fallback, final decline, interactive apply, noninteractive
  behavior, shared/ambiguous/input targets, cached reads, stale-contact protection, requested
  contact labels, and mixed batches of replacements, additions, conflicts, and new contacts.

**Fixture checks**

- Fixtures assert distinct matches and reuse the independently verified multi-contact fake-server
  contract.

**Regression evidence**

- Disabling candidate grouping made the bulk-action regressions fail; restoring it passed them.

**Limits**

- Writes use the existing merge path and its verification tests; no live Google access is part of
  these checks.

### Compact label-only imports

**Coverage**

- `test_label_only_import.py` covers single and multiple contacts, original subset numbers,
  differing missing-label sets, mixed creation/update/skip batches, repeated targets, ambiguity,
  conflicts, new labels, cancellation, noninteractive preview/apply, stale contacts,
  contact-specific failures, interruption cleanup, and redirected progress.
- Existing merge tests retain full update/readback verification coverage.

**Fixture checks**

- A direct fake-transport PATCH independently checks that membership updates preserve contact
  details.

**Regression evidence**

- Compact-review regressions failed before implementation.

## Duplication

### Duplication fixture contracts

**Coverage**

- Success and partial-failure output must link to `/person/c456`, not `/person/c1c8`.
- Creation and duplication tests check that no automatic custom fields are added, supplied or
  copied custom fields remain unchanged, and missing saved custom fields fail verification.

**Fixture checks**

- Duplication tests use the bundled People discovery schema and synthetic source contacts.
- Fixture contracts independently check creation, separate source/destination storage, masked
  reads, missing contacts, and photo writes.
- Duplicate-link regression: a created fixture contact uses resource `people/c456` and source ID
  `1c8`.
- The independent fixture test confirms those distinct identifiers.

**Regression evidence**

- Controlled faults in the apply gate and saved-field verification must be detected.
- The success assertion failed against the original link construction before the fix.

**Limits**

- These checks do not establish live Google normalization or photo fidelity.
- This automated test does not establish live browser navigation behavior.

### Duplicate field overrides

**Coverage**

- `test_duplicate_options.py` covers name/email/phone replacement, repeated email/phone options,
  clearing, mixed overrides, unrelated-field preservation, preview/apply/confirmation, and
  unchanged source data.
- Invalid values and conflicting options stop before authorization.
- Photo omission skips downloads/uploads, including unusable source-photo data, and verifies the
  new contact has no custom photo.
- Separate checks detect lost replacements and unexpectedly retained cleared fields.
- Existing duplication tests retain full-copy, concurrency, photo-copy, and partial-failure
  coverage.

**Fixture checks**

- The fixture contract independently verifies creation/readback with omitted fields.

**Regression evidence**

- New option and verification tests failed against the original implementation before the feature
  was added.
- Temporary faults disabling replacement or saved-field comparison also failed the new
  preservation and lost-replacement checks; both faults were restored.

### Full-size duplicate photos (#1)

**Coverage**

- Regression tests cover path and suffix size options, retained crop options, conflicting query
  sizes, and exact uploaded bytes.
- Unknown URL size formats stop before downloading.

**Fixture checks**

- Synthetic 8×8 and 64×64 checkerboard PNGs exercise thumbnail versus full-size downloads.
- Fixture dimensions and decoding were independently checked with macOS sips.
- No account images are included in fixtures.

**Regression evidence**

- These cases failed against the thumbnail implementation.

**Live evidence**

- The user confirmed improved photo quality in a live duplication test on 2026-11-12.

**Limits**

- Automated tests do not establish Google's upload fidelity for every image.

## Contact lookup and labels

### Contact listing

**Coverage**

- `test_list_contact.py` covers exact names, case and whitespace, emails, phone formatting,
  country digits and extensions, IDs/URLs, missing contacts, plural routing, multiple matches
  without prompts, pre-authorization validation, read failures, and no writes.
- Partial-name lookup tests cover substring defaults, exact opt-in, first/last/structured names,
  case and whitespace, literal stars, unchanged email/ID/URL rules, exact-phone lookup, plural
  routing, pagination, and no writes.
- Existing resolver tests verify that `add-label` still requires complete names.
- Phone-suffix tests cover countryless and shorter suffixes, formatting, complete-number mode,
  longer searches, non-suffix rejection, exact extension matching, multiple matches, and no
  writes.
- The shared resolver remains exact unless suffix matching is explicitly enabled by
  `list-contact`.

**Fixture checks**

- Tests reuse the contact-resolution fixture and the independently verified paginated contact-list
  transport.

**Regression evidence**

- New command tests failed before implementation; existing resolver tests retain label behavior.
- Partial-name tests failed against exact-only listing before the change.
- Phone-suffix regressions failed before implementation; existing add-label tests retain their
  matching rules.

### Add-label contact resolution

**Coverage**

- `test_contact_resolution.py` covers ID/URL routing, full-name and email case matching, phone
  formatting, optional leading `+`, country-code preservation, and optional or explicit
  extensions.
- Batch resolution: contact files, overlapping targets, multiple-match selection, partial
  selection, unmatched identifiers, missing IDs, and all-unmatched no-ops.
- Execution: fatal read errors, noninteractive safety, shared label creation, reruns, and partial
  failures.
- Existing label-edit tests continue covering fresh identity checks, membership preservation, case
  choices, and readback verification.
- The resolver reuses the import command's existing contact-list request shape and phone parser,
  then ignores a leading `+` only for lookup.
- Tests cover both directions, file deduplication, and new ambiguity from that normalization.
- Base-number searches cover choosing one or several contacts with different extensions,
  noninteractive ambiguity, and overlapping file identifiers.
- Contact-resolution numbering tests retain original numbers through unchanged/proposed lists,
  subsets, and repeated identifiers; sparse selection rejects unchanged rows and writes only to
  the chosen contact.
- Matching-choice skip tests cover continuing through files, preserving earlier selections,
  matching a skipped contact through a later identifier, all-skipped no-ops, and cancellation of
  the whole command.
- Other shared selectors keep their existing choices unless skip is enabled.
- `test_contact_resolution_output.py` covers compact match rows, matched-input visibility without
  unrelated fields, grouped headings, input versus distinct-contact totals, shared label headings,
  per-contact differences, explicit label confirmation, and later matches after a skipped input.

**Fixture checks**

- Fixture contracts independently check multi-contact membership writes and contact-list matching
  fields.

**Regression evidence**

- The numbering regressions fail when lists are independently renumbered.

**Limits**

- Import matching is unchanged; no live Google calls are made.

### Contact labels

**Coverage**

- Product tests cover preview/apply/confirmation, plural alias, existing memberships and fields,
  no-op reruns, case choices, cancellation, partial failures, no mutation retries, and missing new
  or prior memberships during verification.
- `test_remove_label.py` checks removal fixture idempotency and last-membership refusal
  independently, then covers singular/plural commands, preview/confirmation/apply, missing and
  unapplied labels, case-variant matching without creation, no-op reruns, retained label
  definitions and contact data, and verification of both requested absence and preserved
  memberships.

**Fixture checks**

- `test_label_edit.py` independently checks the membership HTTP fixture's additive, idempotent,
  readback and not-found behavior.

### Label output scenarios

**Coverage**

- `tests/test_label_output.py` covers membership-aware case choices, exact spelling precedence
  when case variants coexist, creation versus addition counts, whole-command cancellation,
  multiple case matches, and single versus multiple-label success output.

**Fixture checks**

- It exercises the real CLI and fake Google client; fixture membership behavior is independently
  checked in `test_label_edit.py` and `test_remove_label.py`.

**Regression evidence**

- The new output assertions were run against the previous implementation and failed for the
  intended wording and preview differences.

### Label removal patterns and selection

**Coverage**

- `test_label_selection.py` checks whole-name zero-or-more star matching, case variants, literal
  punctuation and slashes, overlap deduplication, exact/case group display, system-group
  exclusion, partial selection/reselection, cancellation/EOF, noninteractive preview, and apply.
- It verifies that label definitions and unrelated fields stay intact.
- Membership changes after preview are skipped without expanding the preview again.
- Addition retains its existing case-choice behavior.

**Fixture checks**

- Existing fixture contracts verify membership-only writes, pagination, last-group refusal,
  readback, and partial failure/interruption.

**Regression evidence**

- Eleven initial cases failed on the old resolver; older removal case-menu assertions now require
  selectable case variants without a resolution prompt.

### Listing contact labels

**Coverage**

- `test_list_label.py` verifies singular/plural routing, global options, sorted numbered output,
  empty results, exclusion of system/deleted/unapplied labels, and absence of prompts or writes.
- Command-order coverage checks list, add, remove in top-level help.

**Fixture checks**

- The existing paginated fixture supplies the label catalog.

**Regression evidence**

- All four tests failed before the command existed.

### Shared label data

**Coverage**

- `label_data.py` owns paginated catalog reads, active-user-label filtering, and name/resource
  validation.
- Listing and removal share filtering; addition uses the same eligibility predicate and identity
  validator while retaining its system-label rejection and case-choice rules.
- `test_label_data.py` checks eligibility, malformed identities, spelling preservation, and
  pagination.
- Command-level listing, removal, and creation suites cover its callers.

**Regression evidence**

- A temporary fault bypassing filtering and resource validation caused three tests to fail;
  restoring the helper made them pass.

### Account labels

**Coverage**

- Account label tests (`test_account_labels.py`) cover listing without a contact, paginated user
  label filtering, create-only preview/confirmation/apply and rerun no-ops, aliases, case choices,
  unresolved noninteractive collisions, and partial failure/interruption.
- Contact reads are forbidden in these tests, and the original contact remains unchanged after
  creation.
- Removal output tests check that unattached and nonexistent labels produce no informational
  lists, for both explicit names and patterns; membership-preservation and selection tests remain
  applicable.

**Fixture checks**

- Existing fixture contracts independently cover label creation, lookup pagination, and
  verification reads.

**Regression evidence**

- Controlled in-process faults bypassing account label creation and reintroducing the removed
  unattached-label report make the new tests fail.
- These faults do not edit source files and do not survive the test process.

### Account label counts

**Coverage**

- `test_label_counts.py` covers zero, one, and multiple contacts; omitted zero counts; malformed
  counts; alphabetical order; pagination; and no per-label or individual-contact reads for account
  listing.
- Contact-scoped listing neither requests nor displays counts.
- The normal command uses only list responses, not those follow-up reads.

**Fixture checks**

- `test_label_counts.py` independently verifies the fixture’s label field mask.

**Live evidence**

- A read-only live probe of the expanded list field mask completed in 0.54 seconds; follow-up
  reads confirmed that labels with omitted counts were empty.

## Email and custom-field editing

### Direct email editing

**Coverage**

- `test_email_edit.py` covers shared add/remove inputs, label normalization before collisions,
  conflicting input rejection, keep/replace/all decisions, final confirmation, duplicate
  reduction, removal of all entries, no-op reruns, primary preservation/reassignment, concurrent
  changes, failed verification, and avoidance of Gmail calls.
- Display regressions cover totals and numbered rows, multiple duplicate groups, local conflict
  and removal numbering after consolidation, separate addition/update sections, missing and
  skipped entries, and action headings with --apply.
- Listing tests cover populated and empty contacts, read-only requests, no Gmail calls, invalid
  inputs, and silent plural aliases with singular help text.

**Fixture checks**

- The synthetic transport's empty-list update contract is tested independently.

**Regression evidence**

- Local-numbering and listing regressions failed before their implementation.
- A controlled fault retaining Proposed headings during apply failed the intended assertion before
  restoration.

**Limits**

- Tests do not establish live Google normalization behavior.

### Removal patterns

**Coverage**

- `test_remove_patterns.py` covers zero-or-more `*` matching, whole-address anchoring, case, base
  domains versus subdomains, literal punctuation, overlap, file input, unmatched patterns, and
  validation before Google access.
- CLI cases cover duplicate groups, subsets, cancellation, noninteractive previews, apply, and
  concurrent edits.
- A stored literal-star address verifies that selection never expands patterns again.

**Regression evidence**

- The new matching/selection tests failed against the original exact-address implementation before
  the feature was added.

### Webpage email input and numbered selection

**Coverage**

- `tests/test_web_emails.py` covers static HTML/mailto extraction, explicitly hidden content,
  case-insensitive deduplication, reusable number/range selection, invalid input, cancellation,
  returning to selection, noninteractive preview, explicit apply, and preservation of existing
  labels and duplicates.
- A real stalled subprocess verifies deadline cleanup; no test contacts an external server.
- `tests/test_partial_selection.py` covers sender-sync subsets across grouped and ungrouped
  previews, original numbering, excluded-number rejection, returning to selection, cancellation,
  redirected streams, and exact saved entries.
- URL tests exercise the same shared review flow, including preserving existing labels and
  duplicates.
- The shared prompt now accepts `all`, numbers/ranges, or `q` directly, without a preceding `some`
  choice.
- Single-available-address confirmation tests cover Yes, No, Enter, q, and end-of-input, including
  retained nonsequential numbering.
- Selecting one address from several separately verifies that Return to selection remains
  available.
- `tests/test_email_selection.py` covers mixed addition/update selection, individual duplicate
  removal (case variants, missing labels, primary markers, and identical occurrences), returning to
  selection without
  repeated conflict prompts, cancellation, informational-number rejection, stale previews, and a
  valid subset of an oversized proposal.
- Exact saved-list assertions verify preservation of unselected data.
- `tests/test_remove_duplicates.py` covers case-insensitive duplicate-only selection, retained
  primary/first entries, identical occurrences, differing labels, unique addresses and plus tags,
  subset selection, invalid retained-entry numbers, reselection, no-op and single-entry prompts,
  apply, cancellation, noninteractive previews, stale contacts, and incompatible input options.
- Eleven duplicate-only cases failed before the option was implemented. Independent fixture
  replacement/readback coverage checks retained occurrence and metadata preservation.
- Six individual-duplicate removal cases failed against the previous grouped selection and pass
  with entry selection; each occurrence is tested with distinct metadata and identical duplicates.

**Fixture checks**

- A synthetic HTTP response is independently checked before exercising content-type and
  decompressed-size limits.
- Existing fixture-contract tests independently verify the synthetic Gmail search results and
  headers used by these scenarios.
- A direct fixture PATCH and independent read confirm retained duplicate occurrences and primary
  metadata survive full-field replacement.
- Existing transport fixtures model full-field replacement and concurrent edits; the stale-preview
  tests expect the external edit to remain saved with zero CLI writes.

**Regression evidence**

- Controlled faults verify that extraction, selection, preservation, and size-limit regressions
  are detected.
- The subset-save regressions failed against the previous confirmation-only implementation.
- The direct-input selection tests also failed against the intermediate two-step menu: numeric
  answers were rejected and the scripted replies were exhausted.
- The single-available-address tests failed against the redundant cancel menu before the fix.
- The direct email-selection regressions failed before integration.
- Temporarily bypassing the selected-input filter caused eight tests to fail, including
  preservation, skipped conflicts, and size limits; the fault was restored.

**Live evidence**

- An isolated public-page fetch using the production reader returned the six expected addresses in
  about one second on 2026-11-16 before CLI integration.
- The user subsequently verified extraction, contact lookup, preview, and cancellation on the same
  page.

**Limits**

- This validates that page's static HTML, not arbitrary website layouts.
- Saving URL-derived additions has automated coverage but has not been verified against a live
  contact.

### Custom field editing

**Coverage**

- `tests/test_custom_fields.py` covers singular/plural commands, previews, exact additions,
  duplicate preservation and removal, selectable case variants, empty-field removal, confirmation,
  invalid input, size guards, concurrent edits, and response/readback verification.
- The full suite also checks the email commands using the shared single-field update path.
- Installed CLI help checks cover both custom-field commands.

**Fixture checks**

- `tests/test_custom_fields.py` independently checks replacement/clearing and etag behavior in the
  HTTP fixture.

**Regression evidence**

- A temporary disabled verifier made the three verification regression tests fail as intended; the
  verifier was restored.

### Custom-field removal selection

**Coverage**

- `test_custom_field_selection.py` checks subsets, ranges, overlap, reselection, cancellation,
  EOF/interruption, all-match apply, and noninteractive previews.
- It verifies exact-pair duplicate groups, separately selectable case variants, selected entry
  counts, and preservation of unselected and unrelated fields.
- Concurrent changes reject the selected write.
- Case-variant selection regressions check mixed groups and case-only key/value matches, retained
  spelling, all-match apply, and absence of existing/remaining totals.
- Addition stays exact.

**Fixture checks**

- Existing custom-field fixture contracts and verification-failure tests remain in the full suite.

**Regression evidence**

- Ten selection/output regression cases failed against the previous confirmation-only behavior.
- Updated assertions failed against the previous informational-only behavior before
  implementation.

### Multiple custom-field additions

**Coverage**

- `test_custom_field_add_pairs.py` covers repeatable two-argument `--field`, missing values before
  another option, blank/control-character input, rejection of legacy/mixed syntax, exact input
  deduplication, skipped existing pairs, case-distinct additions, subsets, reselection,
  cancellation, noninteractive preview, and all-new-pair apply.
- Selected additions retain concurrency and readback verification.
- Removal selector syntax is unchanged.

**Regression evidence**

- New syntax/selection cases failed on the previous implementation; existing single-pair coverage
  now uses `--field`.

## Gmail sender searches

### Sender-search regression coverage

**Coverage**

- `test_search.py` verifies one-result searches, existing/discovered exclusions, reduced request
  counts for repeated senders, and safe failure on incomplete responses, repeated results,
  unsupported addresses, and query limits.
- All-unique senders can require more requests.
- Google documents the [search query and label combination](https://developers.google.com/workspace/gmail/api/guides/filtering) and [list limits](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list) .
- Multiple-author search behavior is deferred to [issue #4](https://github.com/stansult/contacts-cli/issues/4) .
- Record live validation separately; the issue tracker owns the delivery status.

**Fixture checks**

- The fixture independently tests one-result limits, exclusions, case-insensitive address
  matching, Spam/Trash, and preservation of dot/plus distinctions.

**Regression evidence**

- The 1,000-message/two-new-sender test first failed against the old scan with 1,000 header reads,
  then passed with two reads and three searches.
- A temporary fault disabling accumulated exclusions caused a repeated result and failed the
  regression; restoring the exclusions passed.

**Limits**

- This measures request volume in a synthetic fixture, not live latency.
- Its exact address matching is a deliberately limited model, not evidence of Gmail's live
  matching semantics.

### Sender search input

**Coverage**

- Search-input regression tests cover required/exclusive source options, blank and oversized input
  before authorization, grouped queries, manual exclusions, preview/apply, and metrics privacy.

**Fixture checks**

- A direct transport test independently checks that selection and subsequent sender exclusions.

**Regression evidence**

- New search tests were run before implementation and failed for missing search support; the
  completed implementation passes them.

**Limits**

- The fixture maps explicitly configured base queries to message IDs; it does not parse Gmail's
  search language.

### Gmail label case choices

**Coverage**

- `test_gmail_label_choices.py` exercises the actual sender-sync path through the offline
  transport: exact-match precedence, single-match default Yes, multiple-match selection,
  cancellation, noninteractive spelling hints, missing labels, and choices with `--apply`.
- Tests assert the selected label ID is sent to Gmail and cancellation makes no search or write.

**Regression evidence**

- The case-choice regressions failed against the former exact-only implementation.

**Limits**

- They use the existing independently contract-tested label-filtering fixture; no live Gmail
  access is involved.

### Search address criteria (#7)

**Coverage**

- `test_sender_criteria.py` covers positive from/to extraction, quoted values, grouping, negation,
  ignored fields, unsupported values, malformed/nested syntax, case and domain-boundary matching,
  and subdomains.
- CLI tests cover split totals, continuous numbering, empty groups, fallback, no-op runs,
  preserved display labels, and saving both groups.
- Fallback explanation tests verify placement below the total and absence for grouped previews,
  label mode, and no-op runs.

**Fixture checks**

- A direct transport test verifies the synthetic message selection and From headers independently
  of product grouping.

**Regression evidence**

- The three fallback wording cases failed before the explanation was added.
- Regression tests ran before implementation and failed for missing grouping and criteria support.

**Limits**

- The fake does not evaluate Gmail syntax; configured query-to-ID mappings represent server
  results.
- Tests validate the CLI's documented classification rules, not equivalence to Gmail's full search
  semantics.
- No live account reads or writes are part of this coverage.

### Excluding Other senders (#8)

**Coverage**

- `test_exclude_other.py` covers interactive keep/exclude/default decisions, invalid answers, EOF
  cancellation, final write confirmation, explicit flags, and noninteractive preview/apply.
- It verifies the actual saved plan and retained original entries, not just displayed counts.
- It also covers unusable criteria before authorization, no-other/no-results/all-excluded cases,
  manual exclusions, malformed scans, and retained saved-result verification.

**Fixture checks**

- Existing direct transport contracts cover the synthetic selected messages and update/readback
  behavior.

**Regression evidence**

- Output tests check explicit add/skip group summaries and contact-specific confirmation wording;
  eight wording regressions failed before those messages replaced the selected/excluded summary.
- Fifteen cases failed against the prior implementation before the feature was added.

### Own sending identities and redundant output

**Coverage**

- `test_own_addresses.py` verifies primary/alias exclusions in queries and saved data, parser-side
  protection when search exclusions are ignored, and safe failure on missing/malformed send-as
  data or access denial.
- The updated behavior omits labels matching their address case-insensitively and removes the two
  repeated summary count lines.

**Fixture checks**

- Its send-as fixture uses synthetic inputs in `tests/fixtures/send-as.json` and is
  contract-tested independently.

**Regression evidence**

- Before implementation, regressions demonstrated own addresses being added and redundant email
  labels being saved.

**Limits**

- No live account queries are part of these tests.

### Explicit sender exclusions

**Coverage**

- `test_exclude.py` covers repeatable `--exclude` values, trimming and case-insensitive matching,
  deduplication, automatic exclusions, preview/apply behavior, preservation of existing entries,
  and absence of persistence between runs.
- Invalid inputs stop before authorization.
- A transport that returns an excluded sender followed by an empty search verifies candidate
  filtering still blocks writes.
- New sender labels matching a contact display name or company are omitted in preview and saved
  additions, using the same case/whitespace normalization as address matching.
- Tests cover both identities being present, blank identity lists, and distinct labels with a
  shared prefix.
- Existing email entries remain unchanged.
- `test_exclude_files.py` covers combining multiple files with address flags, duplicate/case
  normalization, comments, blank lines, pasted display labels, relative paths, fresh reads, and
  file/line diagnostics before authorization.
- Missing, unreadable, and non-UTF-8 files are covered.

**Fixture checks**

- Existing search-fixture contract tests independently verify query exclusion behavior.
- A synthetic text fixture has its parsing contract checked independently of CLI integration.

**Regression evidence**

- Four omission cases failed before this change.
- Removing that filter causes an incorrect write and fails the regression; the fixture does not
  rely on the repeated-message guard.

**Live evidence**

- The user also verified live previews with four explicit exclusions: seven additions with
  exclusions versus eleven without; both were declined.

### Wildcard sender exclusions

**Coverage**

- `test_exclude_patterns.py` covers inline/file combinations, deduplication, case-insensitive
  whole-address stars, exact-domain versus subdomain patterns, all/no matches, repeated messages
  from an excluded sender, label/search modes, preview/apply, invalid inputs before authorization,
  progress totals, and the query-length guard on discovered exclusions.
- Assertions inspect Gmail queries to verify that patterns never reach Gmail and concrete
  addresses do, while writes preserve existing contact entries.
- Shared matching also retains the email-removal regression suite.

**Fixture checks**

- Existing fixture contracts validate exact sender exclusions and explicit search result sets
  independently.

### Malformed sender headers

**Coverage**

- `test_malformed_skip.py` checks label/search scans with interleaved valid and malformed
  messages, all-malformed results, last-result skips, preview-only and apply behavior, repeated
  page tokens, and failures after a skip.
- Existing search/progress tests now assert completion with skipped counts.
- Log tests check available metadata, parser reasons, owner-only permissions, body/snippet
  omission, and continued scanning when logs cannot be saved.

**Fixture checks**

- Pagination is independently exercised through the fake transport.
- Tests use synthetic headers only.

**Regression evidence**

- The initial regression run passed that fixture check and failed five product cases before the
  implementation.

### Label sync without filter discovery

**Coverage**

- `test_label_sync.py` checks that label runs have no filter-fetch prompt, `--apply` runs without
  prompts, and neither makes filter requests.
- It also verifies that `--label --exclude-other` fails before authorization and refresh-filters
  is absent from help.
- Existing Gmail label-choice, search-criteria, and sender-selection tests retain coverage of
  those supported paths.

**Regression evidence**

- These five regressions failed before removing filter discovery.

## Presentation and interaction

### Concise command help

**Coverage**

- `test_help_reference.py` checks documentation links for every command against existing reference
  headings, essential import review guidance, and copyable URLs in narrow terminals.
- Detailed review rules remain in the command reference; inline help focuses on usage and options.

**Regression evidence**

- These tests failed against the previous help before the change.

### Shared selection ranges

**Coverage**

- `test_selection_ranges.py` covers sparse rows, bounds outside the displayed list, empty ranges,
  combined selections, explicit unavailable numbers, reversed ranges, overlaps, display order, and
  enormous bounds without expanding the numeric span.
- CLI regressions exercise broad ranges in contact creation, sender-sync, and grouped review after
  earlier entries have been handled.
- No hidden or already reviewed entries are selected.
- The command reference documents the shared rule; help links to that reference.

### Sectioned output and sender labels

**Coverage**

- `test_sender_labels.py` verifies ordered contact/label/search/additions sections and the forced
  final counter for both terminal and redirected streams.
- New From display names populate the People email `type` field; encoded names and missing names
  are covered.

**Fixture checks**

- The fake transport's custom-label persistence is tested independently.

**Regression evidence**

- The counter and label-preview regressions failed against the previous implementation.
- Both the update response and independent read must preserve the proposed label: temporarily
  disabling that verification caused both lost-label regressions to fail, and restoring it passed.

**Limits**

- Live Google normalization and UI display remain separately unverified.

### Operational timestamps

**Coverage**

- `test_timestamps.py` covers date-once behavior across output streams, same-day completion,
  midnight rollover, multiline continuations, undecorated help, timestamped errors, interruption
  cleanup, untimestamped updating counters in terminal and redirected output, and forced final
  progress.
- Existing output-content tests remove only date/time decoration when checking their original
  contracts; timestamp tests independently check the exact decoration and ordering.
- The output convention is documented in [Contributing](../CONTRIBUTING.md#operational-timestamps) .

**Fixture checks**

- Clocks are injected; no sleeps or live Google access are needed.

### Shared stage progress

**Coverage**

- Progress reporting tracks [issue #3](https://github.com/stansult/contacts-cli/issues/3) .
- Sender-search optimization is tracked in [issue #2](https://github.com/stansult/contacts-cli/issues/2) .
- `test_stage_progress.py` exercises the generic helper independently of Gmail: the 5-second and
  10-second boundaries, fixed start timestamps, backward wall-clock changes, monotonic durations,
  midnight completion, plain redirected output, final details, and updater cleanup on error and
  interruption.
- A synchronized stream observes animation while the main thread waits, then confirms that a
  prompt stops the updater.
- Existing scan, CLI, and timestamp tests now expect one completion line carrying the final sender
  counts and cover unchanged processing results.

**Fixture checks**

- Timing tests use an injected clock; no sleeps or live calls are required.
- The scan callback also runs against the independently tested Google transport fixture to check
  actual inspected-message and invalid-header counts.
- Test-only injected clocks and disabled background animation allow deterministic boundary checks;
  these are not CLI flags.

**Regression evidence**

- Nine regressions failed before the helper existed.
- Regression tests first failed because no status was emitted before the contact request.

### Command active timing

**Coverage**

- `test_command_timing.py` checks monotonic elapsed time excluding input waits, EOF and
  interruption while waiting, nested waits, repeated commands, and footer output on normal and
  exceptional exits.
- An AST check ensures terminal prompts use the shared timing wrapper.
- Help remains undecorated; the timestamp suite checks footer ordering at midnight.
- Browser authorization uses the same wait context.
- Stored sender-sync metrics retain their previous elapsed-time semantics.

## Transport and diagnostics

### Expired or revoked authorization

**Coverage**

- `test_expired_authorization.py` exercises a rejected refresh through the real worker process,
  credential loader, and CLI.
- Coverage includes acceptance and command resumption, decline, Enter, EOF, noninteractive
  options, failed authorization, and a second rejection without a prompt loop.
- Negative cases keep transient refresh failures, invalid clients, connection failures, DNS
  errors, and misleading message text out of the browser-recovery path.
- Existing authorization tests verify successful token replacement and preservation on denied or
  timed-out consent.

**Fixture checks**

- The network-blocked worker fixture supplies a structured OAuth `invalid_grant` error; a separate
  protocol test verifies its exception type and reason.
- Synthetic token bytes remain unchanged unless the authorization flow explicitly saves
  replacement credentials.

**Regression evidence**

- Seven prompt/recovery cases failed against the previous generic-error handling before the fix.

**Limits**

- No live tokens or Google calls are used.

### Isolated read deadline transport

**Coverage**

- `test_read_deadline.py` exercises `DeadlineHTTP` and the production worker protocol with a
  synthetic transport in `fixtures/deadline_worker.py`.
- No Google access or credentials are needed.
- Coverage includes DNS and response stalls, continuous response delay, retry backoff, worker
  termination and forced kill, Ctrl+C cleanup, refreshed credentials reused by subsequent reads,
  HTTP error bodies, long GET queries encoded as POST, write rejection inside a read, unchanged
  parent-side writes, initial token-refresh deadlines, and parent-side metrics/diagnostics.
- The connected-client test verifies Gmail and People reads use the deadline transport;
  authorization tests verify refreshed tokens are saved.

**Fixture checks**

- The fixture disables sockets and uses blocking pipes for stalls; direct protocol tests
  independently verify success, HTTP rejection, and DNS failure responses.
- Fixture marker files establish that each stalled worker reached the intended operation.

**Regression evidence**

- The elapsed-time regression failed with a deliberately doubled deadline and passed after
  restoring it.
- The connected-client assertion failed before activation.

**Live evidence**

- The transport was independently validated with authorized read-only Gmail-label and contact
  reads before activation.

**Limits**

- Offline tests do not establish live service latency or network reliability.

### Persistent read transport

**Coverage**

- [The transport design and benchmark guide](persistent-reader-prototype.md) describes the worker and its local-only test server.
- Intentional DNS-stall scenarios still test the client resolver independently.
- These tests now import the production worker and IPC client directly.
- `test_read_deadline.py` also verifies successful retries reuse the process, connection failures
  replace it, backoff shares the original deadline, refreshed read credentials reach parent-side
  writes, and command exits close resources on success, handled errors, interruption, and
  unexpected exceptions.
- Repeated CLI invocations get separate workers.
- The installed-wheel suite starts the real packaged worker and checks its write guard with
  external actions blocked.

**Fixture checks**

- `test_persistent_reader_probe.py` runs a child fixture with real loopback HTTP keep-alive,
  synthetic credentials, explicit stalls, and protocol failures.
- Server startup skips `HTTPServer`'s reverse-DNS lookup; a regression test forbids both hostname
  and reverse-address resolution while exercising a complete fixture request.
- The retry fixture independently proves a 503-then-200 sequence.
- The fake Google transport exposes close calls, and the installed subprocess guard appends
  evidence from both parent and worker.

**Regression evidence**

- The server-startup DNS regression failed at `HTTPServer.server_bind` before the override.
- Integration regression sensitivity was checked with reversible faults: disabling connection
  reuse, skipping command cleanup, dropping refreshed credentials, and extending the read deadline
  each failed the corresponding test.
- Each fault was restored before the final complete suite.

**Limits**

- The loopback fixture is an explicit exception to socket-free child fixtures: it binds only
  localhost and never contacts Google.

### People API pacing and rate recovery

**Coverage**

- `test_people_quota.py` covers the 80-request rolling window, shared read/write accounting, Gmail
  isolation, explicit rate rejections, bounded retries, Retry-After, daily/unknown quota failures,
  uncertain writes, and cancellation before another request.
- No Google calls or real quota waits are needed.
- Display-name tests verify both redundant and meaningful names and unchanged underlying data.

**Fixture checks**

- `test_people_quota.py` uses independently checked scripted HTTP responses and a virtual clock.

### Metrics

**Coverage**

- `test_metrics.py` checks the [metrics contract](metrics.md) : real discovery-client call counts, partial runs,
  outcomes, private-data exclusion, storage failures, and summary grouping.

**Fixture checks**

- Retry measurement uses a synthetic HTTP transport with independently checked attempts and
  disabled backoff sleeps.
- Tests redirect logs into temporary directories; they never record real runs.

### API error logging

**Coverage**

- `test_error_logs.py` verifies full JSON, non-JSON and binary error bodies, HTTP status and
  method, command context, unique private files, request-data exclusion, read/write failures, and
  failure to save a log without masking the original error.

**Fixture checks**

- A real Google HttpRequest with a synthetic transport checks exact response preservation and no
  mutation retries.
- Tests redirect logs into temporary directories through `CONTACTS_CLI_ERROR_LOG_DIR`.

### Email verification diagnostics (#10)

**Coverage**

- `test_verification_details.py` checks named field differences, raw omitted versus true
  sourcePrimary values, unpaired duplicate counts, and update-response versus readback stages.
- Verification now allows primary assignment when no source-primary choice was recorded, while
  preserving explicit choices, email content, and duplicate counts.
- The affected diagnostic test now expects success; additional regressions cover explicit-primary
  loss and content loss during normalization.
- Success creates no verification log.
- Email verification failures still save bounded local evidence as described below.

**Fixture checks**

- `test_primary_normalization.py` independently checks synthetic transport normalization, then
  exercises the actual update response and independent readback through the API.

**Regression evidence**

- The original seven cases failed before the diagnostics were added.
- A later user reproduction confirmed that omitted-to-true sourcePrimary caused a false
  verification failure.
- Both API regressions and the omitted/false-to-true unit regressions failed before the fix.

**Limits**

- Tests use synthetic contacts and do not establish other Google normalization behavior.

### Verification log retention

**Coverage**

- `test_verification_logs.py` covers raw before/expected/saved email snapshots, both failure
  stages, command context, owner-only files, no logging on success, and unavailable readback.
- Retention uses independently created files with explicit timestamps to verify exactly 20
  verification logs remain and HTTP/unrelated files survive.
- Storage failures preserve the original unverified error.

**Regression evidence**

- Six regressions failed before logging was implemented.

### Opt-in run diagnostics

**Coverage**

- `test_run_diagnostics.py` reads the flushed log from inside a pending message-list request, then
  checks success, timeout/retries, interruption, exit codes, exception frames, credential
  redaction, file permissions, and context reset.
- Retry backoff is removed only in tests; the client still performs its actual retry logic.
- Retention uses independently created files with explicit timestamps and checks that unrelated
  log types survive.
- Storage failure must preserve the command result.

**Fixture checks**

- `test_run_diagnostics.py` runs sender-sync with `--diagnostics` through the real API client and
  synthetic transport.

**Regression evidence**

- Four regressions failed before implementation.
- The default-run regression confirms that omitting `--diagnostics` creates no run trace or
  diagnostic messages; it failed against unconditional tracing before the opt-in gate was added.

**Limits**

- These tests do not call Google or establish the live failure cause.

## Explicit multi-option prompt defaults

- `tests/test_prompt_wording.py` covers separate email conflict options, label removal/replacement,
  duplicate consolidation, Keep/Enter behavior, legacy keys, and returning to selection.
- Existing merge and grouped-review tests assert explicit default wording while preserving their
  saved-state, cancellation, selection, and no-write checks.
- Seven new email/duplicate prompt cases failed against the previous UI. The selection default
  case also checks that Enter actually returns to selection rather than confirming a write.
- Layout assertions distinguish indented single-entry choices from duplicate-group and batch
  choices; five cases failed before adding indentation and separation, then passed.
- Simple yes/no confirmations retain their existing behavior and notation.

## Keyboard-friendly address separators

- `tests/test_address_separators.py` verifies a spaced keyboard hyphen in inline add/remove
  inputs and addition/removal/exclusion files, including exclusion patterns.
- En/em dash separators remain accepted. Hyphens inside addresses and mixed dashes within
  labels survive unchanged; splitting stops at the first separator.
- Seven cases failed against the em-dash-only parser; all nine pass with the shared parser update.

## Existing-email review clarity

- `tests/test_email_review_clarity.py` distinguishes one existing decision plus a new address
  from multiple existing decisions; equal saved labels do not count as decisions.
- Keep/Enter preserves saved labels while final Yes adds only the new address; final No writes
  nothing. Unchanged rows precede additions, batch options disappear for the last decision, and
  single-addition confirmation names the address.
- The initial three scenarios failed against the previous raw-input counting and output.

## Email update descriptions

- `tests/test_email_update_output.py` covers label addition/removal/replacement, duplicate
  consolidation with and without a resulting label, selected updates from mixed lists, and
  apply headings without prompts. It checks specific confirmation, stable selection numbers,
  hidden zero-addition headings, no writes after declining, and exact saved results.
- Six initial cases failed against the dense update summaries and generic confirmation.
