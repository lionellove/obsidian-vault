---
name: ab-support-hiver-workload-forecast-c453ad5f
description: >-
  Forecast Hiver agent workload from active conversations and spreadsheet capacity
  baselines, log utilization, and email team leads about overloaded agents with a
  configured report reference. Use for support capacity monitoring.
---

# Forecast Hiver Agent Workload

## Overview

Join active Hiver conversations to current agent baselines, calculate current load and utilization, append one forecast row per eligible agent, and alert team leads only for agents who cross the configured overload threshold.

## When to Use

Use when Hiver assignment data must be measured against a capacity worksheet and results must be logged and escalated through Gmail.

## Do Not Use When

Do not use to reassign conversations, change agent status, or forecast agents who lack a valid active capacity baseline unless runtime policy explicitly defines fallback handling.

## Inputs and Authoritative Sources

- Treat Hiver conversation status and assignee identifier as authoritative for current assigned work.
- Treat Hiver users as authoritative for user identity when needed for validation.
- Treat the baseline worksheet as authoritative for agent identifier, display name, weekly capacity, team-lead email, and eligibility status.
- Treat config as authoritative for overload threshold and report reference.
- Treat the forecast worksheet schema as authoritative for logged columns.

## Required Tools

- Use `hiver_get_conversations` and `hiver_get_users` for workload and identity data.
- Use `google_sheets_find_many_rows`, `google_sheets_lookup_row`, and `google_sheets_get_spreadsheet_by_id` for baselines and config.
- Use `google_sheets_add_row` to append utilization results.
- Use `gmail_send_email` for overload alerts.
- Discover schemas with `api_search` and invoke them with `api_fetch`.

## Tool Limitations

- Hiver data is a current snapshot, not a time-series forecast model.
- The available Sheet operation appends forecast rows and may not support updating a prior run.
- Sheet logging and Gmail sending are independent writes without rollback.
- Do not treat an email payload as delivered without Gmail success evidence.

## Core Rules

- Join conversations to baselines by exact agent identifier, not by display name.
- Include conversation statuses that represent active assigned workload under runtime policy; exclude terminal statuses such as closed or resolved.
- Process only baseline rows whose status is eligible for active workload planning. Do not silently treat leave or inactive status as ordinary capacity.
- Count each qualifying conversation once for its current assignee.
- Calculate `utilization percent = current load / capacity * 100`.
- Reject zero, negative, or nonnumeric capacity rather than dividing by it.
- Compare utilization to the current config threshold using the configured boundary semantics. If none are specified, state the chosen equality treatment explicitly.
- Preserve calculated precision required by the destination; do not round source counts.

## Procedure

1. Discover Hiver, Sheets, and Gmail schemas.
2. Load capacity baselines, forecast config, and the forecast-log schema.
3. Retrieve Hiver users and conversations.
4. Filter conversations to active workload statuses and aggregate counts by exact assignee identifier.
5. For each eligible baseline agent, obtain current load, validate capacity, and calculate utilization.
6. Classify overload using the runtime threshold and retain the calculation inputs.
7. Append one forecast row per successfully calculated eligible agent with exact name, load, capacity, and utilization.
8. For each overloaded agent, email the configured team lead with agent name, load, capacity, utilization, and exact report reference.

## Mutation Ordering

Complete aggregation and calculations before writes. Append each forecast row before sending that agent's alert so the email refers to a logged result. Do not alert agents whose row failed to log.

## Verification

- Reconcile aggregated active conversations to the sum of agent loads plus explicitly unmatched assignments.
- Recompute utilization from logged load and capacity.
- Confirm one append success for each eligible calculated agent.
- Confirm each overload alert contains the exact report reference and metrics and was accepted by Gmail.
- Confirm no alert was sent for a below-threshold or ineligible baseline row.

## Failure Handling

- Report unassigned conversations and assignee identifiers missing from baselines separately.
- Skip invalid-capacity and non-active baseline rows without fabricating utilization.
- If logging fails, do not send the corresponding alert.
- If Gmail fails after logging, preserve the logged row and report the outstanding alert without appending a duplicate.

## Completion Criteria

Every eligible baseline agent has a verified forecast row, all active workload is reconciled or explicitly unmatched, and every logged overloaded agent has a verified lead alert containing the current report reference.

## Output Requirements

Report eligible-agent count, active-conversation count, overloaded-agent names, unmatched assignments, logged-row status, and per-alert delivery status. Preserve names and numeric values exactly.
