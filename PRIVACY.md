# Privacy Policy

_Last updated: 6 October 2026_

This policy covers ReformedBot: the Devvit apps `reformedautomodv2` and
`wcgwautomodv2`, and the Slack bot they serve. It is a private moderation tool
run by the moderators of the subreddits it is installed on. It is not offered
to the public.

## What the tool does

The Devvit app is installed on a subreddit by its moderators. The Slack bot
asks the app for that subreddit's mod queue and modmail and posts them to the
moderator team's private Slack workspace, so the moderators can discuss and
keep track of them there. It only reads from Reddit; it changes nothing there.

## What data it handles

Only data that the subreddit's moderators can already see on Reddit:

- **Mod queue items** — the reported post or comment, its author's username,
  its link, and the report reasons.
- **Modmail** — the subject, the participants' usernames, and the messages.
- **Moderation actions** — which moderator approved or removed an item, or
  archived a modmail conversation, and when.
- **Deletions** — the IDs of posts and comments deleted in the subreddit, so
  that copies of them can be removed. Nothing about their content is recorded.
- **Moderator identities** — the moderators' Reddit usernames and Slack user
  IDs, used to check that a person is allowed to act.

It does not collect passwords, email addresses, private messages outside
modmail, or anything about users who have not appeared in the subreddit's mod
queue or modmail. It holds no Reddit account credentials.

## Where it is stored and for how long

Content means the text of a post, comment or modmail message, its title or
subject, and its author's username.

- **In Slack**, in private channels limited to the moderator team: the cards
  the bot posts. A card keeps its content while it is open and for 30 days
  after it is closed. The bot then edits the content out of the card, and out
  of every modmail reply threaded beneath it.
- **On the operator's server**: a database of the same cards. Content is
  removed from it at the same moment it is removed from Slack. The weekly
  export and archive files written from that database never contain content.
- **In the Devvit app** (Reddit's own platform storage, per subreddit): which
  moderator approved or removed an item, and the IDs of deleted posts and
  comments. Both are deleted automatically after 30 days.

What is kept after content is removed is the moderation record: the card's
number, the Reddit ID and link of the item, the moderators' votes, whether it
was approved or removed, by which moderator, and when.

A card that is still open keeps its content for as long as it stays open,
because the moderators have not finished with it.

## Deleted posts, comments and accounts

When a post or comment is deleted on Reddit, by its author or by Reddit, the
app is told, and the bot removes that item's content from Slack and from its
database the next time it checks, normally within a minute. This applies to
open cards as well as closed ones.

Reddit does not tell an app when an account is deleted. The 30-day limit above
is what ensures a deleted account's username and content do not remain: they
are removed 30 days after the card is closed, whether or not the account still
exists. Modmail is covered by the same limit.

## Who it is shared with

Nobody outside the moderator team. The data goes from Reddit to the operator's
server and to the team's private Slack workspace, and nowhere else. It is not
sold, not used for advertising, and not used to train any model.

## Security

Requests to the Devvit app require a secret token held by the operator. If the
tool or its token is compromised, the operator will revoke the token, notify
Reddit and the affected moderator teams, and record the incident in this
repository.

## Removal

To ask for the copy held by this tool to be removed sooner, contact the
subreddit's moderators by modmail, or open an issue at
<https://github.com/terevos/terevosmodbot/issues>.

## Changes

Changes to this policy are published in this file, with the date above
updated.
