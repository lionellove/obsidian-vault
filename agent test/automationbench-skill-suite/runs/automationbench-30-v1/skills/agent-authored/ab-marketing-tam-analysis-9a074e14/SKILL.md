---
name: ab-marketing-tam-analysis-9a074e14
description: >-
  Calculate board-ready TAM, SAM, and SOM from market data using the latest
  authoritative methodology, exclusions, quality flags, and tracking code, then
  email a source-preserving analysis. Use for governed market sizing.
---

# Produce a Governed TAM, SAM, and SOM Analysis

## Overview

Reconcile current methodology across internal sources, validate and filter segment rows, calculate TAM/SAM/SOM with the mandated approach, separate data-quality issues, and email the required recipient with the current tracking code.

## When to Use

Use when market sizing must be calculated from an approved worksheet under evolving board-reporting methodology and distribution requirements.

## Do Not Use When

Do not use raw market figures without applying current inclusion rules, include contested or explicitly excluded rows in main totals, or distribute the report to unapproved external recipients.

## Inputs and Authoritative Sources

- Treat the market-data worksheet as authoritative for segment type, serviceability, accounts, deal size, current share, quality flags, and exclusion notes.
- Treat current authorized internal email and Slack guidance as authoritative for methodology, tracking code, exclusions, format, and distribution.
- Resolve conflicts by authority, timestamp, specificity, and explicit supersession.
- Treat the runtime request as authoritative for the intended recipient when consistent with current internal distribution policy.

## Required Tools

- Use `google_sheets_get_many_rows` for market rows.
- Use `gmail_list_emails` and `gmail_find_email` for strategy and reporting guidance.
- Use `slack_list_channel_messages`, `slack_get_channel_messages`, or `slack_find_message` for current methodology directives.
- Use `gmail_send_email` for the final analysis.
- Discover schemas with `api_search` and invoke them through `api_fetch`.

## Tool Limitations

- No external research operation is available; use only approved runtime sources.
- Tool calls do not provide spreadsheet formulas, so calculations must be performed and independently checked.
- Gmail send is a single external mutation without rollback.
- Do not hide contested or estimated data through rounding or silent omission.

## Core Rules

- Retrieve all relevant current methodology sources before calculating.
- Under a bottom-up directive, compute each segment opportunity as `addressable accounts × average deal size`; do not substitute a raw market-size column.
- Apply current segment-type and serviceability rules separately for TAM and SAM.
- Calculate SOM only from qualifying SAM segments as `segment opportunity × current share`, then sum.
- Apply all notes-based exclusions, including under-review, partner-managed, double-counted, or other current exclusion phrases.
- Exclude contested figures from main totals and list them in a distinct data-quality section with source values.
- Include estimated rows when current policy allows them, but label them explicitly.
- Preserve source counts and monetary strings verbatim when quoted; keep full precision in calculations unless current methodology requires rounding.
- Use only the tracking code and recipients from the controlling current guidance.

## Procedure

1. Discover Sheets, Gmail, Slack, and send schemas.
2. Retrieve market methodology, board standards, distribution guidance, and later authorized updates through the runtime date.
3. Build a controlling requirements checklist and document which source supersedes each conflict.
4. Read all market rows and reject structurally invalid/noise rows.
5. Classify each valid segment as included in TAM, included in SAM, excluded, contested, or included-with-quality-label.
6. Compute segment-level opportunity and SOM contributions using the controlling formulas.
7. Sum TAM, SAM, and SOM and count qualifying SAM segments; independently recheck totals.
8. Prepare a report with prominent totals, methodology, tracking code, qualifying count, estimated labels, exclusions, and a separate data-quality section.
9. Send the report through Gmail only to authorized runtime recipients.

## Mutation Ordering

Complete source reconciliation, row classification, calculations, and verification before sending the single final report.

## Verification

- Retain source and exclusion evidence for every row.
- Recompute segment products and totals independently.
- Reconcile SAM count to the set used in the SAM and SOM calculations.
- Confirm the report uses the controlling methodology and exact tracking code.
- Confirm Gmail accepted the message for only approved recipients.

## Failure Handling

- Isolate invalid or contested rows instead of forcing them into totals.
- Stop if current authoritative sources conflict without a resolvable precedence.
- If a required numeric field is unparseable, exclude the row from totals and disclose it.
- If Gmail fails, preserve the verified analysis and report the delivery failure without changing calculations.

## Completion Criteria

Every source row is accounted for, TAM/SAM/SOM and SAM count follow the controlling methodology, quality issues are disclosed, and the authorized recipient receives a verified report with the current tracking code.

## Output Requirements

Report methodology source, totals, SAM count, exclusions, quality issues, tracking code, and Gmail status. Preserve quoted source amounts and counts exactly.
