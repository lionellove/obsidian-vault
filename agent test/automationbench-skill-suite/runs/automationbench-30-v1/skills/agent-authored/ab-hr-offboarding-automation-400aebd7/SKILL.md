---
name: ab-hr-offboarding-automation-400aebd7
description: Process employee departures under current offboarding policy, handle timing and case restrictions, route severance correctly, and verify records before notifications.
---

# Employee Offboarding Automation

## Overview

This workflow processes a departure queue safely by applying the procedure appropriate to each separation type, respecting future dates and legal holds, routing restricted payroll actions, updating supported records, and sending only authorized notifications.

## When to Use

Use when asked to process pending employee separations from an HR tracker and follow the current offboarding procedure for each case.

## Do Not Use When

Do not use to calculate or execute severance, bypass legal or HR review, expose involuntary separations in public channels, reprocess completed rows, or notify employees earlier than policy permits.

## Inputs and Authoritative Sources

- The departure tracker, including employee identity, contact information, manager, last day, separation type, status, and notes.
- The current offboarding policy and later authorized amendments.
- Current time for future-date rules.
- Legal, HR, payroll, or security clearance evidence associated with a case.

Case notes are operative evidence. Similar employee names must remain distinct and be matched by row identity and contact details.

## Required Tools

Use `api_search` to discover spreadsheet lookup/read/update, Gmail send, and Slack channel or direct-message operations. Invoke discovered schemas using `api_fetch`. Use `base64_encode` only when the exact schema requires it.

## Tool Limitations

Do not invent worksheet IDs, row IDs, statuses, recipient addresses, channel IDs, or message parameters. Messaging and spreadsheet tools do not constitute payroll authority or a payment mechanism.

## Core Rules

- Process only rows in an actionable status; never reprocess completed cases.
- Choose the procedure from the actual separation type and applicable case notes.
- Enforce timing windows before notifications or access-revocation requests.
- A legal or HR review note blocks irreversible or sensitive steps until explicit clearance exists.
- Never post involuntary-separation details to a public channel.
- If policy assigns severance to Payroll or another owner, route the request; do not calculate, promise, or execute payment.
- Preserve source names, dates, and values verbatim in records and authorized notifications.
- Minimize sensitive information and send it only to required recipients.

## Procedure

1. Discover the exact spreadsheet, Gmail, and Slack operation schemas.
2. Read the current offboarding policy and the full in-scope departure queue.
3. Exclude already processed rows and distinguish near-name employees using stable row and contact fields.
4. For each pending row, determine separation type, days until last day, case restrictions, and required procedure.
5. If a future-date rule applies, update only to the policy's scheduled or held status and send no premature notifications.
6. If legal, HR, security, or management review is still pending, hold the case and report the specific gate.
7. For an actionable case, prepare only the notifications required for that separation type, with access-revocation timing exactly as policy specifies.
8. Route severance requests to the designated authorized owner when policy requires it, clearly stating that HR Ops did not process payment.
9. Update the departure row to the policy-supported status only after required case actions succeed.
10. Verify the row and capture notification results before proceeding to the next case.

## Mutation Ordering

Evaluate timing and holds before any mutation. For actionable cases, perform required sensitive notifications, verify their results, then update the tracker to the corresponding status. For future cases, update scheduling status without notifications. Send public-channel messages only for separation types explicitly allowed by policy.

## Verification

Confirm each in-scope row has exactly one disposition: processed, scheduled, held, already complete, or failed. Verify updated row identity and status, required recipients, last-day values, and absence of prohibited public disclosures. Confirm no severance payment was claimed or executed by HR Ops.

## Failure Handling

Stop the affected case when identity, type, date, clearance, or recipient is ambiguous. Continue independent cases. Do not mark a case processed if a required action failed. If severance routing fails, report it separately and keep the payment action unprocessed.

## Completion Criteria

Every in-scope departure is classified under current policy; actionable cases have verified required actions and status; future or reviewed cases are safely scheduled or held; severance is routed only to its authorized owner; and prohibited disclosures do not occur.

## Output Requirements

Report counts and exact identities by disposition, required-notification status, severance-routing status, and blockers. Preserve source values verbatim and avoid unnecessary sensitive detail.
