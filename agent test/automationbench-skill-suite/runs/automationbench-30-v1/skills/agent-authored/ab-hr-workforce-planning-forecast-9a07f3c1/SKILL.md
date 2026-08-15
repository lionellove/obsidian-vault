---
name: ab-hr-workforce-planning-forecast-9a07f3c1
description: Submit approved workforce-plan positions only when current executive guidance permits, reconcile exact headcount, and communicate verified submission or freeze status.
---

# Workforce Planning Submission

## Overview

This workflow reconciles approved position data, checks current executive guidance, submits only permitted headcount requests, and reports exact positions and counts across email and Slack.

## When to Use

Use for a quarterly or periodic workforce plan where approved spreadsheet rows must be submitted, summarized to stakeholders, and reflected in team communications.

## Do Not Use When

Do not use to approve unapproved rows, submit during an active applicable freeze, change headcount to force agreement, post sensitive planning details to an unauthorized channel, or claim submission without a verified write.

## Inputs and Authoritative Sources

- The workforce-planning worksheet with department, role, level, headcount, status, and hiring manager.
- Current executive guidance from authorized leaders, including freezes, caps, exceptions, or submission windows.
- The requested committee, HR owner, and authorized Slack channel.
- Current time for effective-date evaluation.

A newer, applicable company-wide freeze supersedes earlier position approval until explicitly lifted. Approval in a planning sheet is not the same as permission to submit under a freeze.

## Required Tools

Use `api_search` to discover spreadsheet lookup/read/update, Gmail search/read/send, and Slack channel-send operations; invoke exact schemas with `api_fetch`. Use `base64_encode` only when required by a discovered operation.

## Tool Limitations

Do not invent worksheets, row IDs, submission-status values, mailing lists, recipients, or channel IDs. When no dedicated submission system exists, a spreadsheet status update is a submission only if the authoritative process explicitly defines it that way.

## Core Rules

- Check current executive guidance before mutating or announcing positions.
- An active freeze or suspension blocks submission, posting positions as actionable, and status changes that imply approval to hire.
- If no blocker applies, submit only rows whose exact source status qualifies under the current process.
- Preserve department, role, level, headcount, and manager strings verbatim in notifications.
- Sum headcount using numeric values while retaining original source strings.
- Distinguish planned, approved, submitted, paused, and failed states precisely.

## Procedure

1. Discover the exact spreadsheet, Gmail, and Slack schemas.
2. Read the complete position worksheet and find recent executive guidance applicable to the requested cycle.
3. Resolve guidance by authority, effective date, scope, and any documented lift or exception.
4. Filter qualifying approved rows and reconcile row-level counts to department totals and the overall total.
5. If an active freeze applies, make no submission mutations and do not post the positions as available or approved-to-hire. Prepare a blocked-status notice with exact planned counts only where appropriate for authorized recipients.
6. If submission is permitted, update each qualifying row using the actual process status and verify each write.
7. Build the hiring-committee summary from verified submission outcomes, not the original plan alone.
8. Post only verified permitted positions to the authorized hiring channel.
9. Send the HR owner a final status describing submitted, paused, skipped, and failed rows.

## Mutation Ordering

Evaluate executive guidance before any write. When permitted, update and verify rows before announcing them. Send the committee summary and Slack post only after submission outcomes are known; send the HR status last so it includes communication results. Under a freeze, skip all submission mutations and send only authorized hold-status communications.

## Verification

Confirm every source row is accounted for and no unapproved or frozen position was submitted. Recalculate department and total headcount from the exact included set. Verify spreadsheet statuses, recipients, channel, and that each communication accurately distinguishes planned from submitted counts.

## Failure Handling

Stop submission if guidance conflicts, the freeze status is unclear, qualifying statuses are undefined, or totals do not reconcile. Continue safe read-only analysis. If individual writes fail, exclude them from submitted counts and report them. Never announce failed rows as submitted.

## Completion Criteria

Current guidance has been enforced; the exact position population and totals reconcile; permitted writes are verified or correctly withheld; and stakeholders receive accurate submission or hold status without overstating authorization.

## Output Requirements

Report guidance status, exact counts by department and role, overall planned and verified-submitted totals, paused or skipped rows, spreadsheet mutation results, and email/Slack delivery status. Preserve source values verbatim.
