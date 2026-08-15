---
name: ab-sales-overdue-followup-flag-4b2183ea
description: >-
  Audit Salesforce follow-up tasks against a business-day overdue policy,
  completion evidence, and approved extensions; create deduplicated high-priority
  flags and email only overdue items. Use for CRM follow-up control reviews.
---

# Flag Truly Overdue Salesforce Follow-Ups

## Overview

Evaluate follow-up tasks from source dates and evidence rather than CRM status alone, exclude tasks with verified completion or approved extensions, create one policy-formatted flag per overdue task, and email a summary containing only overdue items.

## When to Use

Use when Salesforce follow-up status may be unreliable and a worksheet defines overdue timing, completion proof, flag format, and extension exemptions.

## Do Not Use When

Do not use for arbitrary task reprioritization, for items that are not follow-ups, or when the runtime date or due date cannot be established.

## Inputs and Authoritative Sources

- Treat the current follow-up policy as authoritative for business-day grace period, completion evidence, extensions, and flag format.
- Treat Salesforce task due date, description, owner, contact, related record, and closure fields as source facts.
- Treat Salesforce notes linked to the task or related account as authoritative only for explicit manager-approved extensions.
- Treat the runtime request as authoritative for summary recipient and the runtime date as the comparison anchor.

## Required Tools

- Use `google_sheets_get_many_rows` for current follow-up policy.
- Use `salesforce_find_records` or `salesforce_query` for tasks, contacts, accounts, notes, and existing flags.
- Use `salesforce_task_create` to create flag tasks.
- Use `gmail_send_email` for the overdue-only summary.
- Discover exact schemas with `api_search` and call them through `api_fetch`.

## Tool Limitations

- The available workflow creates flags but does not modify or close the original task.
- Business-day calculation excludes weekends only unless current policy names holidays and provides a calendar.
- Task creation and email sending are independent writes without rollback.
- Similar flag subjects alone may not prove duplication; combine subject with original task linkage when available.

## Core Rules

- Retrieve policy before classifying any task.
- Start with follow-up tasks that are operationally open, but independently validate completion evidence rather than trusting status text.
- When policy requires a completion note, treat a completed status without that evidence as not actually complete.
- Compute elapsed business days strictly from the due date to the runtime date and apply the policy boundary exactly.
- Exempt only tasks with explicit, applicable manager-approved extensions in related notes.
- Search for an existing flag tied to the original task before creating another.
- Build the new subject, priority, and owner exactly from policy and preserve original names and values verbatim.
- Include only overdue items in the email; omit compliant, completed, extended, and not-yet-overdue tasks.

## Procedure

1. Discover Sheets, Salesforce query/create, and Gmail schemas.
2. Load all current follow-up policy rows.
3. Retrieve candidate follow-up tasks and their related contacts, accounts, and notes.
4. Determine actual completion from status, closure fields, and required description evidence.
5. For every not-complete task, calculate business days past due and test the strict policy threshold.
6. Check related notes for an explicit manager-approved extension that covers the evaluation date.
7. For each remaining overdue task, search for an existing linked flag.
8. Create one policy-formatted flag with the same owner and source relationships.
9. After all creates, send a Gmail summary containing only verified overdue items and their affected entity names.

## Mutation Ordering

Complete classification, extension checks, and duplicate checks before any flag creation. Send the summary only after all overdue flag outcomes are known.

## Verification

- Retain due date, runtime date, counted business days, completion evidence, and extension evidence for each candidate.
- Confirm each created flag has the exact subject format, priority, owner, and original-task relationship supported by the schema.
- Reconcile the summary item count to verified overdue classifications and flag results.
- Confirm Gmail accepted the summary for the runtime recipient.

## Failure Handling

- Mark invalid dates, missing owners, or ambiguous extensions unresolved rather than overdue.
- Do not create a second flag for a verified existing one.
- If some flag creates fail, show those failures in the overdue-only summary without claiming a flag exists.
- If email fails, preserve successful flag identifiers and report only the delivery gap.

## Completion Criteria

Every candidate is evidence-classified, every nonexempt overdue task has at most one verified flag, and the recipient receives a summary containing only overdue items.

## Output Requirements

Report overdue count, created and existing flag identifiers, affected entity names, unresolved classifications, and Gmail delivery status. Preserve source values verbatim.
