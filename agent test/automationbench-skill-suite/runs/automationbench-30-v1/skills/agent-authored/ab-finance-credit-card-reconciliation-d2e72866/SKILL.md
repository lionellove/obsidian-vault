---
name: ab-finance-credit-card-reconciliation-d2e72866
description: Reconcile corporate-card statement charges to submitted expenses, flag exceptions, notify cardholders about missing receipts, and send an exact controller summary.
---

# Corporate Card Reconciliation

## Overview

Use this workflow to match statement charges to employee submissions, distinguish excluded or personal items, identify unmatched charges and missing receipts, update supported tracker fields, and communicate exact monetary values.

## When to Use

Use for a defined card-statement period when statement charges and submitted expenses are available in a spreadsheet or related tracker.

## Do Not Use When

Do not use to approve reimbursement, dispute charges with the issuer, infer card ownership from names alone, or treat an employee submission marked as personal or excluded as a valid business match.

## Inputs and Authoritative Sources

- The requested statement period.
- The statement worksheet as the authoritative charge population.
- The submitted-expense worksheet or tracker, including employee, contact, amount, date, receipt, description, and notes.
- Current reconciliation rules or explicit exclusion notes.

Preserve source display strings for dates and amounts. Use parsed decimal values only for matching and calculations.

## Required Tools

Use `api_search` to discover spreadsheet lookup/read/update and Gmail send operations, then use `api_fetch` to invoke them. Use Drive lookup only when needed to find a referenced workbook. Use `base64_encode` only if required by the discovered schema.

## Tool Limitations

Do not invent worksheet IDs, row IDs, columns, update fields, or email schemas. If the tracker has no supported exception field, do not overwrite unrelated cells; report unmatched items in the summary instead.

## Core Rules

- Reconcile from statement charge to submission so every charge receives a disposition.
- Match using a defensible combination of cardholder/card identifier, exact amount, date, and merchant or description compatibility.
- Enforce one-to-one matching unless source data explicitly supports split or aggregated expenses.
- Honor exclusion and personal-expense notes before matching.
- An unmatched charge and a missing receipt are different exceptions; a charge can have one or both only when evidence supports it.
- Copy source monetary values verbatim in emails and records; do not round or normalize their display.

## Procedure

1. Discover and inspect the exact spreadsheet and mail operation schemas.
2. Locate the statement and submitted-expense sources and read the entire in-scope period.
3. Normalize values in memory for matching while retaining each source's original strings and row identifiers.
4. Exclude submissions explicitly marked personal, erroneous, canceled, or otherwise out of reconciliation scope.
5. Generate candidate matches by cardholder/card identity, amount, date, and merchant/description; resolve only unique, well-supported matches.
6. Classify each statement charge as matched, unmatched, or ambiguous. Separately identify submitted business expenses whose receipt field is missing according to source semantics.
7. Update tracker status or flag fields only where supported, preserving unrelated cells.
8. Verify each updated row.
9. Email each affected cardholder a consolidated, privacy-safe list of their own missing-receipt items using exact dates and amounts.
10. Email the controller a reconciliation summary covering totals and exception detail with exact source values.

## Mutation Ordering

Complete the full match analysis before writing. Apply and verify tracker flags before sending cardholder notices. Send the controller summary after all writes and cardholder-send results are known.

## Verification

Confirm no statement row is omitted or matched more than once, no excluded submission was used, and ambiguous matches remain unresolved. Reconcile counts and exact amount totals across matched, unmatched, and total statement populations. Confirm notices went only to the correct cardholders.

## Failure Handling

Do not guess on ambiguous card ownership, duplicate amounts, or weak description matches. Leave those charges unmatched with a clear reason. Continue independent rows. If an update is unsupported, retain the exception in the report. If email fails, report the recipient and affected items without claiming notification succeeded.

## Completion Criteria

Every in-scope statement charge is classified; supported flags are verified; missing-receipt cardholders are notified; excluded submissions remain excluded; and the controller receives a complete, exact reconciliation summary.

## Output Requirements

Report statement count and amount, matched count and amount, unmatched count and exact amounts, ambiguous items, missing-receipt notices, and any update or send failures. Preserve source values verbatim in notifications.
