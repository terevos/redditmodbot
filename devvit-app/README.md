# ReformedBot

## Overview

**What it does.** ReformedBot lets a moderator team work through their subreddit's mod queue and modmail from Slack. Each reported post or comment, and each modmail conversation, appears in the team's private Slack channel as a card. Moderators vote on what should happen, mark things done, and see at a glance what is still waiting.

**Who it is for.** Moderator teams who already coordinate in Slack and want their Reddit moderation work to show up there. It is published as two apps, `reformedautomodv2` (for r/Reformed) and `wcgwautomodv2` (for r/WhatCouldGoWrong), which are the same app under two names so that each subreddit is served by its own bot account.

**How it works.** There are two parts:

1. **This app**, installed on the subreddit. It reads the mod queue and modmail on the moderators' behalf.
2. **A Slack bot**, a separate program that the moderator team runs on a computer of their own. It asks this app what is new every 30 seconds and posts it to Slack.

The app has nothing to look at on Reddit: no posts, no comments, no custom pages. Its only visible part is one entry in the subreddit's moderator menu.

### Critical operational notes

- **The app does nothing by itself.** Without the Slack bot running and connected, installing it has no effect.
- **It needs Reddit's approval for "external endpoints".** The Slack bot reaches the app from outside Reddit, which is a limited-access feature Reddit enables per app. Until it is enabled, the bot cannot connect.
- **It sends moderation data off Reddit.** Mod queue items, report reasons, modmail messages and the usernames involved are sent to the team's Slack bot and posted in their private Slack channels. Install it only if your team is comfortable with that. See the [privacy policy](https://github.com/terevos/terevosmodbot/blob/main/PRIVACY.md) and [terms](https://github.com/terevos/terevosmodbot/blob/main/TERMS.md).
- **It only reaches the people you let in.** Requests to the app must carry a secret token that the app's owner creates. Anyone holding that token can read the subreddit's mod queue and modmail, so treat it like a password.
- **It is read-only. It changes nothing on Reddit.** The app only reads. It never approves, removes, bans, locks, archives, messages, posts or comments, and no button in Slack does any of those things either. Code for such actions exists but is switched off, and the app refuses every request for one. Moderators act on Reddit as they always have, and Slack follows.
- **It asks for full moderator permissions**, including mail, because reading the mod queue and modmail requires them.
- **Copies of content do not outlive the original.** When a post or comment is deleted on Reddit, the bot removes its text and author from the Slack card and from its own records, normally within a minute. Every card also loses its content 30 days after it is closed, modmail included. What remains is the moderation record: the card's number, the votes, and who approved or removed the item.
- **What it stores on Reddit:** which moderator approved or removed an item, so the Slack card can credit them, and the IDs of deleted posts and comments, so their copies can be removed. Both are deleted automatically after 30 days.

## What the app reads

| What | Why |
|---|---|
| The mod queue (reported and filtered posts and comments, with report reasons) | To post each item to Slack |
| Individual posts and comments from the queue | To learn whether an item was approved or removed, and by whom |
| Modmail conversations and their messages | To post each conversation and its replies to Slack |
| The subreddit's moderator list | To tell a moderator's modmail reply from a user's |
| Moderator actions (approve, remove, mark as spam) | To record who resolved an item |
| Deletions of posts and comments (IDs only) | To remove the copy of anything deleted on Reddit |

## Setting it up

