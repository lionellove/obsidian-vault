---
name: ab-sales-chatgpt-proposal-customization-48c76be4
description: >-
  Research account stakeholders and priorities, reconcile proposal SOP rules with
  newer authoritative guidance, use ChatGPT to draft a grounded strategy, and
  save it as a Salesforce opportunity note. Use for customized proposal planning.
---

# Build and Save a Customized Proposal Strategy

## Overview

Resolve the account and opportunity, identify stakeholders across Salesforce and LinkedIn, extract their direct priorities from email, reconcile the proposal SOP with valid newer overrides, generate a structured strategy with ChatGPT, and save the reviewed result on the opportunity.

## When to Use

Use when a proposal approach must combine CRM relationships, public professional profiles, customer communications, internal guidance, and a formal SOP.

## Do Not Use When

Do not use to send a proposal to the customer, to invent stakeholder priorities, or to save strategy on an ambiguously matched opportunity.

## Inputs and Authoritative Sources

- Treat Salesforce account, contact, and opportunity identifiers as authoritative for record linkage.
- Treat LinkedIn current-title and company fields as authoritative for stakeholder roles and company size when matched reliably.
- Treat direct stakeholder communications as stronger evidence of priorities than unsupported internal hearsay.
- Treat the proposal SOP as the baseline requirements and newer authorized internal guidance as an override only when its condition applies.
- Treat the runtime date as the cutoff for deciding whether guidance is current.

## Required Tools

- Use `salesforce_find_records` or `salesforce_query` for account, contacts, and opportunity.
- Use `linkedin_find_profile` for stakeholder titles and company size.
- Use `gmail_find_email` or `gmail_list_emails` for customer priorities and current proposal guidance.
- Use `google_sheets_get_many_rows` for the proposal SOP.
- Use `chatgpt_send_prompt` to draft the strategy.
- Use `salesforce_note_create` to save the reviewed result.
- Discover schemas with `api_search` and call them through `api_fetch`.

## Tool Limitations

- ChatGPT is a drafting aid, not an authority for account facts, ROI inputs, security claims, or policy.
- Similar names across LinkedIn and Salesforce are not sufficient for stakeholder identity.
- Salesforce note creation is a write with no rollback operation in the available tool set.
- Do not treat generated text as saved until a note identifier is returned.

## Core Rules

- Match one exact account and one opportunity linked to that account.
- Resolve stakeholders through CRM contacts and exact email/company matches to LinkedIn profiles.
- Use stakeholder-authored messages for priorities; label internal claims as unverified when they conflict with direct customer evidence.
- Apply SOP requirements by default. Apply a newer override only when its sender is authoritative, its effective date is current, and its stated condition is proven.
- Include every remaining required section and reference code from current guidance.
- Base ROI estimates on verified company-size inputs and state assumptions; do not fabricate savings.
- Ensure ChatGPT receives only verified facts, applicable rules, and explicit uncertainty.

## Procedure

1. Discover Salesforce, LinkedIn, Gmail, Sheets, ChatGPT, and note-create schemas.
2. Resolve the target account and its opportunity by stable relationships.
3. Retrieve account contacts, match them to current LinkedIn profiles, and identify stakeholder roles.
4. Search relevant email for direct stakeholder priorities and current internal proposal guidance up to the runtime date.
5. Load all SOP rules and build a requirements checklist.
6. Reconcile each override against authority, recency, and applicability; document the resulting required sections.
7. Prompt ChatGPT with verified stakeholder facts, direct priorities, requirements, value propositions, and explicit constraints.
8. Review the draft for unsupported claims, omitted sections, conflicting priorities, and ungrounded ROI figures.
9. Save the final strategy as a Salesforce note linked to the exact opportunity.

## Mutation Ordering

Complete research and rule reconciliation before generation. Review and correct generated text before the single Salesforce note creation.

## Verification

- Retain identity evidence for every named stakeholder and source evidence for each stated priority.
- Check every applicable SOP/override rule against the final strategy.
- Confirm the note parent is the intended opportunity and capture the returned note identifier.
- Confirm reference codes and required sections appear exactly as current guidance requires.

## Failure Handling

- Omit or label unverified stakeholder claims rather than resolving conflicts by guesswork.
- Stop if account/opportunity linkage is ambiguous or required guidance cannot be retrieved.
- If ChatGPT output remains unsupported after revision, do not save it.
- If note creation fails, report the reviewed strategy and error without creating a note on another record.

## Completion Criteria

A fully reviewed, evidence-grounded proposal strategy satisfying current applicable rules is stored as one verified note on the exact Salesforce opportunity.

## Output Requirements

Report the account/opportunity match, stakeholder evidence, applied and overridden rules, note identifier, and unresolved assumptions. Do not claim customer delivery.
