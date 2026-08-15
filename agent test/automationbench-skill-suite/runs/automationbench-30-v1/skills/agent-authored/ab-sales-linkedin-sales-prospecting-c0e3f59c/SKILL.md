---
name: ab-sales-linkedin-sales-prospecting-c0e3f59c
description: >-
  Identify an exact LinkedIn decision maker by title, company, and region, send a
  grounded personalized connection request, and update the corresponding
  Salesforce lead. Use for LinkedIn-to-CRM prospecting workflows.
---

# Prospect a Decision Maker and Update Salesforce

## Overview

Find one exact decision-maker profile, resolve the corresponding Salesforce lead, write a concise invitation from verified profile facts and the supplied value proposition, send it, and update the lead with discovered details and a working status.

## When to Use

Use when prospecting specifies a role, company, and geography and requires both a LinkedIn invitation and a Salesforce lead update.

## Do Not Use When

Do not use when multiple profiles remain plausible, the target is not currently in the requested role/company/region, or no corresponding Salesforce lead can be matched reliably.

## Inputs and Authoritative Sources

- Treat the runtime request as authoritative for target role, company, region, and value proposition.
- Treat the LinkedIn profile as authoritative for name, current title, current company, location, industry, company size, and profile URL.
- Treat Salesforce as authoritative for the lead record and supported status values.
- Use exact email when available as the strongest cross-system match; otherwise require an unambiguous company and identity match.

## Required Tools

- Use `linkedin_find_profile` to research candidates.
- Use `salesforce_find_records` or `salesforce_query` to resolve the corresponding lead.
- Use `linkedin_send_invite` to send the request.
- Use `salesforce_lead_update` to store details and mark the lead as being worked.
- Discover and invoke exact schemas with `api_search` and `api_fetch`.

## Tool Limitations

- Profile search results may contain similarly titled people or former employees; inspect current fields rather than trusting rank.
- Invitation and CRM update are separate writes without rollback.
- Do not invent an email or profile field that LinkedIn does not expose.
- Respect any invitation length limit returned by the discovered schema.

## Core Rules

- Require an exact current-company match, a title that satisfies the requested seniority/function, and the requested region.
- Do not use connection count or search ordering as identity proof.
- Resolve the Salesforce lead before sending so the workflow cannot create an orphaned outreach action.
- Mention only verified engineering/functional leadership, profile industry, profile company size, and the runtime value proposition.
- Keep the invitation natural and specific without unsupported praise or claims.
- Update only the corresponding lead and use the exact supported status representing active work.
- Preserve discovered decision-maker details verbatim in the CRM description or fields supported by the update schema.

## Procedure

1. Discover LinkedIn and Salesforce schemas, including invitation limits and lead status fields.
2. Search LinkedIn using the role, company, and region. Inspect all plausible profiles.
3. Select one profile only after verifying current title, company, and location.
4. Search Salesforce for the company lead and match the decision maker by exact email or unambiguous identity evidence.
5. Draft an invitation that mentions the target's verified leadership, industry, company size, and the requested value proposition.
6. Validate the invitation against source facts and schema length limits.
7. Send the LinkedIn invitation and retain the success response.
8. Update the matched Salesforce lead with the discovered name, role, contact/profile details supported by the schema, and the being-worked status.

## Mutation Ordering

Resolve both profile and lead before writes. Send the invitation first, then mark and enrich the lead only after the invitation succeeds.

## Verification

- Retain the profile identifier and all fields supporting the target match.
- Confirm the invitation text contains the required grounded elements and no fabricated facts.
- Confirm LinkedIn accepted the invitation for the selected profile.
- Confirm the Salesforce response identifies the intended lead, working status, and saved decision-maker details.

## Failure Handling

- Stop on ambiguous profiles or leads rather than choosing by similarity.
- If the invitation fails, do not mark the lead as successfully worked through this outreach.
- If the lead update fails after invitation success, report the profile and invite evidence for manual CRM reconciliation; do not resend.

## Completion Criteria

The exact decision maker has one verified personalized invitation, and the corresponding Salesforce lead contains the verified details and active working status.

## Output Requirements

Report the selected profile and lead identifiers, match evidence, invitation status, CRM update status, and any partial failure without exposing unnecessary personal data.
