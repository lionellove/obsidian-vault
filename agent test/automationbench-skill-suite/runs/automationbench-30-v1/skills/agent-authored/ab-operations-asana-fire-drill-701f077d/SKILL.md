---
name: ab-operations-asana-fire-drill-701f077d
description: >-
  Process an actionable facilities fire-drill email into a correctly placed and
  tagged Asana task, then notify an operations Slack channel. Use for workflows
  that require policy-aware email selection, exact field extraction, ordered
  Asana mutations, and completion reporting.
---

# Create an Asana Fire-Drill Task from Email

## Overview

Select the newest eligible unread fire-drill email from the requested sender, apply the current email-processing policy, create the Asana task from the source values, place and tag it, and announce only a verified completion.

## When to Use

Use for a facilities request that names an email source, an Asana workspace/project/section, and a Slack destination, especially when draft or superseded notices may coexist with the actionable message.

## Do Not Use When

Do not use for non-fire-drill facilities mail, for messages prohibited by policy, or when the request is only to summarize an email without creating an Asana task.

## Inputs and Authoritative Sources

- Treat the runtime request as authoritative for sender, unread requirement, project, section, and notification destination.
- Treat the policy worksheet as authoritative for whether an email may be actioned. Read it before selecting a message.
- Treat the selected email body as authoritative for task text, due date, and tag. Preserve those values verbatim.
- Use message metadata to verify sender, unread state, subject/body relevance, and recency.

## Required Tools

- Discover schemas with `api_search`, then call them with `api_fetch`.
- Use `google_sheets_get_many_rows` for the policy rows.
- Use `gmail_find_email` and `gmail_get_email_by_id` to select and inspect the source message.
- Use `asana_find_section`, `asana_create_task`, `asana_add_task_to_section`, and `asana_add_tag_to_task` for the task.
- Use `slack_list_channels` and `slack_send_channel_message` for the completion notice.

## Tool Limitations

- `api_search` searches operation schemas, not business records.
- The available Asana calls are separate mutations; they do not provide a transaction or rollback.
- Do not assume an attempted create, section add, tag add, or Slack send succeeded without a success response or returned identifier.
- Encode content only if the discovered operation schema explicitly requires Base64.

## Core Rules

- Fetch policy before taking any write action.
- Require all runtime selection constraints: correct sender, unread, genuinely about a fire drill, and not disqualified by policy.
- Evaluate policy markers against the full message, not only its subject.
- Sort eligible candidates by message timestamp and choose the newest; do not let a newer ineligible draft displace an older actionable message.
- Do not infer missing task text, due date, or tag from another email.
- Preserve extracted names, dates, and labels exactly when writing records or notifications.

## Procedure

1. Discover the exact schemas for the needed Sheets, Gmail, Asana, and Slack operations.
2. Read all current email-processing policy rows and identify exclusion or precedence rules.
3. Search unread mail from the requested sender using a fire-drill relevance filter broad enough to catch subject variations.
4. Fetch each plausible message in full. Reject unrelated facilities topics and every message barred by policy.
5. Choose the newest remaining message and extract the task text, due date, and tag without paraphrasing.
6. Resolve the requested Asana section and retain its returned identifier.
7. Create the task in the requested project with the extracted text and due date.
8. Add the created task to the resolved section, then apply the extracted tag.
9. Resolve the requested Slack channel and send a concise notice naming the created task and preserving relevant source values.

## Mutation Ordering

Complete all reads and eligibility checks first. Create the task only after the source is unambiguous. Add it to the section before tagging it. Send Slack only after all requested Asana mutations are confirmed.

## Verification

- Confirm the chosen message satisfies every selector and policy rule.
- Capture the created task identifier from the create response.
- Confirm the section and tag calls reference that same task identifier and report success.
- Confirm the Slack response identifies the intended channel and a successful message send.

## Failure Handling

- If no eligible email remains, stop without creating a task or sending completion Slack.
- If multiple candidates tie or required fields conflict, report the ambiguity instead of guessing.
- If task creation succeeds but placement or tagging fails, retain the task identifier, report the partial state, and do not claim completion.
- If Slack fails after Asana succeeds, report the notification failure without recreating the task.

## Completion Criteria

One eligible source email has produced one task with the exact requested text and due date, placed in the requested section, tagged as directed, and followed by a verified Slack notice.

## Output Requirements

Report the selected source message, created task identifier, applied section and tag, and Slack send status. Clearly distinguish completed writes from skipped candidates and partial failures.
