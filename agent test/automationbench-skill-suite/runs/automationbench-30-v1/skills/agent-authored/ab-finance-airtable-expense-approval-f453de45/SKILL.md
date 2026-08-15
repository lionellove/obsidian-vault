---
name: ab-finance-airtable-expense-approval-f453de45
description: Review pending expense requests against current policy, update Airtable outcomes safely, and notify each submitter only after the corresponding record is verified.
---

# Airtable Expense Approval Processing

## Overview

This workflow evaluates pending expense requests consistently against authoritative expense policy, records supported outcomes, and communicates each verified decision to its submitter.

## When to Use

Use for a batch of pending expense approvals stored in Airtable when each request must be reviewed, updated, and followed by an individual email.

## Do Not Use When

Do not use to reimburse expenses, override approval chains, invent missing receipts or pre-authorization, or force a decision where policy requires an additional approver or hold state.

## Inputs and Authoritative Sources

- The user's requested population and outcome labels.
- Current expense guidelines and later amendments from authorized finance leadership.
- Pending Airtable records, including category, amount, receipt evidence, pre-authorization, description, submitter, and contact address.
- Any authoritative approval or exception evidence linked to a request.

More recent authorized policy supersedes older conflicting policy. Record data is evidence, not permission to ignore an approval gate.

## Required Tools

Discover exact Airtable find/update and Gmail search/read/send schemas with `api_search`, then invoke them with `api_fetch`. Use spreadsheet or Drive discovery only when the current policy or evidence resides there. Use `base64_encode` only when explicitly required by a discovered API schema.

## Tool Limitations

Schema discovery does not search records. Never guess base IDs, table IDs, record IDs, field names, enum values, or email parameters. Confirm supported Airtable status and reason fields before writing.

## Core Rules

- Evaluate only records currently in the requested pending state.
- Apply all applicable rules, including receipts, category thresholds, per-person rules, pre-authorization, exceptions, and additional-approval gates.
- A required hold or escalation is not a rejection. Do not mislabel it merely to fit requested binary outcomes.
- Rejections require a specific policy-based reason.
- Notify the submitter only after the record's outcome is successfully updated and verified.
- Do not disclose other employees' requests or unnecessary sensitive details.

## Procedure

1. Discover Airtable and Gmail operations and their exact request schemas.
2. Locate and read the latest applicable expense policy and authorized amendments.
3. Query the expense table for all in-scope pending records; note the table's actual fields and allowed status values.
4. For each record, verify submitter address, category, amount, receipt evidence, pre-authorization, description, and any exception or approval evidence.
5. Apply policy deterministically. Classify as approved, rejected with reason, or held/escalated when policy requires another approval or evidence.
6. Update only fields necessary for the supported outcome. Preserve unrelated record content.
7. Verify the record status and rejection reason or hold note after the write.
8. Email the corresponding submitter with the verified outcome and concise rationale. Avoid claiming payment has occurred.
9. Track counts and failures without exposing one submitter's details to another.

## Mutation Ordering

Read policy before decisions. Update and verify each Airtable record before emailing that submitter. Do not send an approval or rejection message when its record update failed. Finish the batch only after reconciling every pending record to one documented disposition.

## Verification

Confirm each updated record retains the correct record identity, contains an allowed status, and includes a reason where required. Confirm exactly one outcome email was sent to the record's own submitter and that email matches the stored outcome.

## Failure Handling

Hold ambiguous or incomplete requests without guessing. If Airtable lacks a policy-required status or reason field, avoid destructive substitution and report the schema conflict. Continue processing independent records. If notification fails after a verified update, report the record as decided but notification-pending.

## Completion Criteria

Every in-scope pending request has a policy-supported disposition, each successful mutation is verified, every decided request has a matching submitter notification, and all holds or failures are explicitly reported.

## Output Requirements

Return counts by approved, rejected, held/escalated, unchanged, and failed status. Include concise reasons for non-approvals and notification failures, without leaking unrelated employee data.
