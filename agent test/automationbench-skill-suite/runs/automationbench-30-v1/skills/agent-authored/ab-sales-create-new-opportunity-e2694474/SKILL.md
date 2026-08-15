---
name: ab-sales-create-new-opportunity-e2694474
description: >-
  Create a Salesforce expansion opportunity with pricing derived from current
  module rates, account size, tier discounts, pricing updates, and account-health
  policy. Use for policy-aware add-on or module opportunity creation.
---

# Create a Policy-Priced Expansion Opportunity

## Overview

Resolve the account, determine account size and tier, apply current module pricing and eligible updates, evaluate account health, calculate the opportunity amount, prevent duplicates, and create the Salesforce opportunity in the policy-correct stage.

## When to Use

Use when an existing account wants an add-on or module and the deal amount and stage depend on spreadsheet pricing, recent internal pricing notices, and open support cases.

## Do Not Use When

Do not use for a net-new account, an unsupported module, or when account identity, pricing inputs, or required opportunity fields are ambiguous.

## Inputs and Authoritative Sources

- Treat Salesforce account identifiers, tier, renewal date, associated contacts, cases, and existing opportunities as authoritative CRM data.
- Treat the standard-pricing and tier-discount worksheets as baseline pricing authority.
- Treat newer authoritative pricing communications as overrides only when their eligibility conditions match the account.
- Treat current account-health communications as authoritative for stage restrictions.
- Treat the runtime request as authoritative for account and module identity.

## Required Tools

- Use `salesforce_find_records` or `salesforce_query` for account, contacts, cases, and duplicate opportunities.
- Use `google_sheets_get_many_rows` for module prices and discounts.
- Use `gmail_find_email` or `gmail_list_emails` for current pricing and health policies.
- Use `salesforce_opportunity_create` for the final record.
- Discover exact schemas with `api_search` and call them through `api_fetch`.

## Tool Limitations

- Pricing documents and CRM writes are not transactional.
- Contact count is a usable size measure only when current pricing guidance defines or implies it; do not substitute unrelated company-size fields.
- Do not invent close dates or required fields. If the create schema requires missing information, stop for clarification.
- A create request is not proof of a created opportunity; require a returned identifier.

## Core Rules

- Match one exact account and retain its stable identifier.
- Count only contacts associated with that account when contact count is the pricing size input.
- Match one exact module pricing row and one exact tier-discount row.
- Apply an override rate only when its effective scope and account eligibility are satisfied.
- Calculate the pre-discount price from the current base price plus the size-based variable component, then apply the current tier discount once.
- Preserve original monetary strings for audit and use normalized numeric values only for calculation.
- Search for an existing open opportunity for the same account and module before creation.
- If account-health policy places accounts with open cases on hold, derive case openness from current case status and use the exact required stage.

## Procedure

1. Discover Salesforce, Sheets, Gmail, and opportunity-create schemas.
2. Resolve the account exactly and retrieve its contacts, open cases, and existing opportunities.
3. Load standard module pricing and tier discounts.
4. Retrieve the latest authoritative pricing updates and account-health policy.
5. Determine the account-size input, exact tier, applicable base price, variable rate, and discount.
6. Evaluate every update condition, such as renewal windows, before replacing a baseline rate.
7. Compute and independently recheck the final amount.
8. Search for a duplicate account-and-module opportunity and stop if one already exists.
9. Choose the stage required by current health policy and create the opportunity with an audit-friendly description of pricing inputs.

## Mutation Ordering

Complete entity resolution, policy retrieval, pricing calculation, case review, and duplicate checking before the single create mutation.

## Verification

- Retain source rows and communications supporting every price input and policy decision.
- Reconcile the size count to exact account-linked contacts.
- Recompute the final amount from parsed values and verify discount application.
- Confirm the returned opportunity identifier, account relationship, module/name, amount, and stage.

## Failure Handling

- Stop on conflicting current pricing guidance, missing discount rows, invalid amounts, or unclear account size.
- Do not create a second opportunity when a verified duplicate exists.
- If creation fails, report the calculation and error without retrying with altered fields unless the schema identifies a correctable validation issue.

## Completion Criteria

One nonduplicate opportunity exists for the exact account and module with a verified, policy-supported amount and account-health stage.

## Output Requirements

Report the created identifier, account-size basis, pricing components, applied update and discount, health-policy result, final amount, and any skipped duplicate or failure.
