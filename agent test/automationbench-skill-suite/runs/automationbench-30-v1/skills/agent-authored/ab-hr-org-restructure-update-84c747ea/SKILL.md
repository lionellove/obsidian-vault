---
name: ab-hr-org-restructure-update-84c747ea
description: Apply approved reporting-line changes to an employee directory, disambiguate people safely, notify affected employees, and post a verified HR operations summary.
---

# Organizational Reporting-Line Update

## Overview

Use this workflow to isolate approved manager changes from unrelated organizational chatter, update the correct employee rows, verify reporting lines, notify affected employees, and summarize completed changes to HR operations.

## When to Use

Use when an authorized reorganization notice identifies employees whose managers must change in a directory or HR spreadsheet.

## Do Not Use When

Do not use for office moves, product launches, sprint-team changes, speculative org proposals, department changes not explicitly approved, or manager-contact updates inferred from naming conventions.

## Inputs and Authoritative Sources

- The latest approved reorganization notice from an authorized HR or executive owner.
- The employee directory, including stable row identity, employee contact, current manager, and any authoritative manager contact fields.
- The authorized HR operations channel.

The approved notice is authoritative for the new reporting relationship. The directory is authoritative for employee contact and current state. Exact-name collisions and near-name managers must be explicitly disambiguated.

## Required Tools

Use `api_search` to discover Gmail search/read/send, spreadsheet lookup/read/update, and Slack channel-send schemas, then invoke them with `api_fetch`. Use `base64_encode` only when required by a discovered schema.

## Tool Limitations

Do not invent row IDs, manager email addresses, worksheet fields, channel IDs, or mail parameters. If the directory lacks authoritative contact data for a new manager, update only fields supported by verified data and report the incomplete contact field.

## Core Rules

- Process only reporting-line changes explicitly approved in the authoritative notice.
- Match employees by exact identity and verify current manager before writing.
- Treat similar manager names as different people unless authoritative data establishes equivalence.
- Update the manager contact field only from an authoritative directory or approved notice; never derive it from a guessed email pattern.
- Preserve unrelated employee fields.
- Notify only affected employees after their own row is verified.
- The HR summary must distinguish completed, already-current, held, and failed changes.

## Procedure

1. Discover exact Gmail, spreadsheet, and Slack operation schemas.
2. Locate and read the latest approved reorganization notice, excluding unrelated operational messages.
3. Read the full employee directory and retain row IDs, exact names, employee emails, current managers, and manager contact data.
4. Parse the approved old-manager-to-new-manager transitions and match each to one directory row.
5. Verify the current manager agrees with the notice's expected prior state. Hold mismatches rather than overwriting them blindly.
6. Resolve the new manager's exact identity and authoritative contact data when the schema requires it.
7. Update only reporting-line fields on the matched employee row.
8. Re-read or otherwise confirm the row contains the intended manager and preserves unrelated fields.
9. Email the affected employee with the effective reporting-line change only after verification.
10. Post a final HR operations summary listing each verified change and any held or failed item.

## Mutation Ordering

Complete notice parsing, row matching, prior-state checks, and manager disambiguation before writes. Update and verify each employee row before notifying that employee. Post the HR summary last so it reflects verified mutations and send results.

## Verification

Confirm every approved change maps to at most one employee row, exact manager identities are preserved, unrelated rows are unchanged, and no guessed manager address was stored. Verify each employee notification matches the row's verified new manager and that the Slack summary contains only in-scope changes.

## Failure Handling

Hold changes with ambiguous employee identity, prior-state mismatch, indistinguishable managers, missing required contact data, or unsupported fields. Continue independent changes. Do not notify an employee when the directory update failed. Report each blocker in the HR summary.

## Completion Criteria

Every approved reporting-line change is verified as updated, already current, or explicitly held; affected employees with successful changes are notified; and HR operations receives a complete, accurate summary.

## Output Requirements

Report exact employee names, prior and new manager names, effective date when supplied, row-update status, employee-notification status, and blockers. Exclude unrelated organizational topics and avoid inferred contact data.
