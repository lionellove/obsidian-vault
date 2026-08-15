---
name: ab-marketing-social-engagement-response-1681800e
description: >-
  Classify recent Twitter mentions under the latest social-engagement SOP, like
  praise, answer eligible questions, escalate complaints to Slack, and skip
  neutral, competitor, or retweet content. Use for policy-driven social response.
---

# Handle Twitter Mentions by Social-Engagement Policy

## Overview

Retrieve the latest authoritative engagement SOP, identify direct recent mentions, classify each once, perform only the action allowed for that class, and reconcile action counts in the required messages.

## When to Use

Use when recent Twitter mentions must be triaged into likes, public replies, Slack escalations, or intentional skips.

## Do Not Use When

Do not use for unrelated tweets, direct messages, scheduled social publishing, or content outside the runtime recency scope.

## Inputs and Authoritative Sources

- Treat the latest authorized internal SOP as authoritative for categories and actions.
- Treat Twitter tweet text, author, timestamp, and retweet flag as authoritative source data.
- Treat the authenticated brand account as authoritative for determining direct mentions.
- Treat the runtime date and request as authoritative for the recency window and reporting requirements.

## Required Tools

- Use `gmail_find_email` or `gmail_list_emails` to retrieve current SOP guidance.
- Use `twitter_find_tweet` to retrieve candidate mentions and source tweets.
- Use `twitter_like_tweet` for eligible positive mentions.
- Use `twitter_post_tweet` for eligible public replies.
- Use `slack_list_channels` and `slack_send_channel_message` for complaint escalation.
- Discover schemas with `api_search` and call them through `api_fetch`.

## Tool Limitations

- Tweet search may return unrelated content; require a direct mention and runtime recency evidence.
- Liking, replying, and Slack sending are independent mutations without rollback.
- No product knowledge source is available in this workflow; do not invent feature support in a reply.
- A retweet may contain positive or negative text but remains a retweet for policy classification.

## Core Rules

- Load the latest SOP before any social action.
- Exclude unrelated tweets and handle each source tweet at most once.
- Apply explicit skip rules before sentiment: retweets and competitor comparisons receive no engagement when policy says so.
- Like positive praise only; do not add a public reply unless policy requires one.
- Reply to genuine questions with verified, helpful information. If the answer is unavailable, acknowledge the question and direct the user to an approved next step without fabricating facts.
- Never publicly reply to or like complaints when policy requires private escalation.
- Include the author's Twitter username and issue summary in each Slack escalation.
- Preserve exact counts of likes, replies, escalations, and skips.

## Procedure

1. Discover Gmail, Twitter, and Slack schemas.
2. Retrieve the newest authoritative social-engagement SOP and extract category actions.
3. Find direct mentions within the runtime recency scope and fetch full tweet records.
4. Classify each candidate in a deterministic order: ineligible/unrelated, retweet, competitor comparison, complaint, question, positive, neutral, or ambiguous.
5. Like each eligible positive tweet once.
6. Draft and post one grounded reply for each eligible question, linking it to the source tweet as supported by the schema.
7. Resolve the support escalation channel and send one concise complaint alert with username and issue summary.
8. Record skips and ambiguities without mutating Twitter.
9. Reconcile all candidate and action counts and include required counts in the final reporting message.

## Mutation Ordering

Finish SOP retrieval and classification before any action. Execute only the single allowed action for each tweet. Reconcile counts after all action responses are known.

## Verification

- Retain the SOP source and classification reason for every candidate.
- Confirm each like and reply response references the intended tweet.
- Confirm each complaint Slack message contains the exact username and issue and was delivered to the intended channel.
- Verify `candidate count = liked + replied + escalated + skipped + failed`, with no tweet in more than one completed action category.

## Failure Handling

- Leave ambiguous sentiment or intent unengaged and report it for review.
- If a reply cannot be grounded, do not invent an answer.
- If one action fails, report that tweet separately and do not compensate with a disallowed action.
- Do not repeat successful likes, replies, or escalations when retrying another failure.

## Completion Criteria

Every eligible recent mention has one policy-supported outcome, complaints have no public engagement, and all reported counts reconcile to verified actions and skips.

## Output Requirements

Report total candidates and exact counts for likes, replies, escalations, policy skips, ambiguities, and failures. Include Slack delivery evidence for escalations.
