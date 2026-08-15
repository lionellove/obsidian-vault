---
name: ab-support-intercom-feature-request-eabf1b1d
description: >-
  Process tagged Intercom feature requests using spreadsheet-based product-area
  rules and blocklists, log eligible requests, create appropriate Jira stories,
  reply to requesters, and post a referenced Slack summary.
---

# Process Intercom Feature Requests

## Overview

Select unprocessed tagged feature-request conversations, resolve requester identity and blocklist status, classify requests from current keyword rules, log eligible items, create Jira stories when classification supports them, reply in Intercom, and publish a batch-referenced summary.

## When to Use

Use for Intercom conversations explicitly tagged as feature requests when product-area mapping, request logging, competitor exclusions, Jira creation, requester replies, and Slack reporting are required.

## Do Not Use When

Do not use for ordinary bugs or support questions lacking the feature-request tag, for already logged conversations, or for requesters excluded by the current blocklist.

## Inputs and Authoritative Sources

- Treat Intercom conversation tags, user-authored parts, contacts, and companies as authoritative for the request and requester.
- Treat the product-area worksheet as authoritative for keyword-to-area classification.
- Treat the feature log as authoritative for prior processing.
- Treat the blocklist as authoritative for excluded company names and domains.
- Treat the config worksheet as authoritative for the batch reference used in the Slack summary.

## Required Tools

- Use `intercom_get_conversations`, `intercom_find_contact`, and company lookup operations to resolve requests and identities.
- Use `google_sheets_find_many_rows` and `google_sheets_lookup_row` for area rules, prior logs, blocklist, and config.
- Use `google_sheets_add_row` to record processed requests.
- Use `jira_create_issue` for eligible, sufficiently classified stories.
- Use `intercom_reply_to_conversation` for requester replies.
- Use `slack_list_channels` and `slack_send_channel_message` for the batch report.
- Discover schemas with `api_search` and call them with `api_fetch`.

## Tool Limitations

- Keyword matching can produce zero or multiple areas; do not pretend it provides semantic certainty.
- Sheet append, Jira create, Intercom reply, and Slack send are independent writes without rollback.
- The log schema may not support every desired field; use only documented columns and operation fields.
- Do not mark a conversation as processed through an unsupported tag mutation.

## Core Rules

- Require the exact runtime feature-request tag and a user-authored request body.
- Deduplicate against both the feature log's request identifier and any explicit processed marker visible in the conversation.
- Resolve the contact and company before blocklist evaluation; compare normalized email domain and company name.
- Exclude blocked requesters from logging, Jira creation, and outreach unless current policy explicitly specifies a safe response.
- Match product-area keywords case-insensitively across title and user-authored content.
- If one area clearly wins, use it. If no area or an unresolved tie remains, log/report it as unclassified and do not invent a Jira category.
- Preserve affected names and any monetary values exactly when included in records or summaries.
- Read the batch reference at runtime; never synthesize one.

## Procedure

1. Discover Intercom, Sheets, Jira, and Slack schemas.
2. Load area rules, existing feature-log entries, blocklist rows, and report config.
3. Retrieve Intercom conversations and filter to tagged, unprocessed feature requests.
4. Resolve each requester's contact, email domain, and company; apply the current blocklist.
5. Classify eligible request text using the current keyword lists and retain matched evidence.
6. For a clearly classified request, create the Jira story with source identifier, request summary, product area, and requester context permitted by policy.
7. Append the feature-log row using the source request identifier, product area or explicit unclassified value, and contact email supported by the schema.
8. Reply to eligible requesters with a factual acknowledgement that does not promise delivery dates or feature acceptance.
9. Post a Slack summary with the config-derived batch reference and counts for created, logged, replied, blocked, duplicate, unclassified, and failed outcomes.

## Mutation Ordering

Complete filtering, identity resolution, and classification first. For classified items, create Jira before logging so returned issue evidence can be retained even if the log schema is minimal. Reply only after the intended internal record actions are known. Post Slack last.

## Verification

- Confirm each processed conversation has the required tag and was not already logged.
- Retain blocklist and keyword evidence for each decision.
- Capture Jira keys, Sheet append success, and Intercom reply identifiers separately.
- Confirm Slack includes the exact runtime batch reference and totals that reconcile to all candidates.

## Failure Handling

- Skip records with unresolved requester identity or blocked status.
- Keep ambiguous classifications out of automatic Jira creation and report them for review.
- If Jira succeeds but logging fails, preserve the Jira key and do not create another story.
- If a reply fails after internal writes, report it as a partial outcome without duplicating the log or issue.

## Completion Criteria

Every tagged candidate has one outcome, every eligible classified request has verified internal records and an appropriate reply, and the Slack summary reconciles all outcomes under the current batch reference.

## Output Requirements

Report counts and identifiers by outcome, including blocked, duplicate, unclassified, and partial failures. Preserve source names and relevant amounts verbatim when quoting them.
