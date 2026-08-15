---
name: ab-operations-hubspot-personalized-outreach-5dbbc834
description: >-
  Identify stale HubSpot leads under current outreach policy, generate grounded
  personalized copy with ChatGPT, send it through Gmail, and log each engagement
  in HubSpot. Use for compliant re-engagement of quiet CRM leads.
---

# Run Policy-Aware Outreach to Stale HubSpot Leads

## Overview

Load current outreach rules before evaluating HubSpot contacts, select only clearly eligible stale leads, generate individualized messages from CRM facts, send through Gmail, and log only sends that actually succeeded.

## When to Use

Use for cold-lead re-engagement where contact eligibility, staleness, personalization, sending, and CRM engagement logging are all required.

## Do Not Use When

Do not use for customers, opted-out contacts, policy-restricted industries, recent contacts, or recipients whose eligibility cannot be established from runtime policy and CRM data.

## Inputs and Authoritative Sources

- Treat current policy worksheets as authoritative for eligibility, exclusions, staleness thresholds when supplied, and logging requirements.
- Treat HubSpot contact fields as authoritative for lifecycle stage, last-contact age, name, company, industry, company size, email, and notes.
- Treat the runtime request as authoritative for campaign purpose and any additional message constraints.
- Use ChatGPT only to draft copy; it is not an authority for contact facts or policy.

## Required Tools

- Use `google_sheets_get_spreadsheet_by_id` and `google_sheets_get_many_rows` to load all active outreach and logging rules.
- Use `hubspot_get_all_contacts` to obtain candidates.
- Use `chatgpt_send_prompt` to draft one message per eligible contact.
- Use `gmail_send_email` for all sends.
- Use `hubspot_create_engagement` to record successful outreach.
- Discover and invoke operations through `api_search` and `api_fetch`.

## Tool Limitations

- The contact listing may include records lacking outreach fields; missing data is not permission to contact.
- ChatGPT can generate text but cannot verify CRM facts or guarantee policy compliance.
- Gmail sending and HubSpot engagement creation are separate writes with no transaction or rollback.
- Do not claim that an email was sent based only on generated copy.

## Core Rules

- Load the latest active policy before selecting contacts.
- Require the allowed lifecycle stage and a valid recipient email.
- Exclude every contact covered by opt-out, restricted-industry, customer-stage, or other current policy rules.
- Determine staleness from the explicit runtime threshold or policy. If neither defines one, do not invent a cutoff; report the ambiguity.
- Personalize only with verified CRM facts. Do not fabricate achievements, pain points, or relationship history.
- Review generated copy for unsupported claims, sensitive content, and compliance before sending.
- Include every policy-required field in the engagement log, including analytics attributes such as industry when required.

## Procedure

1. Discover the Sheets, HubSpot, ChatGPT, Gmail, and engagement schemas.
2. Fetch the outreach-policy and engagement-logging worksheets and retain only rules currently marked active.
3. Retrieve all HubSpot contacts and discard records that lack the fields required for a safe eligibility decision.
4. Apply lifecycle, opt-out, industry, and staleness rules. Build an evidence record for each included or excluded contact.
5. Prompt ChatGPT separately for each eligible lead using only verified name, company, industry, company size, and campaign value proposition.
6. Review the subject and body against policy and CRM facts.
7. Send the approved message with Gmail to the contact's CRM email.
8. After a confirmed send, create a HubSpot engagement tied to the contact and include the required factual tracking details.

## Mutation Ordering

Perform policy retrieval and filtering before copy generation. Generate and review before sending. Create the engagement only after Gmail confirms the send, so the CRM does not record unsent outreach.

## Verification

- Record the rule and CRM fields supporting each eligibility decision.
- Confirm the final message contains no unsupported personalization.
- Capture Gmail success evidence for each recipient.
- Capture the HubSpot engagement identifier and confirm it references the same contact and includes required logging fields.

## Failure Handling

- Skip ambiguous, incomplete, or policy-restricted contacts without sending.
- If generation fails review, revise using the same verified facts or skip the contact.
- If Gmail fails, do not create a sent-email engagement.
- If logging fails after a successful send, report the contact and send evidence for manual reconciliation; do not resend the email.

## Completion Criteria

Every processed contact is policy-eligible and stale under an explicit rule, has one verified Gmail send, and has one corresponding HubSpot engagement containing all required tracking information.

## Output Requirements

Summarize counts of eligible, excluded, sent, and logged contacts. For exclusions or failures, state the governing reason without exposing unnecessary personal data.
