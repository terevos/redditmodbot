# Privacy Policy

_Last updated: 2 October 2026_

This policy covers RedditModBot: the Devvit apps `reformedautomodv2` and
`wcgwautomodv2`, and the Slack bot they serve. It is a private moderation tool
run by the moderators of the subreddits it is installed on. It is not offered
to the public.

## What the tool does

The Devvit app is installed on a subreddit by its moderators. The Slack bot
asks the app for that subreddit's mod queue and modmail and posts them to the
moderator team's private Slack workspace, so the moderators can discuss and
keep track of them there.

## What data it handles

Only data that the subreddit's moderators can already see on Reddit:

- **Mod queue items** — the reported post or comment, its author's username,
  its link, and the report reasons.
- **Modmail** — the subject, the participants' usernames, and the messages.
- **Moderation actions** — which moderator approved or removed an item, or
  archived a modmail conversation, and when.
- **Moderator identities** — the moderators' Reddit usernames and Slack user
  IDs, used to check that a person is allowed to act.

It does not collect passwords, email addresses, private messages outside
modmail, or anything about users who have not appeared in the subreddit's mod
queue or modmail. It holds no Reddit account credentials.

## Where it is stored and for how long

- **In the Devvit app** (Reddit's own platform storage, per subreddit): a
  record of who approved or removed an item, kept for 30 days and then deleted
  automatically.
- **On the operator's server**: a database of the items and conversations that
  were posted to Slack, the moderators' votes on them, and their status. It is
  kept as the moderation record until the operator deletes it.
- **In Slack**: the messages the bot posts, in private channels limited to the
  moderator team, kept under that workspace's own retention settings.

## Who it is shared with

Nobody outside the moderator team. The data goes from Reddit to the operator's
server and to the team's private Slack workspace, and nowhere else. It is not
sold, not used for advertising, and not used to train any model.

## Removal

Content deleted on Reddit is not re-fetched. To ask for the copy held by this
tool to be removed, contact the subreddit's moderators by modmail, or open an
issue at <https://github.com/terevos/redditmodbot/issues>.

## Changes

Changes to this policy are published in this file, with the date above
updated.
