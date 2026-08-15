---
name: ab-operations-trello-basecamp-slack-compliance-foll-a3f74b16
description: >-
  Turn the latest matching compliance follow-up email into coordinated Trello
  and Basecamp updates and a Slack notification. Use when one source message
  supplies exact task text and due dates for multiple project-management systems.
---

# Coordinate a Compliance Follow-Up Across Trello and Basecamp

## Overview

Find the latest compliance follow-up email that satisfies the runtime selectors, copy its task text and due date exactly, update the specified Trello card, create the specified Basecamp todo, and notify the team after both systems are confirmed.

## When to Use

Use when a compliance email must drive a card update and label in Trello, a new todo in Basecamp, and a completion message in Slack.

## Do Not Use When

Do not use for general compliance mail, for a message whose sender or subject does not match the request, or for a Trello-only or Basecamp-only workflow.

## Inputs and Authoritative Sources

- Treat the runtime request as authoritative for sender, subject phrase, board/card, Trello label, Basecamp account/project/todoset/list, and Slack channel.
- Treat the newest matching email body as authoritative for task text and due date.
- Preserve source text and dates verbatim in both destination systems and in any notification that quotes them.

## Required Tools

- Discover exact request schemas with `api_search` and invoke them with `api_fetch`.
- Use `gmail_find_email` and `gmail_get_email_by_id` for source selection.
- Use `trello_board_list`, `trello_find_card`, `trello_card_update`, and `trello_card_label` for Trello.
- Use `basecamp3_todo` to create the Basecamp todo.
- Use `slack_list_channels` and `slack_send_channel_message` for team notification.

## Tool Limitations

- Schema search does not search emails, cards, or todos.
- Trello updates, label assignment, Basecamp creation, and Slack sending are independent writes with no cross-system transaction.
- Do not assume a duplicate check exists when no discoverable operation supports one.
- Base64 is unnecessary unless a discovered schema explicitly requires it.

## Core Rules

- Match the sender exactly and require the requested subject phrase.
- Rank matching messages by timestamp and fetch the newest candidate in full before extracting values.
- Do not combine task text from one email with a due date from another.
- Confirm that the Trello card belongs to the requested board before mutating it.
- Apply the requested status representation according to the discovered Trello update schema; do not invent unsupported fields.
- Preserve task text and due date exactly rather than shortening or normalizing them.

## Procedure

1. Discover the schemas for Gmail, Trello, Basecamp, and Slack operations.
2. Search mail by exact sender and required subject phrase; sort plausible results by timestamp.
3. Fetch the newest result and extract the full follow-up task text and due date.
4. Resolve the requested Trello board and card. Verify the returned card identity and board relationship.
5. Update the card to reflect the requested follow-up status and set the extracted due date.
6. Add the runtime-specified compliance label to that same card.
7. Create a Basecamp todo in the requested hierarchy with the exact extracted task text and due date.
8. Resolve the Slack channel and announce the coordinated update, including relevant source values verbatim.

## Mutation Ordering

Finish source selection and destination resolution before writes. Complete the Trello update and label assignment before creating the Basecamp todo. Notify Slack only when both destination records are confirmed.

## Verification

- Confirm the email identifier, sender, subject match, timestamp, task text, and due date.
- Capture success evidence for the Trello update and label calls on the intended card.
- Capture the created Basecamp todo identifier and its destination hierarchy.
- Confirm Slack delivery to the requested channel.

## Failure Handling

- If no matching email or a required field is missing, stop before all writes.
- If card identity or board membership cannot be verified, do not mutate Trello.
- If a later mutation fails, report exactly which earlier writes succeeded and do not replay them blindly.
- If Slack alone fails, report that the project records succeeded but notification is outstanding.

## Completion Criteria

The intended Trello card reflects the follow-up status, due date, and label; the Basecamp todo contains the same source task text and due date; and Slack delivery is confirmed.

## Output Requirements

Return a concise audit summary with the source email identifier, Trello card result, Basecamp todo identifier, Slack result, and any partial failure. Do not report unverified attempts as completed.