Setup takes a moderator with full permissions and someone able to run the Slack bot. The full walkthrough for the Slack side, with a sample configuration file, is in the [project README](https://github.com/terevos/terevosmodbot#setup).

1. **Install the app** on your subreddit from its page on [developers.reddit.com](https://developers.reddit.com), and grant the permissions it asks for.
2. **Get the app's address.** On your subreddit, open the subreddit's "…" menu and choose **ReformedBot: show endpoint URL**. A short message shows the address for your subreddit's install. Copy it. If it says "unavailable", external endpoints have not been enabled for the app yet.
3. **Get a token.** The app's owner creates a *managed app token* in the app's Developer Settings on developers.reddit.com.
4. **Set up the Slack bot.** Create a Slack app from the manifest in the project, then put the address, the token, your two Slack channels (one for reports, one for modmail) and your moderators' Slack user IDs into the bot's `slack.ini` file.
5. **Start the bot.** Items waiting in the mod queue and open modmail conversations appear in Slack within a minute.

There are no settings to change on Reddit. Everything is configured in the Slack bot's `slack.ini`:

| Setting | What it controls |
|---|---|
| Report channel and modmail channel | Where each kind of card is posted |
| `CONTROLS = vote` | Report cards get the voting menu (the default). Leave it empty for cards with only a Done button |
| `[Mods]` | Which Slack users may use the buttons |

## Using it

Everything below happens in Slack, and none of it changes anything on Reddit. Only the Slack users your team listed as moderators can use the controls; anyone else gets a private "not authorized" notice.

### Reports

Each reported post or comment becomes a numbered card (`#12 · post by u/someone`) showing the content, a link to it on Reddit, and the report reasons.

- **Cast vote…** Choose Approve, Remove, Discuss, Remove + Ban, Lock, Warn, Spam and so on. Votes are a discussion aid: they are recorded in Slack, show the team's view on the card, and **do not do anything on Reddit**. Picking a vote again withdraws it, and opposite votes (Approve and Remove) cancel each other.
- **Act on Reddit as usual.** Approve or remove the item on Reddit. Within a minute the card marks itself done and names the moderator who handled it.
- **Done.** Closes the card by hand, in Slack only.
- **Re-open.** Brings a closed card back with its controls.

A card with a Ban vote on it stays open after the post is removed, as a reminder that the ban is still undecided.

A card whose post or comment has been deleted on Reddit reads *Deleted on Reddit — content removed*. Thirty days after any card is closed, its content is replaced by *Content removed 30 days after closing*. In both cases the card keeps its number, votes, status and link.

### Modmail

Each conversation becomes a lettered card (`#A · u/someone · Subject`), and later replies appear as a thread beneath it.

- **Done.** Closes the card in Slack only. This is the card's one control.
- **Reply, archive or mute on Reddit as usual.** Slack shows what happened.

A closed conversation re-opens on its own when the user writes back. Archiving a conversation on Reddit closes its card too. Thirty days after a conversation is closed, the bot removes the subject, usernames and message text from its card and its thread.

### Status message

The last message in each channel is a live summary: how many reports are still pending, which have three or more Approve or Remove votes and are ready to be acted on, and which modmail conversations are open. The **Items I haven't voted on** button shows you, privately, the open reports still waiting for your vote.

## Removing it

Uninstall the app from your subreddit's installed apps page. The Slack bot can no longer reach the subreddit from that moment. What the app stored on Reddit expires on its own within 30 days at the latest. Cards already posted in Slack stay there; if the bot keeps running it still removes their content 30 days after they were closed, but it can no longer learn of deletions on Reddit.

## Troubleshooting

| Problem | Likely cause |
|---|---|
| The menu item says the address is "unavailable" | Reddit has not yet enabled external endpoints for the app |
| Nothing appears in Slack | The Slack bot is not running, or its address or token is wrong |
| The bot refuses to start, naming a different subreddit | An address was entered under the wrong subreddit in `slack.ini` |
| An old card's Archive or Unarchive button says it was withdrawn | Those buttons were removed; archive the conversation on Reddit and the card follows |
| A card never names who approved or removed an item | The item was deleted by its author or caught by Reddit's filters, so no moderator handled it |

## Support and source

- Questions and bug reports: <https://github.com/terevos/terevosmodbot/issues>
- Source code (GPL-3.0): <https://github.com/terevos/terevosmodbot>
- [Privacy policy](https://github.com/terevos/terevosmodbot/blob/main/PRIVACY.md) · [Terms of use](https://github.com/terevos/terevosmodbot/blob/main/TERMS.md)
