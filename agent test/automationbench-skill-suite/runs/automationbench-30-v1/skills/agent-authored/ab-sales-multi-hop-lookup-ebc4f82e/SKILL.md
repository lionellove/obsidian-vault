---
name: ab-sales-multi-hop-lookup-ebc4f82e
description: >-
  Close a Salesforce opportunity as won and route a Gmail notification using
  current account-tier, FX, routing-policy, and support-escalation data. Use for
  multi-source sales win workflows requiring verified joins and currency handling.
---

# Close and Route a Sales Win

## Overview

Resolve the opportunity and account, obtain the latest authoritative tier and exchange rate, evaluate open support escalations, mark the opportunity won, and send verified Gmail notifications to recipients selected by the current routing policy.

## When to Use

Use when a deal win requires Salesforce mutation plus policy-driven notification based on spreadsheet and support-case lookups.

## Do Not Use When

Do not use when the opportunity match is ambiguous, the win is not authorized, or required tier, currency, or routing inputs cannot be verified.

## Inputs and Authoritative Sources

- Treat the runtime request as authoritative for the opportunity identity and allowed team mailboxes.
- Treat Salesforce opportunity/account identifiers as the join keys between the deal and account.
- Treat the account-hierarchy worksheet as authoritative for tier; choose the newest valid row for the exact account identifier.
- Treat the FX worksheet as authoritative for conversion; choose the newest valid rate for the opportunity currency.
- Treat the latest internal routing policy as authoritative for primary and conditional recipients.
- Treat current Salesforce cases as authoritative for open escalation status and priority.

## Required Tools

- Use `salesforce_find_records` or `salesforce_query` to resolve opportunity, account, and cases.
- Use `google_sheets_get_many_rows` for hierarchy and FX rows.
- Use `gmail_send_email` for supported sends. Use routing guidance only when it is already present in observable task state or can be read through an operation actually returned by schema discovery; do not assume Gmail search or read support.
- Use `salesforce_opportunity_update` to mark the opportunity won.
- Discover schemas with `api_search` and invoke them with `api_fetch`.

## Tool Limitations

- Schema search does not search business records.
- Salesforce update and Gmail sends are independent writes without rollback.
- The available tools do not guarantee transactional multi-recipient delivery; verify each send separately.
- The supplied operation hints expose Gmail sending but no Gmail search/read operation. If current routing guidance is not otherwise observable through a supported operation, stop before updating the opportunity or sending mail rather than guessing recipients.
- Do not convert currency without an exact currency row and parseable rate.

## Core Rules

- Match the opportunity exactly and verify its account relationship before calculations.
- Resolve duplicate hierarchy or FX rows by exact key and newest update timestamp, not by row order or similar names.
- Preserve the source amount and currency. When conversion is required, compute `converted amount = source amount × current rate` and label both currencies clearly.
- Define open support escalations from current case status and the priority levels named by routing policy; do not treat closed cases as open.
- Select recipients only through current routing rules and the runtime mailbox allowlist.
- Include the opportunity name, account name, and relevant source and converted amounts in notifications.

## Procedure

1. Discover the Salesforce, Sheets, update, and Gmail-send schemas. Record whether schema discovery exposes any supported source for reading the current routing guidance.
2. Resolve one opportunity by exact requested name and fetch its account by identifier.
3. Load all hierarchy rows for that account and select the newest valid tier record.
4. If the opportunity is not already in the reporting currency, load current FX rows and select the newest exact-currency rate.
5. Query cases for the account and identify qualifying open escalations under current policy.
6. Retrieve the latest authoritative routing guidance only from observable task state or an actually discovered supported read operation. If neither exists, stop safely; otherwise map the resolved tier to a primary mailbox and add any conditional escalation mailbox.
7. Validate every selected recipient against the runtime allowlist.
8. Update the opportunity to the exact closed-won stage supported by the Salesforce schema.
9. After update success, send the win notice through Gmail to the policy-selected recipient set.

## Mutation Ordering

Complete all joins, calculations, case checks, and routing decisions before writes. Mark the opportunity won first. Send email only after Salesforce confirms the update.

## Verification

- Capture the exact opportunity/account identifiers and selected hierarchy/FX row timestamps.
- Recompute any conversion from preserved source values.
- Record the cases supporting the escalation decision.
- Confirm the update response identifies the intended opportunity and won stage.
- Confirm each Gmail response accepted the intended recipient and content.

## Failure Handling

- Stop before mutation on ambiguous entity matches, missing tier, stale/unparseable FX data, or unresolved routing.
- If the Salesforce update fails, send no win notice.
- If one email fails after the win update, report the successful update and exact delivery gap; do not repeat successful sends.

## Completion Criteria

The exact opportunity is confirmed won, routing is supported by current tier and escalation evidence, currency is handled correctly, and every required Gmail notification is verified.

## Output Requirements

Report the updated opportunity identifier, tier source, source and converted amounts when relevant, escalation result, selected routing categories, and per-email delivery status.
