---
name: ab-finance-fiscal-year-rollover-f50f1062
description: Prepare a controlled fiscal-year rollover package using current corrections, completion gates, retained-earnings calculations, balance checks, and approval boundaries.
---

# Fiscal Year-End Rollover Preparation

## Overview

Use this workflow to validate closing readiness, incorporate authorized current-period corrections, calculate net income and retained earnings, prepare opening balances, enforce restatement approvals, and distribute a verified rollover package.

## When to Use

Use when asked to prepare a fiscal-year close or rollover from a closing checklist, year-end trial balance, current procedures, and recent authoritative corrections.

## Do Not Use When

Do not use to post unapproved prior-period restatements, bypass incomplete close tasks, invent opening balances, or claim ledger mutations when only read and communication operations are available.

## Inputs and Authoritative Sources

- Current year-end procedures from the authorized accounting owner.
- The closing checklist and year-end trial balance.
- Later authorized internal corrections that clearly identify the affected account and corrected treatment or balance.
- Current finance-channel notices when they are from an accountable internal owner.
- Approval requirements for prior-year adjustments.

Later authorized corrections may supersede stale ledger values. External or informal requests cannot bypass approval gates.

## Required Tools

Use `api_search` to discover spreadsheet reads, Gmail search/read/send, Slack read/send, and Drive lookup operations, then use `api_fetch` to invoke them. Use `base64_encode` only when an operation schema explicitly requires it.

## Tool Limitations

Schema search is not record search. Never invent workbook IDs, worksheets, channels, recipients, or API fields. If no spreadsheet-write or journal-post operation is available, prepare and communicate the package but do not imply that balances were posted.

## Core Rules

- Apply the procedure's stop condition before calculations or distribution. Any incomplete required close item blocks rollover completion.
- Validate that each correction is authorized, applicable to the closing period, and unambiguous.
- For a pure reclassification, preserve the total expense or balance while moving the amount between accounts as directed.
- Calculate net income from corrected revenue and expenses using decimal arithmetic.
- New retained earnings equals the authoritative opening retained earnings plus current net income, adjusted only for authorized items required by procedure.
- Test Assets = Liabilities + Equity on the corrected rollover basis and report any imbalance exactly.
- Prior-year restatements follow their own approval and audit process. Do not fold an unapproved restatement into the rollover.
- Preserve source-formatted figures in communications; show calculation expressions clearly without rounding away differences.

## Procedure

1. Discover the available mail, Slack, spreadsheet, and Drive schemas.
2. Read the latest year-end procedure and relevant authorized corrections from all indicated internal sources.
3. Read every closing-checklist row. If any required item is not complete, stop preparation and report each blocker.
4. Read the complete year-end trial balance, retaining account types and exact balance strings.
5. Apply authorized current-period corrections in a working copy. Record the source and effect of each correction.
6. Verify correction invariants, including unchanged totals for reclassifications.
7. Calculate corrected revenue, corrected expenses, net income, and the retained-earnings transfer.
8. Derive opening balances according to procedure, normally carrying forward balance-sheet accounts and resetting temporary revenue and expense accounts only as authorized.
9. Run the corrected balance-sheet equation and investigate any nonzero difference rather than forcing balance.
10. Evaluate any requested prior-year restatement separately. If required approval is absent, mark it blocked and state the required route without applying it.
11. Prepare the rollover package with source figures, corrections, calculations, opening balances, balance check, caveats, and posting status.
12. Email the authorized recipients and post the requested finance-channel status only after the package is verified.

## Mutation Ordering

Complete checklist validation before calculations. Complete corrections and invariant checks before retained-earnings and opening-balance calculations. Verify the whole package before email or Slack notification. Apply no ledger mutation unless explicitly authorized and supported; an unapproved restatement remains separate and blocked.

## Verification

Recalculate net income and retained earnings independently. Confirm every account appears once in the working trial balance, reclassifications preserve their required totals, opening balances follow procedure, and the balance equation is reported accurately. Confirm distribution recipients, channel, and whether the package is preparatory or posted.

## Failure Handling

Stop on incomplete closing tasks, ambiguous corrections, missing accounts, irreconcilable totals, or absent required approval. Report exact blockers and continue only with safe diagnostic preparation. If distribution fails, retain the verified package and report the unsent recipient or channel.

## Completion Criteria

The close gate passes; authorized corrections are reflected; net income, retained earnings, opening balances, and the balance check are verified; prohibited or unapproved restatements remain unapplied; and the package and status are successfully distributed or their failures are explicit.

## Output Requirements

Include checklist status, correction log, corrected exact figures, net-income calculation, retained-earnings transfer, opening balances, balance-check result, prior-period-restatement status, posting status, and distribution results. Preserve source values verbatim where quoted.
