---
name: ab-finance-vendor-statement-reconciliation-75e58482
description: Compare vendor statements with internal AP balances, honor exclusions, contact vendors about unresolved differences, and provide an exact reconciliation summary.
---

# Vendor Statement Reconciliation

## Overview

This workflow reconciles external vendor statement balances against internal accounts-payable records, isolates genuine unresolved differences, contacts only affected vendors, and summarizes exact balances for the controller.

## When to Use

Use when a vendor-statement population and corresponding internal AP balances are available for the same reconciliation date or period.

## Do Not Use When

Do not use to post journal entries, promise payment, accept a vendor's balance without comparison, or contact vendors whose accounts reconcile or are explicitly excluded from the current reconciliation.

## Inputs and Authoritative Sources

- Vendor statement rows for vendor identity, contact address, and statement balance.
- Internal AP rows for the comparable AP balance and internal notes.
- Current reconciliation policy, cutoff date, and documented exclusions such as payments in transit.

The external statement is authoritative for the claimed vendor balance; internal AP is authoritative for the booked balance and documented internal exceptions. Neither silently overrides the other.

## Required Tools

Discover spreadsheet lookup/read and Gmail send operations with `api_search`; invoke them using `api_fetch`. Use Drive lookup only to locate a referenced workbook. Use `base64_encode` only when the discovered schema requires it.

## Tool Limitations

Do not guess spreadsheet, worksheet, row, or mail parameters. If transaction-level detail is unavailable, describe the result as a balance discrepancy rather than inventing missing invoices or payments.

## Core Rules

- Compare records only after resolving vendor identity and ensuring balances share the same period and currency.
- Honor explicit, applicable exclusion notes and explain them in the controller summary.
- Parse balances as decimals for comparison but preserve the original source strings in messages.
- Calculate and label the direction of each difference consistently; state which balance is higher.
- Email only vendors with unresolved discrepancies, using the contact tied to that vendor row.
- Do not disclose other vendors' balances.

## Procedure

1. Discover and inspect the spreadsheet and Gmail operation schemas.
2. Locate both worksheets and read all in-scope statement and AP rows.
3. Retain exact vendor names, emails, balance strings, row IDs, notes, and any period or currency fields.
4. Match vendor rows using stable identifiers when present, otherwise careful normalized name matching with ambiguity checks.
5. Apply documented exclusions only when they clearly pertain to the current reconciliation.
6. Compare matched balances and classify each vendor as reconciled, unresolved discrepancy, excluded with reason, missing internal record, missing statement, or ambiguous identity.
7. For each unresolved vendor, compute the exact difference and prepare a vendor-specific email containing only that vendor's statement balance, AP balance, direction, and requested follow-up.
8. Send vendor emails and capture send results.
9. Send the controller a full summary with exact balances, differences, exclusions, unmatched records, and vendor-notification status.

## Mutation Ordering

Complete matching, exclusions, and calculations before any email. Send vendor-specific messages first so their results can be included accurately in the controller summary. No source record should be altered unless the user separately authorizes it and a supported operation exists.

## Verification

Confirm each source row participates in at most one vendor match, equal balances are not emailed as discrepancies, difference direction is correct, exclusions are supported by source notes, and each vendor email uses the correct contact. Recalculate all summary counts and amounts.

## Failure Handling

Do not guess ambiguous vendor matches, currencies, cutoff periods, or undocumented exclusions. Report them for review. Continue independent vendors. If a vendor send fails, include that failure in the controller summary and do not claim the vendor was contacted.

## Completion Criteria

All statement and AP rows are accounted for, unresolved discrepancies are accurately calculated, affected vendors are contacted where possible, and the controller receives the complete reconciliation with exact values and send status.

## Output Requirements

Report counts for reconciled, unresolved, excluded, unmatched, and ambiguous vendors. For discrepancies, preserve vendor names and source-formatted statement balance, AP balance, and calculated difference without paraphrasing or rounding.
