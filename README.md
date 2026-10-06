# ReformedBot

A Slack bot that surfaces Reddit moderation activity directly in Slack, so mods can discuss and triage it there rather than in the Reddit modqueue.

It comes in two parts:

- **The bot** (Python, this directory) — talks to Slack, keeps the state, and runs on a machine of yours.
- **The Devvit app** (`devvit-app/`, TypeScript) — installed on each subreddit, runs on Reddit's Developer Platform, and is the bot's only route to Reddit. The bot holds no Reddit credentials; it calls the app with a token.

Any number of subreddits can be served at once. Each gets its own pair of Slack channels (one for mod reports, one for modmail), its own numbering, and its own status messages; see [Configuration Files](#configuration-files).

---

## Mod Reports

New reported submissions and comments are automatically posted to the modqueue channel as rich cards containing the item number, type, author, content, and all report reasons.

### Voting

Each report card has a **Vote dropdown** for non-binding discussion before taking action:

| Option | Notes |
|--------|-------|
| ✅ Approve | Cancels any Remove, Remove + Ban, or Spam votes |
| ❌ Remove | Cancels any Approve vote |
| 💭 Discuss | |
| 🤷 Meh | |
| 🎉 Remove + Ban | Cancels any Approve vote |
| 🔒 Lock | |
| 🐚 Warn | |
| 🥫 Spam | Cancels any Approve vote |
| ❓ Huh? | |

- Each mod can hold multiple votes simultaneously
- Selecting a vote you already cast toggles it off
- Opposing votes (e.g. Approve vs. Remove) automatically cancel each other
- The live tally updates immediately on the card, showing each option with a count and voter names

Votes are for mod discussion only — they do not automatically take action on Reddit.

### Closing a report out

Report cards take no action on Reddit. Approve, remove, warn, and ban happen on Reddit itself; the card is how the mods decide and keep track.

- **Done** — Marks the item resolved in Slack. Every card has this button.
- Or do nothing: once the item leaves the Reddit modqueue, the next poll marks the card done on its own and the header names who approved or removed it.

Either way the card is updated in place: dropdowns are removed, a status header is added (e.g. `✅ DONE — username`), and a `:completed: DONE :completed:` marker appears at the bottom. A **Re-open** dropdown also appears to restore the full interactive card if needed.

One exception to the auto-done: while any mod holds a **Ban** vote the card is kept open, since leaving the modqueue does not settle the question that vote is asking. The header says what Reddit did and the card keeps its controls, so Done still closes it.

### Report Summaries

Every 5 minutes the bot updates a single status message at the bottom of the channel with what is still pending:

```
🕐 3 item(s) still pending: #1 | #3 | #7
🗳 Items with 3+ votes: #1 ❌3 | #7 ✅4
```

Each number links directly to its Slack message. The pending count links to the subreddit's Reddit modqueue. If nothing is queued on Reddit and no card is still open: `✅ Mod queue is clear.` If nothing is queued but a card is still open here — a **Ban** vote holds one open — the summary names what is left rather than claiming the queue is clear. Duplicate summaries are suppressed if the state hasn't changed.

The second line appears once an item has collected **three or more Approve or Remove votes** — the mods have agreed, and somebody needs to act on Reddit. A Spam vote counts as a Remove. An item that has gone both ways is listed twice, so a split is visible rather than hidden. Items held open after leaving the modqueue (a Ban vote) are included, so this line can appear under an otherwise-clear queue.

Below the summary is an **Items I haven't voted on** button. The list it returns is different for every mod — it shows only the open items *you* have not voted on — and only you see it. Nothing is posted to the channel.

---

## Modmail

New modmail conversations are posted as top-level messages in the modmail channel and assigned a sequential `#N` number. Replies within the same conversation are posted as **thread replies**, keeping each conversation together. Auto-generated Reddit messages (mod invitations, approved-user additions, etc.) are silently skipped.

### Actions

The controls sit on the conversation's own card, not on its thread replies:

- **Done** — Marks the conversation resolved in Slack alone, leaving Reddit untouched. Always present.
- **Archive** — Archives the conversation on Reddit for the whole mod team, and marks it **done**. Replaced afterwards by a single **Unarchive** option, which puts the conversation and its controls back. Offered only on a subreddit configured for `CONTROLS = actions`.

### Done and Re-opened

A conversation is marked **done** when any of the following occur:

| Trigger | How |
|---|---|
| Mod marks it done in Slack | Done button |
| Mod archives via bot | Archive button |
| Archived directly on Reddit | Detected on next poll |

When done, the top-level message gains a status header and `:completed: DONE :completed:` marker.

A conversation is **re-opened** when a new message arrives from a non-mod. The new message is posted as a thread reply and the top-level message is updated to show `🔄 REOPENED`. Unarchiving via the bot also re-opens the conversation and restores its controls.

### Modmail Summaries

Every 5 minutes the bot posts a summary of all open conversations:

```
💬 2 open modmail thread(s):
• #1 u/username — Subject line
• #3 u/other_user — Another subject
```

Each entry links directly to the Slack thread. If all conversations are resolved: `:white_check_mark: All modmail conversations are resolved.` Duplicate summaries are suppressed if the open set hasn't changed.

---

## Authorization

Only Slack users listed in the `[Mods]` section of `slack.ini` can use a card's controls. Unauthorized clicks receive a private ephemeral error visible only to them.

`[Mods]` applies to every subreddit the bot serves. To authorize someone for one subreddit alone, list them in `[Mods:<subreddit>]` instead — they can then act on that subreddit's channels and nowhere else. A message must also live in a configured feed channel; a click in any other channel is ignored.

---

## Setup

### Requirements

- Python 3.13
- `requests` and `slack-bolt` (see `requirements.txt`)
- Node 24 or newer, for building and uploading the Devvit app

Install with pipenv:

```
pipenv install
```

Or with pip:

```
pip install -r requirements.txt
```

### The Devvit app

The app is the bot's Reddit backend. It needs setting up once, and installing once per subreddit.

Its own README, [`devvit-app/README.md`](devvit-app/README.md), is the moderator-facing description Reddit shows on the app's page and reads at app review.

```
cd devvit-app
npm install
npx devvit login          # opens a browser
npm test                  # type-check, unit tests, build
npm run upload            # builds and uploads the app
```

1. **Pick the app name.** `name` in `devvit-app/devvit.json` (`reformedautomodv2`) becomes the app's Reddit account and must be unique on the platform; change it before the first upload if it is taken. `devvit.wcgw.json` is the same app under a second name (`wcgwautomodv2`), uploaded with `npm run upload:wcgw`.
2. **Get external endpoints enabled.** The bot calls the app from outside Reddit, which uses Devvit's *external endpoints* — an experimental, limited-access feature that Reddit has to approve for the app. Nothing below works until that is granted.
3. **Install the app** on each subreddit, from the app's page on developers.reddit.com. It needs full moderator permissions, mail included.
4. **Create a managed app token** in the app's Developer Settings. That is `DEVVIT_TOKEN`; one token covers every install of that app.
5. **Find each install's URL**: in the subreddit's mod menu, *ReformedBot: show endpoint URL*. That is the subreddit's `DEVVIT_URL`. (It is also logged when the app is installed or upgraded: `npx devvit logs <subreddit>`.)

`npm run playtest` runs the app against a test subreddit with live reload.

### Configuration

**`slack.ini`** — Copy from `slack.ini.example` and fill in:

```ini
[Default]
API_TOKEN = xoxb-your-bot-token-here
APP_TOKEN = xapp-your-app-level-token-here
SIGNING_SECRET = your-signing-secret-here
POLL_INTERVAL = 30
DEVVIT_TOKEN = devvit_at_your-managed-token-here

[Subreddit:reformed]
MODQUEUE_CHANNEL = mod_actions
MODMAIL_CHANNEL  = mod_mail
CONTROLS         = vote
DEVVIT_URL       = https://reformedautomodv2-2th52-external.devvit.net/external/

[Subreddit:whatcouldgowrong]
MODQUEUE_CHANNEL = wcgw_reports
MODMAIL_CHANNEL  = wcgw_mail
CONTROLS         = vote, actions
DEVVIT_URL       = https://wcgwautomodv2-2qh1i-external.devvit.net/external/

[Mods]
U0123456789 = reddit_username
UABCDEFGHIJ = another_mod

[Mods:whatcouldgowrong]
UZYXWVUTSRQ = wcgw_only_mod
```

One `[Subreddit:<name>]` section per subreddit; add a section to add a subreddit. Each is reached through the Devvit app's install on that subreddit, at its `DEVVIT_URL`. At startup the bot asks each install which subreddit it serves, and refuses to run if a URL has been put under the wrong section. Reddit sees the bot's actions as the app's own account.

To act on one subreddit as a different Reddit account, upload the app a second time under another name (a copy of `devvit.json` with its own `name`, passed as `devvit upload --config <file>`), install that app there, and give the subreddit's section its own `DEVVIT_TOKEN` — a token belongs to one app, and a section's token wins over `[Default]`'s.

`CONTROLS` picks which controls that subreddit's cards carry: `vote` for the Cast vote… dropdown on report cards, `actions` for Archive/Unarchive on modmail cards, comma-separated for both. Omit the key for `vote`. A `CONTROLS` in `[Default]` applies to every subreddit that does not set its own. The Done button is not part of the choice — every card has one.

Channel values may be a channel name (`mod_actions`) or a Slack channel ID (`C0123456789`); names are resolved to IDs when the bot starts. For a private channel, invite the bot to it first or the lookup will fail. Leave a channel blank to disable auto-posting for that category.

The pre-multi-subreddit layout — a bare `[Channels]` section, with the subreddit taken from `[Default] SUBREDDIT` (default: `reformed`) — is still read when no `[Subreddit:...]` section exists, so an existing config keeps working unchanged.

### Slack App

Import `slack_app_manifest.yaml` into your Slack app configuration. The bot uses **Socket Mode** — no public HTTP endpoint is required.

Required OAuth scopes:
- `chat:write` — post messages
- `channels:history` / `groups:history` / `im:history` / `mpim:history` — read messages for commands
- `channels:read` / `groups:read` — look up channel info

### Running

```
python reformed_listener.py
```

> **Avoid `pipenv shell`** — it spawns a subshell that can break terminal input. Instead activate the virtualenv directly:
> ```
> source $(pipenv --venv)/bin/activate
> ```
> Or run without activating:
> ```
> pipenv run python reformed_listener.py
> ```

The bot prevents duplicate instances using a pidfile (`reformedbot.pid`) in the project directory. Starting a second instance from the same directory will exit immediately with an error.

---

## Data Storage

Each subreddit keeps its own state in a SQLite database, so two feeds never
share a file:

| Path | Contents |
|------|----------|
| `logs/<subreddit>/modlog.db` | The store: reports, votes, modmail conversations and messages, card numbering |
| `logs/<subreddit>/archive/` | Rolled-over logs, one JSON file per cycle per channel |
| `logs/<subreddit>/export/` | Weekly JSON exports of the live store |

Everything the bot writes during a poll or a button click is a single row —
one vote, one done-stamp — rather than a rewrite of the whole log, which is
what the JSON files this replaced had to do.

A bot upgraded from either JSON layout (`logs/<subreddit>/modqueue.json`, or
the older shared `logs/modqueue.json` keyed by channel) imports each feed's
channels on the first poll after startup. The JSON files are left in place and
can be deleted once every feed has started.

### Archiving

Report numbers run `#1`–`#999` and modmail letters `#A`–`#ZZ`. Reaching the cap
writes that channel's entries to
`logs/<subreddit>/archive/modqueue-<channel>-cycle001-<timestamp>.json`, deletes
the archived rows and starts the numbering over at `#1` / `#A`. Anything still
open — and anything closed within the last 7 days, which the poll loop may still
reconcile — stays in the store, keeping its old number; the new cycle skips
numbers a carried-over card still holds, so no two cards in the channel share a
label.

### Exports

Once a week the bot writes both logs to `logs/<subreddit>/export/` as JSON, in
the same shape the old log files had, and keeps the newest 52 of each — a year
of weekly snapshots. They are the readable, greppable copy of a database that is
otherwise binary. Exports and archives hold the moderation record only, never
content (see [Content retention](#content-retention)), so a database rebuilt
from one has every card's number, votes and status but not its text or author. The
schedule is stored in the database, so restarting the bot does not restart it;
a brand-new store exports on its first poll.

An export holds the *live* store, so cycles already archived are not in it —
the archive files are the rest of the history.

### Content retention

Reddit requires that a copy of a post or comment goes when the original is
deleted, and that nothing identifying a deleted account is kept. The bot does
both without being asked:

- **Deleted on Reddit** — the Devvit app records each deletion and the bot
  reads the list every poll. The card for a deleted item has its text, author
  and title replaced by *Deleted on Reddit — content removed*, open or closed.
  A moderator's removal is not a deletion and changes nothing here.
- **Closed for 30 days** — the card's content is replaced by *Content removed
  30 days after closing*. For modmail that covers the subject, the usernames,
  and the text of every reply in the thread. Reddit sends no event for a deleted
  account, so this limit is what guarantees one leaves nothing behind.

A scrubbed card keeps its number, link, votes, status and controls, and the
database keeps the same record. Open cards are never scrubbed for age. A card
that is re-opened and rebuilt from Reddit is scrubbed again 30 days after it is
next closed.

Scrubbing is irreversible and is rationed to a few cards per poll, so the first
start after upgrading works through every card closed more than 30 days ago
over the following hours. On that start the bot also rewrites the existing
export, archive and older JSON log files without their content.

### Entry structure

The store hands entries back in the shape the JSON logs used, which is also
what the exports contain:

**Reports**

```json
{
  "CHANNEL_ID": {
    "ITEM_ID": {
      "queue_num": 1,
      "report_link": "https://reddit.com/...",
      "item_type": "submission",
      "slack_ts": "1234567890.123456",
      "slack_permalink": "https://workspace.slack.com/archives/...",
      "slack_blocks": [...],
      "votes": {
        "USLACKID": ["approve"]
      }
    }
  }
}
```

**Modmail**

```json
{
  "CHANNEL_ID": {
    "modmail_conv": {
      "CONV_ID": {
        "conv_num": 1,
        "subject": "Conversation subject",
        "author": "reddit_username",
        "status": "open",
        "slack_ts": "1234567890.123456",
        "slack_permalink": "https://workspace.slack.com/archives/...",
        "messages": {
          "MESSAGE_ID": true
        }
      }
    }
  }
}
```

---

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).
