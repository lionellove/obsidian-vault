---
name: ab-marketing-campaign-roi-analysis-31f490e8
description: >-
  Calculate campaign ROI under current data-quality, date, classification, and
  budget rules; recommend scaling tiers and email the authorized report recipient.
  Use for governed spreadsheet-based campaign performance analysis.
---

# Analyze Campaign ROI and Scaling Capacity

## Overview

Load current reporting requirements and prior format, filter campaign rows by completion and data quality, calculate ROI, assign recommendation tiers, check channel budget capacity, and email a reconciled report with the current tracking code.

## When to Use

Use when campaign spend and attributed revenue must be evaluated under an internal ROI SOP and scaling recommendations depend on both performance and budget availability.

## Do Not Use When

Do not use excluded, unvalidated, incomplete, out-of-scope, or malformed campaign rows in official ROI results, and do not distribute the analysis to unapproved external requesters.

## Inputs and Authoritative Sources

- Treat the campaign-data worksheet as authoritative for campaign, channel, spend, attributed revenue, end date, and notes.
- Treat the budget worksheet as authoritative for quarterly budget and spent-to-date by channel.
- Treat the latest authorized internal requirements and SOP as authoritative for recipient, tracking code, date scope, formula, rounding, labels, and report format.
- Use a prior sent report only as a structural template, not as current data or policy.

## Required Tools

- Use `google_sheets_get_many_rows` for campaign and budget data.
- Use `gmail_find_email`, `gmail_list_emails`, and `gmail_get_email_by_id` for current requirements, SOP, and prior report format.
- Use `gmail_send_email` for authorized distribution.
- Discover exact schemas with `api_search` and invoke them via `api_fetch`.

## Tool Limitations

- Attributed revenue is accepted as source data; this workflow does not independently validate the attribution model beyond notes and policy flags.
- Zero-spend campaigns make the standard ROI division undefined.
- No budget mutation tool is available; a scale recommendation does not allocate funds.
- Email delivery is not proven until Gmail returns success.

## Core Rules

- Retrieve the newest internal SOP and requirements before analysis.
- Include only completed campaigns within the current policy period and exclude rows whose notes mark attribution unreliable, unvalidated, or out of official scope.
- Calculate `ROI percent = (attributed revenue - spend) / spend × 100` for positive spend.
- Handle zero spend with the exact policy label and raw revenue; do not divide by zero or report infinite ROI.
- Apply current rounding and classification boundaries exactly, distinguishing negative, break-even, standard scale, and priority-scale tiers.
- For every scaling tier, compute `remaining budget = quarterly budget - spent to date` for the exact channel; state when budget data is unavailable.
- Separate performance recommendation from budget feasibility so a high ROI does not imply available funds.
- Preserve source spend, revenue, and counts verbatim when included, while clearly labeling computed ROI.

## Procedure

1. Discover Sheets and Gmail schemas.
2. Retrieve the latest requirements email, current ROI SOP, and prior sent report structure.
3. Read campaign data and budget limits.
4. Validate row structure, end-date scope, completion, and note-based quality exclusions.
5. Parse monetary values, calculate ROI or the defined zero-spend result, and apply exact rounding.
6. Assign the current performance label and recommendation to every included campaign.
7. Join scale candidates to budget rows by exact channel and calculate remaining budget.
8. Reconcile total analyzed count and excluded count to all valid source candidates.
9. Build the report in the required structure with tracking code, source amounts, ROI, labels, budget availability, and exclusions.
10. Send only to the authorized internal recipient through Gmail.

## Mutation Ordering

Complete policy retrieval, filtering, calculation, classification, budget joins, and count reconciliation before the single email send.

## Verification

- Retain an inclusion or exclusion reason for every source row.
- Recompute every positive-spend ROI and remaining-budget value independently.
- Check boundary labels against the current SOP, including exact equality cases.
- Confirm the report count equals the included campaign set and contains the exact tracking code.
- Confirm Gmail accepted only the authorized recipient.

## Failure Handling

- Exclude malformed dates or numeric fields and disclose them rather than coercing values.
- Report missing channel budgets as unavailable instead of inventing capacity.
- Stop on conflicting current internal requirements that lack clear precedence.
- If email fails, preserve the verified report and return the delivery error without recalculating.

## Completion Criteria

Every campaign candidate is accounted for, included ROI and labels follow current policy, scale recommendations show budget feasibility, and the authorized recipient receives a report with reconciled counts and tracking code.

## Output Requirements

Report analyzed and excluded counts, campaign labels, budget findings, tracking code, recipient category, and Gmail status. Preserve source amounts and counts exactly.
