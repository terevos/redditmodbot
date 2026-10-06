# RedditModBot for Slack

## Overview

**What it does.** This app lets a moderator team work through their subreddit's mod queue and modmail from Slack. Each reported post or comment, and each modmail conversation, appears in the team's private Slack channel as a card. Moderators vote on what should happen, mark things done, and see at a glance what is still waiting.

**Who it is for.** Moderator teams who already coordinate in Slack and want their Reddit moderation work to show up there. It is published as two apps, `reformedautomodv2` (for r/Reformed) and `wcgwautomodv2` (for r/WhatCouldGoWrong), which are the same app under two names so that each subreddit is served by its own bot account.

**How it works.** There are two parts:

1. **This app**, installed on the subreddit. It reads the mod queue and modmail on the moderators' behalf.
2. **A Slack bot**, a separate program that the moderator team runs on a computer of their own. It asks this app what is new every 30 seconds and posts it to Slack.

The app has nothing to look at on Reddit: no posts, no comments, no custom pages. Its only visible part is one entry in the subreddit's moderator menu.

### Critical operational notes

- **The app does nothing by itself.** Without the Slack bot running and connected, installing it has no effect.
- **It needs Reddit's approval for "external endpoints".** The Slack bot reaches the app from outside Reddit, which is a limited-access feature Reddit enables per app. Until it is enabled, the bot cannot connect.
- **It sends moderation data off Reddit.** Mod queue items, report reasons, modmail messages and the usernames involved are sent to the team's Slack bot and posted in their private Slack channels. Install it only if your team is comfortable with that. See the [privacy policy](https://github.com/terevos/redditmodbot/blob/main/PRIVACY.md) and [terms](https://github.com/terevos/redditmodbot/blob/main/TERMS.md).
- **It only reaches the people you let in.** Requests to the app must carry a secret token that the app's owner creates. Anyone holding that token can read the subreddit's mod queue and modmail, so treat it like a password.
- **It changes almost nothing on Reddit.** The one thing it can do is archive or unarchive a modmail conversation, and only when a moderator clicks that button in Slack. It never approves, removes, bans, locks, messages, posts or comments. Those actions exist in the code but are switched off, and the app refuses them.
- **It asks for full moderator permissions**, including mail, because reading the mod queue and modmail requires them.
- **What it stores on Reddit:** a short note of which moderator approved or removed an item, so the Slack card can credit them. Each note is deleted automatically after 30 days.

## What the app reads

| What | Why |
|---|---|
| The mod queue (reported and filtered posts and comments, with report reasons) | To post each item to Slack |
| Individual posts and comments from the queue | To learn whether an item was approved or removed, and by whom |
| Modmail conversations and their messages | To post each conversation and its replies to Slack |
| The subreddit's moderator list | To tell a moderator's modmail reply from a user's |
| Moderator actions (approve, remove, mark as spam) | To record who resolved an item |

## Setting it up

Setup takes a moderator with full permissions and someone able to run the Slack bot. The full walkthrough for the Slack side, with a sample configuration file, is in the [project README](https://github.com/terevos/redditmodbot#setup).

1. **Install the app** on your subreddit from its page on [developers.reddit.com](https://developers.reddit.com), and grant the permissions it asks for.
2. **Get the app's address.** On your subreddit, open the subreddit's "…" menu and choose **ReformedBot: show endpoint URL**. A short message shows the address for your subreddit's install. Copy it. If it says "unavailable", external endpoints have not been enabled for the app yet.
3. **Get a token.** The app's owner creates a *managed app token* in the app's Developer Settings on developers.reddit.com.
4. **Set up the Slack bot.** Create a Slack app from the manifest in the project, then put the address, the token, your two Slack channels (one for reports, one for modmail) and your moderators' Slack user IDs into the bot's `slack.ini` file.
5. **Start the bot.** Items waiting in the mod queue and open modmail conversations appear in Slack within a minute.

There are no settings to change on Reddit. Everything is configured in the Slack bot's `slack.ini`:

| Setting | What it controls |
|---|---|
| Report channel and modmail channel | Where each kind of card is posted |
| `CONTROLS = vote` | Report cards get the voting menu (the default) |
| `CONTROLS = actions` | Modmail cards get Archive / Unarchive buttons |
| `[Mods]` | Which Slack users may use the buttons |

## Using it

Everything below happens in Slack. Only the Slack users your team listed as moderators can use the controls; anyone else gets a private "not authorized" notice.

### Reports

Each reported post or comment becomes a numbered card (`#12 · post by u/someone`) showing the content, a link to it on Reddit, and the report reasons.

- **Cast vote…** Choose Approve, Remove, Discuss, Remove + Ban, Lock, Warn, Spam and so on. Votes are a discussion aid: they show the team's view on the card and **do not do anything on Reddit**. Picking a vote again withdraws it, and opposite votes (Approve and Remove) cancel each other.
- **Act on Reddit as usual.** Approve or remove the item on Reddit. Within a minute the card marks itself done and names the moderator who handled it.
- **Done.** Closes the card by hand, in Slack only.
- **Re-open.** Brings a closed card back with its controls.

A card with a Ban vote on it stays open after the post is removed, as a reminder that the ban is still undecided.

### Modmail

Each conversation becomes a lettered card (`#A · u/someone · Subject`), and later replies appear as a thread beneath it.

- **Done.** Closes the card in Slack only.
- **Archive / Unarchive.** Archives or restores the conversation on Reddit for the whole team. This is the only button that changes anything on Reddit, and it appears only if your team turned on `CONTROLS = actions`.

A closed conversation re-opens on its own when the user writes back. Archiving a conversation on Reddit closes its card too.

### Status message

The last message in each channel is a live summary: how many reports are still pending, which have three or more Approve or Remove votes and are ready to be acted on, and which modmail conversations are open. The **Items I haven't voted on** button shows you, privately, the open reports still waiting for your vote.

## Removing it

Uninstall the app from your subreddit's installed apps page. The Slack bot can no longer reach the subreddit from that moment. The notes the app stored on Reddit expire on their own within 30 days at the latest. Cards already posted in Slack stay there, and the bot's own records stay on the computer running it until your team deletes them.

## Troubleshooting

| Problem | Likely cause |
|---|---|
| The menu item says the address is "unavailable" | Reddit has not yet enabled external endpoints for the app |
| Nothing appears in Slack | The Slack bot is not running, or its address or token is wrong |
| The bot refuses to start, naming a different subreddit | An address was entered under the wrong subreddit in `slack.ini` |
| Archive does nothing | The app lacks the modmail permission; reinstall and grant full permissions |
| A card never names who approved or removed an item | The item was deleted by its author or caught by Reddit's filters, so no moderator handled it |

## Support and source

- Questions and bug reports: <https://github.com/terevos/redditmodbot/issues>
- Source code (GPL-3.0): <https://github.com/terevos/redditmodbot>
- [Privacy policy](https://github.com/terevos/redditmodbot/blob/main/PRIVACY.md) · [Terms of use](https://github.com/terevos/redditmodbot/blob/main/TERMS.md)
