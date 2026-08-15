---
name: ab-support-zendesk-sf-case-sync-cc537677
description: >-
  Sync eligible new Zendesk tickets into Salesforce cases using current blocklist,
  SLA, and priority configuration; comment on processed tickets and post a Slack
  batch summary. Use for policy-driven support ticket synchronization.
---

# Sync Zendesk Tickets to Salesforce Cases

## Overview

Load all sync configuration before evaluating tickets, exclude blocked requesters, match requesters and accounts, derive priority from current rules, create cases without duplicates, comment on processed tickets, and publish a reconciled batch summary.

## When to Use

Use when new Zendesk tickets must become Salesforce cases and runtime spreadsheets govern organization eligibility, SLA-based priority, and reporting references.

## Do Not Use When

Do not use for bulk status changes in Zendesk, for blocked organizations, or when requester-to-contact/account identity cannot be matched with sufficient confidence.

## Inputs and Authoritative Sources

- Treat the three runtime configuration worksheets as authoritative for blocklist status, active SLA tier, priority mappings, sync mode, and batch reference.
- Treat Zendesk ticket, requester, and organization records as authoritative for source content and requester identity.
- Treat Salesforce contacts and accounts as authoritative for CRM linkage.
- Preserve source names, amounts, and other quoted values verbatim in comments and summaries.

## Required Tools

- Fetch the independent configuration sources with `google_sheets_find_many_rows` or `google_sheets_lookup_row`.
- Use `zendesk_get_tickets`, `zendesk_find_user`, and `zendesk_find_organization` for source resolution.
- Use `salesforce_find_records` or `salesforce_query` to match contacts, accounts, and existing cases.
- Use `salesforce_case_create` for case creation.
- Use `zendesk_add_comment_to_ticket` for internal comments.
- Use `slack_list_channels` and `slack_send_channel_message` for the batch summary.
- Discover schemas with `api_search` and call them with `api_fetch`.

## Tool Limitations

- `api_search` finds operation schemas, not tickets or CRM records.
- Salesforce case creation and Zendesk commenting are separate writes without rollback.
- Do not assume an internal comment mode; verify the discovered comment schema supports a private/internal flag before sending.
- Do not infer a contact or account from a similar name when exact requester email or an unambiguous relationship is unavailable.

## Core Rules

- Fetch blocklist, SLA tiers, and sync configuration before processing any ticket; issue the independent reads in parallel when the runtime permits.
- Process only tickets in the runtime-defined new/incremental scope.
- Match policy by normalized requester email domain while preserving the original domain in audit output.
- Exclude entries whose current blocklist status is blocking. Apply warning or SLA priority only through current config values, not hard-coded mappings.
- Require an exact Salesforce contact email match, then use that contact's account relationship.
- Search for an existing equivalent case before creation using stable source identifiers when available; do not create a duplicate from subject similarity alone.
- Add an internal Zendesk comment only after a case is confirmed, and mention the matched Salesforce account name.
- Include the config-derived batch reference in Slack.

## Procedure

1. Discover schemas for the needed Sheets, Zendesk, Salesforce, and Slack operations.
2. Start the three independent configuration reads together and wait for all to succeed.
3. Parse blocked/warning domains, active SLA tiers, priority mappings, sync mode, and batch reference.
4. Retrieve tickets in scope. Resolve each requester and, when needed, the requester's Zendesk organization.
5. Evaluate blocklist status and SLA tier by requester domain; record each skip or priority input.
6. Match the requester to a Salesforce contact by exact email and resolve the related account.
7. Search Salesforce for an already-synced equivalent case. Skip creation when a verified equivalent exists and report it separately.
8. Derive case priority from applicable current config rules. If multiple rules apply without a defined precedence, mark the ticket ambiguous rather than inventing precedence.
9. Create the Salesforce case with the source subject, description, account, origin, and derived priority supported by the schema.
10. Add a private Zendesk comment to the source ticket naming the matched account and referencing the confirmed case.
11. Post a Slack summary with the batch reference, counts by result, affected entity names, and relevant source amounts.

## Mutation Ordering

Complete all configuration reads first. For each ticket, finish filtering, identity matching, duplicate checking, and priority derivation before case creation. Comment only after case success. Post Slack after all ticket outcomes are reconciled.

## Verification

- Confirm all three config reads succeeded and the batch reference is present.
- Retain the evidence for domain classification, contact match, account match, and priority selection.
- Capture each created case identifier and verify its contact/account context and priority.
- Confirm each processed ticket received a private comment mentioning the account name.
- Reconcile Slack totals to created, duplicate, blocked, unmatched, ambiguous, and failed outcomes.

## Failure Handling

- If any required config source fails, stop before processing tickets.
- Skip blocked, unmatched, or ambiguously prioritized tickets without creating cases or comments.
- If case creation succeeds but commenting fails, retain the case identifier and report a partial sync; do not create another case.
- If Slack fails, report that record-level processing completed but the batch notification is outstanding.

## Completion Criteria

Every ticket in scope has one recorded outcome, every eligible matched ticket has at most one confirmed Salesforce case and an internal Zendesk comment, and Slack contains a reconciled summary with the current batch reference.

## Output Requirements

Report counts and identifiers by outcome, config-read status, comment status, and Slack status. Preserve affected names and relevant monetary values exactly when included.
