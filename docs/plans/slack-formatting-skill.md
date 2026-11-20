# Plan: chat message formatting skill (Slack)

Status: implemented in PR #85 (`slack-formatting` bundled skill). Date: 2026-11-20. Builds on PR #85 (bundled skills
live in `install/content.py` `SKILLS`, budget `SKILL_MAX = 2500` bytes).

## Why a skill and not a rule

The guidance only matters when an agent writes a Slack message. An always-on rule would cost
context in every session; a skill loads only when needed. The content is generic Slack
behavior, so it belongs in the engine, not in a company pack.

## Verified behavior (tested 2026-11-19)

- **Draft through the connector** (`slack_send_message_draft`, `thread_ts` for threads) renders
  standard Markdown: `**bold**`, `_italic_`, real lists with `- ` and 2-space nested levels,
  `[text](url)` links, `:emoji:` codes. Accepted about 12,900 characters.
- **Direct send** (`slack_send_message`) fails with `msg_too_long` near 5,000 characters.
- **Does not work:** fake bullets (`•`, `◦`) with leading spaces (Slack trims them, nesting is
  lost); pasting `[text](url)` in the normal composer unless the user enables markup
  formatting, which then breaks indented lists.
- **One draft per channel or thread.** A new draft silently replaces the previous one; the
  connector cannot edit or delete drafts.
- **Raw API:** `mrkdwn` uses `*bold*` and `<url|text>` and has no lists. Real lists need
  `rich_text_list` blocks (`indent`) or the `markdown` block (12,000 characters).

Sources:
- https://slack.com/help/articles/360039953113-Format-your-messages-in-Slack-with-markup
- https://docs.slack.dev/messaging/formatting-message-text
- https://docs.slack.dev/reference/block-kit/blocks/markdown-block

## Proposed skill: `slack-formatting`

Added to `SKILLS` in `install/content.py`, English, under 2,500 bytes:

1. **Default path:** create a draft with the connector so the user reviews and sends it. Use
   direct send only when the user asks and the text is under 5,000 characters.
2. **Format:** standard Markdown as above. Never fake bullets; never use `*x*` or `<url|text>`
   in a draft (that is API `mrkdwn`).
3. **Before writing:** show the exact text and target channel or thread and wait for OK.
   Warn before creating a draft where one may already exist (it will be replaced).
4. **Raw API fallback:** `mrkdwn` syntax, lists via `rich_text_list` or the `markdown` block.
5. **Content:** never mention internal tooling; link sources, do not copy them.

## Tests

- Budget: the existing `test_context_budget.py` loop covers the new entry.
- Install: one assertion that the skill renders for each agent, reusing the current skill
  install test; no new test file.

## Local follow-up (outside this repo)

The company pack rule about PR announcements keeps its channel and message shape, drops the
"if `**bold**` does not render, try `*bold*`" hint, and points to this skill. Whether the
announcement becomes a draft (user presses send) or stays a direct send after OK is the
user's decision.

## Decisions

- Engine skill (the personal layer is retired).
- Shipped in PR #85, no separate branch.
