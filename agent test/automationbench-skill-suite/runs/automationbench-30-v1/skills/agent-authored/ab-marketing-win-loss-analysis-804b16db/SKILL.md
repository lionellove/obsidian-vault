---
name: ab-marketing-win-loss-analysis-804b16db
description: >-
  Analyze governed win/loss data for the required reporting period, deal types,
  and value threshold; calculate win rate and reason patterns, then email the
  authorized audience with a tracking code. Use for competitive sales reporting.
---

# Produce a Governed Win/Loss Analysis

## Overview

Retrieve current reporting rules, filter source rows to qualifying competitive wins and losses in the required period, calculate count and value metrics, summarize reason patterns rather than individual deals, and send the report in the mandated format and distribution.

## When to Use

Use when a deal worksheet must produce a period-specific win/loss report under current exclusions, minimum-value rules, tracking, and recipient requirements.

## Do Not Use When

Do not include pending, disqualified, internal, renewal, referral, pilot, malformed, out-of-period, or otherwise noncompetitive rows unless current authoritative policy explicitly includes them.

## Inputs and Authoritative Sources

- Treat the win/loss worksheet as authoritative for deal outcome, reason, value, close date, and notes.
- Treat the latest authorized internal reporting communication as authoritative for period, minimum value, tracking code, recipient, and report focus.
- Resolve conflicts in older templates or informal requests by authority, recency, specificity, and explicit policy scope.
- Treat the runtime date as the anchor for relative periods such as last month.

## Required Tools

- Use `google_sheets_get_many_rows` for deal data.
- Use `gmail_find_email`, `gmail_list_emails`, and `gmail_get_email_by_id` to retrieve reporting requirements and conflicting guidance.
- Use `gmail_send_email` for final distribution.
- Discover exact schemas with `api_search` and call them through `api_fetch`.

## Tool Limitations

- Notes and outcomes must be interpreted from source rows; no external deal-validation service is available.
- Gmail search can surface informal requests that are not authoritative policy.
- No spreadsheet write is required or supported by this analysis workflow.
- A sent payload is not proof of delivery without Gmail success evidence.

## Core Rules

- Retrieve current reporting requirements before filtering data.
- Convert the required reporting period into inclusive start and end dates and require a valid close date within that range.
- Include only recognized won and lost outcomes that represent direct competitive deals.
- Apply the current minimum-value boundary exactly after parsing the source amount.
- Respect source notes and policy exclusions for internal programs, renewals, referrals, fraudulent inquiries, and other noncompetitive records.
- Calculate `win rate = wins / (wins + losses) × 100`; never include other outcomes in the denominator.
- Aggregate primary reasons separately by outcome and emphasize patterns rather than naming individual deals.
- Include relevant aggregate amounts while preserving source values verbatim when quoted.
- Use only the controlling tracking code and authorized recipient.

## Procedure

1. Discover Sheets and Gmail schemas.
2. Retrieve the latest reporting requirements, older templates, and any later requests relevant through the runtime date.
3. Determine the controlling period, value threshold, exclusions, tracking code, recipient, and required format.
4. Read all source rows and reject malformed/noise records.
5. Apply period, outcome, competitive-deal, note-based, and value filters; record one reason for every exclusion.
6. Count wins and losses, sum their values, compute win rate, and aggregate primary reasons by outcome.
7. Independently reconcile counts and amounts to the included row set.
8. Draft a pattern-focused report with methodology, win rate, outcome totals, value totals, leading reasons, exclusions, and tracking code.
9. Send the report through Gmail to the authorized internal distribution.

## Mutation Ordering

Complete requirements reconciliation, filtering, calculations, and report verification before the single Gmail send.

## Verification

- Retain inclusion/exclusion evidence for every valid source row.
- Confirm all included close dates fall inside the exact reporting period and all values satisfy the threshold.
- Recompute win rate and value totals from the final included set.
- Confirm the report focuses on aggregated patterns and contains the exact tracking code.
- Confirm Gmail accepted the authorized recipient.

## Failure Handling

- Exclude and disclose invalid dates, outcomes, or amounts rather than guessing.
- Ignore informal inclusion requests that conflict with controlling policy unless an authorized update explicitly changes it.
- Stop if authoritative current requirements conflict without resolvable precedence.
- If email fails, preserve the verified report and return the delivery failure without altering the analysis.

## Completion Criteria

Every row is accounted for, the included set matches current period and competitive-deal rules, win rate and aggregates reconcile, and the authorized audience receives a tracking-coded report.

## Output Requirements

Report included and excluded counts, wins, losses, win rate, aggregate amounts, leading reason patterns, tracking code, and Gmail delivery status. Preserve quoted source values exactly.
