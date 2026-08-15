---
name: ab-hr-jira-it-onboarding-a03f71e9
description: Create policy-compliant Jira onboarding tickets from new-hire requirements while enforcing security restrictions, worker-type rules, priority overrides, and special handling.
---

# Jira IT Onboarding Ticket Creation

## Overview

Use this workflow to translate new-hire data and the latest IT policies into least-privilege Jira provisioning tickets without placing prohibited privileged-access requests in the normal onboarding path.

## When to Use

Use when HR or IT needs one setup ticket per new hire based on a roster, standard checklist, role requirements, worker type, and recent policy updates.

## Do Not Use When

Do not use to grant access directly, include prohibited root or break-glass credentials, ignore contractor restrictions, create new accounts for a rehire when reactivation is required, or bypass security approval workflows.

## Inputs and Authoritative Sources

- The new-hire roster: identity, department, role, start date, worker type, requested systems, and notes.
- The standard provisioning checklist for baseline systems, Jira project, priority, and description requirements.
- Newer instructions from authorized IT, security, and executive owners.
- Any separate privileged-access review policy and documented approvals.

Security restrictions override convenience requests. A priority override changes priority only, not access scope. Free-text notes can narrow normal provisioning and must be honored.

## Required Tools

Use `api_search` to discover spreadsheet lookup/read, Gmail search/read, and Jira issue-creation schemas, then use `api_fetch` for calls. Use `base64_encode` only when explicitly required by the discovered Jira schema.

## Tool Limitations

Do not invent Jira projects, issue types, priorities, fields, users, or allowed access. If no Jira search operation is available, do not claim that duplicate detection was performed; use roster status or another authoritative indicator if available and report the limitation.

## Core Rules

- Create exactly one standard onboarding ticket for each in-scope hire unless an existing-ticket indicator shows one already exists.
- Derive baseline access and Jira routing from worker type and current checklist.
- Add role-specific systems only when consistent with policy and notes.
- Remove or block prohibited privileged access even if the user requests it. Route it to a separate review only when the policy, approvals, and available operations support that route.
- Do not silently replace prohibited root access with a different privilege. Standard non-root access may be included only when independently allowed.
- Apply current department-specific priority overrides without changing other departments.
- Rehire and contractor notes override default account-creation behavior where applicable.

## Procedure

1. Discover exact spreadsheet, Gmail, and Jira schemas, including required issue fields.
2. Read the roster, every standard-checklist item, and recent messages from authorized IT, security, or executive owners.
3. Resolve conflicts by authority, scope, and recency; record each applicable override or restriction.
4. For each hire, determine worker type, destination project, priority, baseline services, role-specific access, start date, and special-handling instructions.
5. Remove prohibited access requests and note the governing restriction. Do not include credentials, secrets, or unnecessary personal data.
6. Construct a concise ticket with hire identity, role, department, worker type, start date, allowed provisioning checklist, and special handling.
7. Create the issue using the actual Jira schema and capture the returned issue identifier.
8. Verify the returned project, issue type, priority, summary, description, and absence of prohibited access.
9. Record held or failed hires separately without fabricating tickets.

## Mutation Ordering

Read policy and compute all access scopes before issue creation. Create and verify tickets one hire at a time. Never create a separate privileged-access ticket before confirming the mandated project, approval evidence, and authorization.

## Verification

Check every roster row is accounted for once. Confirm each ticket uses the correct project and priority, includes the start date, applies worker-type and rehire restrictions, and contains no prohibited root access. Verify issue keys came from successful API responses.

## Failure Handling

Hold a hire when project mapping, worker type, identity, special handling, or allowed access is ambiguous. Continue independent hires. If ticket creation fails, do not retry blindly when duplication is possible; inspect the error and report the unresolved hire.

## Completion Criteria

Every in-scope hire has one verified, least-privilege onboarding ticket or a documented hold/failure; current overrides are applied; prohibited access is excluded; and all created issue identifiers are captured.

## Output Requirements

Report each hire's ticket identifier, project, priority, allowed access summary, excluded or separately routed access, and any hold or failure. Never include secrets or imply access has already been provisioned.
