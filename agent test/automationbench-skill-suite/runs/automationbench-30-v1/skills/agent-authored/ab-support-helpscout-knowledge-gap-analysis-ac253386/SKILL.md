---
name: ab-support-helpscout-knowledge-gap-analysis-ac253386
description: >-
  Analyze active HelpScout questions against knowledge-base coverage and review
  policy, create deduplicated Jira content stories, log gaps, and report findings
  through Gmail and Slack. Use for support-driven documentation gap analysis.
---

# Turn HelpScout Questions into Knowledge-Base Gap Work

## Overview

Count active customer questions by normalized topic, apply current coverage, staleness, volume, and exclusion rules, create one Jira story for each actionable gap, update the gap tracker, and send reconciled findings.

## When to Use

Use when HelpScout conversations are evidence for missing or stale documentation and a coverage workbook governs which topics should become content work.

## Do Not Use When

Do not use for resolving customer tickets, for spam or closed-conversation analysis when policy limits the scope to active questions, or for topics explicitly retired or excluded from documentation work.

## Inputs and Authoritative Sources

- Treat HelpScout conversation status, tags, subjects, and customer-authored threads as authoritative evidence of customer questions.
- Treat the articles worksheet as authoritative for current topic coverage, article URL, update date, and exclusion notes.
- Treat the review-policy worksheet as authoritative for staleness and volume rules.
- Treat the gap-tracking worksheet as authoritative for already-created work and stored Jira keys.
- Treat the runtime request as authoritative for Jira project/type and reporting destinations.

## Required Tools

- Use `helpscout_get_conversations` and `helpscout_find_customer` to gather support evidence.
- Use `google_sheets_get_spreadsheet_by_id`, `google_sheets_find_many_rows`, and `google_sheets_lookup_row` for coverage, tracking, and policy.
- Use `jira_create_issue` for content stories.
- Use `google_sheets_add_row` to log confirmed gaps.
- Use `gmail_send_email` and `slack_send_channel_message` for reporting.
- Discover exact schemas through `api_search` and invoke them with `api_fetch`.

## Tool Limitations

- Topic classification is not a semantic search service; ground it in explicit tags and message content.
- Jira creation and Sheets logging are separate writes without rollback.
- The available Sheet operation appends rows; do not promise in-place correction when no update operation is available.
- Email and Slack delivery must be verified independently.

## Core Rules

- Count only conversations whose current status is in the policy-defined active scope; exclude closed, spam, and irrelevant records.
- Prefer a recognized topic tag; use subject and customer-authored text to disambiguate rather than counting every incidental tag.
- Count a conversation once per actionable topic and avoid inflating counts from multiple threads in the same conversation.
- Apply current staleness rules to article dates even if the stored coverage label says full.
- Apply current high-volume overrides exactly as configured.
- Respect retirement or do-not-create notes even when a topic otherwise appears stale or high-volume.
- Search gap tracking for an existing Jira key before creating a new story.
- Create and log work at topic granularity, with evidence counts that preserve source values.

## Procedure

1. Discover HelpScout, Sheets, Jira, Gmail, and Slack schemas.
2. Load articles, gap tracking, and review policy before analyzing conversations.
3. Retrieve HelpScout conversations and retain only eligible customer questions.
4. Normalize each conversation to one or more recognized topics using tags first and customer text second; record ambiguous topics separately.
5. Aggregate unique conversation counts per topic.
6. Join each topic to article coverage and apply missing, partial, staleness, volume, and exclusion rules.
7. Check the gap tracker for existing Jira work. Reuse a verified Jira key rather than creating a duplicate.
8. For each new actionable gap, create a Jira story in the runtime project/type with topic, evidence count, coverage state, and concise examples.
9. After Jira success, append a gap-tracking row containing the topic, exact count, severity derived from current rules, and returned Jira key.
10. Email the content lead through Gmail and post the findings to Slack, including relevant counts and failures.

## Mutation Ordering

Finish classification and gap decisions before writes. Create Jira first, then log its returned key in Sheets. Send Gmail and Slack reports only after all topics have final outcomes.

## Verification

- Reconcile topic counts to the unique eligible conversations used as evidence.
- Confirm each actionable decision cites a coverage or review-policy rule and is not excluded by notes.
- Confirm each new Jira response contains a key and each appended tracking row uses that same key.
- Confirm the emailed and posted counts match the final topic outcome table.

## Failure Handling

- Keep ambiguous topics out of automatic Jira creation and report them for review.
- If a tracker row has a Jira key, do not create another issue merely because issue lookup is unavailable.
- If Jira succeeds but Sheet append fails, preserve the Jira key and report the logging gap; do not create a second issue.
- If either notification fails, report its delivery status separately without replaying record mutations.

## Completion Criteria

All eligible HelpScout questions are counted by topic, every actionable non-excluded gap has one verified Jira story and tracking row, and Gmail and Slack reports contain reconciled counts.

## Output Requirements

Return topic counts, gap reasons, Jira keys, tracker results, and separate Gmail and Slack delivery statuses. Distinguish new work, existing work, exclusions, ambiguities, and failures.
