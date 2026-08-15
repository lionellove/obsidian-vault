---
name: ab-operations-generator-load-testing-schedule-8f49ae40
description: >-
  Determine which backup generators require load testing within a planning
  horizon, apply operational holds and effective-test overrides, schedule weekday
  calendar events, and email grouped engineer counts. Use for policy-aware
  spreadsheet-to-calendar maintenance scheduling.
---

# Schedule Backup Generator Load Tests

## Overview

Calculate each unit's next due date from the effective last test and frequency, apply all current exclusions and policy holds, schedule qualifying units in weekday morning blocks, and notify responsible engineers with exact scheduled counts.

## When to Use

Use for generator inventories that provide unit, building, frequency, last-test, status, assignment, and notes fields plus engineer mappings and operational-policy worksheets.

## Do Not Use When

Do not use for repair scheduling, emergency-run execution, portable event-unit planning, or any unit whose test is prohibited by a current hold.

## Inputs and Authoritative Sources

- Treat the runtime request as authoritative for the anchor date, planning horizon, frequency intervals, event duration, start time, and title format.
- Treat the unit worksheet as authoritative for inventory attributes and notes.
- Treat current policy and restriction worksheets as authoritative for additional holds.
- Treat an eligible dated emergency-run note as an override for the effective last-test date when the request defines it as equivalent to a test.
- Treat the engineer worksheet as authoritative for building-to-recipient mapping.

## Required Tools

- Use `google_sheets_get_spreadsheet_by_id` and `google_sheets_get_many_rows` to load units, engineers, policies, and active restrictions.
- Use `google_calendar_find_calendars` to resolve the target calendar.
- Use `google_calendar_create_detailed_event` to schedule each test.
- Use `gmail_send_email` for engineer notifications.
- Discover and invoke operations through `api_search` and `api_fetch`.

## Tool Limitations

- The listed calendar operations resolve calendars and create events but may not expose a complete free/busy search. Do not claim conflict checking beyond observable tool capability.
- Calendar creation and email sends are independent writes without a transaction.
- Do not reschedule or delete unrelated events; no such operation is required.
- Treat an event as created only when the API returns success and an event identifier.

## Core Rules

- Compute `next due = effective last test + frequency interval` using calendar dates.
- A unit is in scope when its next due date is on or before the inclusive horizon end; this includes already-overdue units.
- When a qualifying emergency-run date falls inside the request's lookback window, use it instead of the recorded last-test date.
- Apply hard exclusions before scheduling: disallowed status, excluded portable assignment, policy holds, and active building restrictions.
- Parse dated notes carefully; an undated mention is not a valid effective-test override.
- Choose the earliest permissible weekday under the runtime scheduling rule. Keep the requested local start time and duration.
- Group successfully scheduled units by engineer email and count only confirmed calendar events.

## Procedure

1. Discover the Sheets, Calendar, and Gmail schemas.
2. Read all worksheets in the referenced generator workbook, including policy updates and restriction tables rather than only the inventory.
3. Resolve the target calendar and anchor-date timezone.
4. For each unit, derive the effective last-test date, map the frequency to its interval, and calculate next due.
5. Apply status, type/assignment, note-based, and active-restriction exclusions. Record a reason for every skipped unit.
6. Select units whose next due is within the inclusive planning horizon.
7. Assign each selected unit to the earliest permissible weekday and construct the required two-hour morning event with the runtime unit identifier in the title.
8. Create events one unit at a time and retain successful event identifiers.
9. Join confirmed events to buildings and engineer contacts, aggregate counts per engineer, and send one factual email per recipient group.

## Mutation Ordering

Finish calculations and exclusions before any event write. Create and verify all events before computing email counts. Send notifications only from the confirmed-event set.

## Verification

- Retain effective last-test, interval, next due, eligibility, and exclusion reason for each inventory row.
- Confirm every scheduled date is a weekday and every event has the required start time, duration, title, and calendar.
- Confirm each event response returns an identifier.
- Reconcile the sum of emailed group counts to the number of successful event creations.
- Confirm each engineer email was accepted by Gmail.

## Failure Handling

- Skip rows with invalid dates, unknown frequency, missing unit/building, or ambiguous policy state and report them separately.
- Do not schedule a unit when a hard hold or active restriction applies.
- If an event fails, exclude it from notification counts and do not recreate successful events.
- If an engineer mapping is missing, keep the event result but report the unnotified unit; do not invent a recipient.

## Completion Criteria

Every inventory row is accounted for, every eligible due unit has one verified weekday event, every skipped unit has a reason, and grouped engineer emails report counts that reconcile to confirmed events.

## Output Requirements

Report scheduled and skipped totals, event identifiers, per-engineer notification status, and unresolved rows. Preserve source unit labels, dates, and counts verbatim when quoting them.
