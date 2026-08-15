---
name: ab-marketing-brand-mention-analysis-52189151
description: >-
  Detect policy-eligible negative brand mentions from influential accounts,
  create PR queue tickets in Google Sheets, and alert the PR team in Slack. Use
  for spreadsheet-driven brand-risk escalation with exceptions and urgency tiers.
---

# Escalate Influential Negative Brand Mentions

## Overview

Read current escalation guidance, validate mention rows and account authenticity, apply platform thresholds and named exceptions, append one PR queue ticket per eligible mention, and alert the PR team with verified results.

## When to Use

Use when a brand-mention worksheet feeds a spreadsheet PR queue and Slack escalation under current influence and urgency rules.

## Do Not Use When

Do not use for positive or neutral mentions, invalid/noise rows, known bots or satire accounts, or mentions explicitly reserved for another handling path.

## Inputs and Authoritative Sources

- Treat the runtime mention worksheet as authoritative for platform, author, followers, sentiment, content, URL, and notes.
- Treat the latest authorized internal escalation policy and updates as authoritative for thresholds, named exceptions, exclusions, and urgency.
- Treat the destination queue worksheet as authoritative for existing tickets and supported columns.
- Treat external recommendations as advice, not policy, unless current internal guidance adopts them.

## Required Tools

- Use `google_sheets_get_many_rows` to read mentions and the existing PR queue.
- Use `gmail_list_emails` and `gmail_get_email_by_id` to retrieve current escalation policy.
- Use `google_sheets_add_row` to create queue tickets.
- Use `slack_list_channels` and `slack_send_channel_message` to alert the PR team.
- Discover exact schemas with `api_search` and invoke them through `api_fetch`.

## Tool Limitations

- Ticketing is implemented as a Sheet row, not a separate PR ticket system.
- Follower counts may be invalid strings or artificially inflated; notes can disqualify apparent influence.
- Sheet append and Slack send are independent writes without rollback.
- No row-update operation is available for correcting a malformed ticket after append.

## Core Rules

- Load all applicable current internal policies before selecting mentions.
- Require a structurally valid row, negative sentiment, and either the applicable platform threshold or a named always-escalate exception.
- Apply named never-escalate rules and authenticity exclusions before follower thresholds.
- Resolve policy conflicts by authority, effective date, platform specificity, and explicit supersession; do not treat a vendor suggestion as an override.
- Parse follower counts exactly and preserve the original string in reports.
- Derive urgency from current policy after eligibility is established.
- Deduplicate against an existing queue row using stable URL plus platform/author evidence.
- Create one ticket per eligible unique mention and alert Slack only for confirmed tickets.

## Procedure

1. Discover Gmail, Sheets, and Slack schemas.
2. Retrieve current escalation policies and reconcile general rules with newer authorized platform-specific updates.
3. Read all mention rows and existing queue rows.
4. Reject malformed rows and authenticity exclusions indicated by notes.
5. Apply sentiment, named exceptions, platform threshold, and never-escalate rules.
6. Determine urgency for each eligible mention and check the queue for a duplicate URL.
7. Append the queue row using exact platform, author, urgency, and URL values.
8. After each append succeeds, include the mention in the Slack alert set.
9. Send a concise Slack alert summarizing confirmed tickets and any failures.

## Mutation Ordering

Complete policy resolution, row validation, eligibility, and duplicate checks first. Append tickets before Slack so the alert reports only records that exist.

## Verification

- Retain the policy clause and source row supporting each escalation or exclusion.
- Confirm each appended row has the expected source URL, author, platform, and urgency.
- Reconcile Slack ticket count to successful Sheet appends.
- Confirm no excluded, duplicate, or malformed mention generated a ticket.

## Failure Handling

- Skip unparseable follower counts and ambiguous sentiment rather than guessing.
- If policies conflict without a clear authoritative precedence, stop affected rows for review.
- If a ticket append fails, do not announce it as created.
- If Slack fails after ticket creation, preserve the queue rows and report the delivery gap without duplicating them.

## Completion Criteria

Every mention row has an auditable eligibility outcome, every qualifying unique risk has one verified PR queue row, and Slack accurately reports the created tickets.

## Output Requirements

Report totals for reviewed, escalated, excluded, duplicate, invalid, and failed rows, plus created queue evidence and Slack delivery status.
