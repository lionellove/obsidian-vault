---
name: ab-support-reamaze-intercom-sync-4a6ee132
description: >-
  Synchronize eligible conversations between Re:amaze and Intercom using a
  spreadsheet tracker and current conflict-priority rules, recording progress per
  conversation and posting a reconciled Slack report. Use for bidirectional
  support-platform syncs.
---

# Synchronize Re:amaze and Intercom Conversations

## Overview

Compare both platforms with the sync tracker, apply current exclusion and conflict rules, create missing counterparts or record status changes, update tracking immediately after each successful item, and publish a final reconciliation report.

## When to Use

Use when Re:amaze and Intercom conversations must be synchronized bidirectionally and a worksheet defines existing pairs, last-synced status, exclusions, and conflict actions.

## Do Not Use When

Do not sync closed/resolved, paused, test, staging, or otherwise excluded conversations when current priority rules say to skip them. Do not use this workflow to merge unrelated conversations by similar subject alone.

## Inputs and Authoritative Sources

- Treat Re:amaze and Intercom records as authoritative for their current conversation state, contact identity, tags, and content.
- Treat the tracker as authoritative for known cross-platform ID pairs and last-synced status.
- Treat the priority worksheet as authoritative for exclusions, new-conversation handling, status-change handling, and conflict precedence.
- Preserve source entity names, amounts, subjects, and messages verbatim when copied or reported.

## Required Tools

- Use `reamaze_get_conversations`, `reamaze_create_conversation`, and `reamaze_add_message` for Re:amaze reads and supported writes.
- Use `intercom_get_conversations`, contact lookup/create operations, `intercom_create_conversation`, `intercom_reply_to_conversation`, and `intercom_add_note` for Intercom.
- Use `google_sheets_find_many_rows` and `google_sheets_lookup_row` for tracker and rules.
- Use `google_sheets_add_row` for new pairs and `google_sheets_update_row` for existing-pair progress.
- Use `slack_list_channels` and `slack_send_channel_message` for reporting.
- Discover exact schemas with `api_search` and call them with `api_fetch`.

## Tool Limitations

- There is no cross-platform transaction or rollback.
- The listed operations may not support changing conversation status directly. Follow the configured note/log action instead of inventing a status update.
- Use `reamaze_add_message` as an internal note only if its discovered schema supports private/internal visibility; never leak sync notes to customers.
- Similar subjects are insufficient proof of identity. Use tracker IDs or a newly created counterpart's returned ID.

## Core Rules

- Load tracker and priority rules before processing either platform.
- Apply hard exclusions first, including terminal states, blocked domains, and pause tags defined by current rules.
- Normalize email domains only for exclusion comparison; preserve original contact data in records.
- For a tracked pair, compare current states to the tracker's last-synced state and follow the exact configured status-change action.
- For an eligible conversation present on only one platform and absent from the tracker, create one counterpart on the other platform.
- Resolve or create the destination contact from the source contact's exact email; do not create a conversation without a trustworthy identity.
- Update or append the tracker immediately after each item's external actions are confirmed.
- Never mark an item synced when only one required side effect succeeded.

## Procedure

1. Discover the exact Re:amaze, Intercom, Sheets, and Slack schemas.
2. Read the tracker and all priority rules, preserving their declared order or precedence.
3. Retrieve conversations from both platforms and build indexes by platform ID and exact contact email.
4. Apply exclusions to every candidate before matching or creating records.
5. Resolve tracked pairs by their stored IDs. Detect missing sides, state changes, and inconsistent tracker rows.
6. For each eligible untracked Re:amaze conversation, resolve/create the Intercom contact, create the Intercom counterpart, then append the returned pair to the tracker.
7. For each eligible untracked Intercom conversation, resolve the contact email, create the Re:amaze counterpart, then append the returned pair to the tracker.
8. For each tracked status change, add only the private/internal notes supported by both platforms and update the tracker with the resulting sync status and notes.
9. After each item, record success or partial failure in the tracker using the available append/update operation.
10. Post a Slack report with counts for new pairs, status changes, skips, conflicts, and failures, plus affected entity names and relevant source amounts.

## Mutation Ordering

Process one conversation pair at a time. Create or note on destination platforms first, then write the tracker using returned identifiers. Post Slack only after all per-item tracker updates have been attempted and reconciled.

## Verification

- Confirm every processed pair is either linked by existing tracker IDs or by a newly returned counterpart ID.
- Confirm excluded conversations produced no platform writes.
- Confirm tracker rows contain both platform IDs for new pairs and accurately reflect completed status-change actions.
- Reconcile final Slack totals to item-level outcomes and confirm channel delivery.

## Failure Handling

- Quarantine ambiguous matches, duplicate tracker rows, and missing contact identities instead of guessing.
- If counterpart creation succeeds but tracker append fails, preserve both IDs and report the orphaned sync record; do not create another counterpart.
- If private notes are unsupported on either platform, do not substitute a public reply; record the limitation in tracking.
- If Slack fails, retain all platform and tracker results and report only the outstanding notification.

## Completion Criteria

Every eligible candidate has one reconciled outcome, new counterparts have verified cross-platform IDs recorded in the tracker, status changes follow current rules, exclusions receive no writes, and Slack reports the final totals.

## Output Requirements

Return item counts by outcome, new ID pairs, tracker update results, conflicts, partial failures, and Slack status. Preserve quoted names and amounts exactly.
