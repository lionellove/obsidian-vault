---
name: ab-operations-role-based-access-audit-88c6c488
description: >-
  Audit employee system access against role permissions, account for documented
  exceptions, create review tasks for unauthorized access, and email a complete
  security report. Use for spreadsheet-driven quarterly access reviews.
---

# Audit Role-Based Access and Create Review Tasks

## Overview

Join each employee-access row to the current role definition, calculate unauthorized systems, interpret documented approvals conservatively, create one review task for each actionable row, and send a complete report to the configured security recipient.

## When to Use

Use when employee access, role permissions, exception notes, and audit settings are maintained in worksheets and unauthorized access must produce review tasks plus a security report.

## Do Not Use When

Do not use to revoke access directly, to grant exceptions, or to infer permissions for a role missing from the authoritative role-definition worksheet.

## Inputs and Authoritative Sources

- Treat the employee-access matrix as authoritative for each row's employee, role, department, actual systems, and notes.
- Treat the role-permissions worksheet as authoritative for allowed systems.
- Treat audit settings as authoritative for the destination project and report recipient.
- Treat notes as evidence of an exception only when they clearly approve the relevant excess access; do not expand a narrow or ambiguous approval.

## Required Tools

- Use `google_sheets_get_many_rows` and `google_sheets_find_many_rows` to read the matrix, role definitions, and audit settings.
- Use `asana_list_projects` to resolve the configured review project.
- Use `asana_create_task` to create review tasks.
- Use `gmail_send_email` to send the full audit report.
- Discover schemas with `api_search` and invoke operations with `api_fetch`.

## Tool Limitations

- The available operations create review tasks but do not revoke system access.
- Employee names may not be unique. Do not merge rows solely by display name when role or department differs.
- Task creation and email sending are independent writes without rollback.
- A created payload is not proof of a created task; require returned success evidence.

## Core Rules

- Normalize system lists only for comparison: split on the documented delimiter and trim whitespace. Preserve original labels in tasks and reports.
- Join permissions by the exact role value. If a role has no definition, flag the row as unresolved rather than treating all access as authorized or unauthorized.
- Compute `unauthorized = actual systems - allowed systems`.
- Apply documented special approval only to the systems it clearly covers. Keep unapproved excess systems in the unauthorized set.
- Treat each matrix row as a distinct audit subject unless a stable employee identifier proves rows belong together.
- Create a review task only when the final unauthorized set is non-empty or current audit policy explicitly requires review for an unresolved/offboarding state.
- List every unauthorized system explicitly in the task and report.

## Procedure

1. Discover the exact Sheets, Asana, and Gmail schemas.
2. Read every relevant worksheet in the access-control spreadsheet, including settings and notes-bearing matrix rows.
3. Build an exact role-to-allowed-systems map and validate duplicate or missing role definitions.
4. For each matrix row, parse actual and allowed systems, compute the set difference, and apply only clear note-based exceptions.
5. Classify the row as compliant, approved exception, unauthorized, or unresolved; retain the evidence for the classification.
6. Resolve the configured Asana project.
7. Create one task for each actionable row, naming the employee context and listing the exact unauthorized systems and relevant notes.
8. Build a full report covering all rows, review-task identifiers, exceptions, and unresolved cases.
9. Send the report to the security recipient from current audit settings.

## Mutation Ordering

Complete and freeze the audit calculation before creating tasks. Create and verify all required tasks before sending the report so it can contain accurate task identifiers and failures.

## Verification

- Recompute each non-empty difference from the source values.
- Confirm each exception is supported by explicit note text.
- Confirm every actionable row has exactly one successful task create response.
- Confirm the report includes every matrix row and every specific unauthorized system.
- Confirm Gmail accepted the report for the configured recipient.

## Failure Handling

- Do not guess when a role definition or exception scope is missing; label the row unresolved.
- If the project cannot be resolved, stop before task creation and report the configuration issue.
- If some task creates fail, include those failures in the report and do not create duplicates for successful rows.
- If email fails after task creation, preserve the task identifiers and report the outstanding delivery separately.

## Completion Criteria

All matrix rows are classified, each unauthorized row has a verified review task listing its exact excess systems, and the configured security recipient has received a complete, verified report.

## Output Requirements

Return totals by classification, created task identifiers, the report send status, and any unresolved rows or partial failures. Never describe an access review task as an access revocation.
