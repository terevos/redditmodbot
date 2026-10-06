"""Removing content Reddit's rules say must not be kept: anything deleted on
Reddit, and anything closed for longer than the retention window."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

import reformed_listener as L
from conftest import CHANNEL, MAIL_CHANNEL
from reddit_actions import RedditActions

DAY = 86400
LINK = "https://reddit.com/r/reformed/comments/p1/a_title_with_words/c1/"
BODY = "the words the author wrote"


def card(item_id: str = "a1", author: str = "someuser", done: bool = False) -> List[Dict[str, Any]]:
    """A modqueue card the way the bot posts one, open or done."""
    status = " · ✅ DONE — terevos2" if done else ""
    blocks: List[Dict[str, Any]] = [
        RedditActions.header_block(f"#7 · comment by u/{author}{status}"),
        {"type": "section", "text": {"type": "mrkdwn", "text": f"<{LINK}|View on Reddit>\n*User:* u/{author}\n_ {BODY} _\n*Reports:*\n• User: Rule 2"}},
        {"type": "section", "block_id": f"vote_tally_{item_id}", "text": {"type": "mrkdwn", "text": "*Votes:* none"}},
        {"type": "divider"},
    ]
    if done:
        blocks += [
            {"type": "section", "text": {"type": "mrkdwn", "text": RedditActions.done_marker_text()}},
            {"type": "actions", "block_id": f"reopen_{item_id}", "elements": []},
        ]
    else:
        blocks.append({"type": "actions", "block_id": f"actions_{item_id}", "elements": []})
    return blocks


def log_item(actions: RedditActions, slack: Any, item_id: str = "a1", ts: str = "900.0", done_at: Optional[float] = None) -> None:
    """Record an item as posted, with its card in Slack and cached in the log."""
    blocks = card(item_id, done=done_at is not None)
    entry: Dict[str, Any] = {"queue_num": 7, "item_type": "comment", "author": "someuser", "report_link": LINK,
                             "slack_ts": ts, "slack_blocks": blocks, "votes": {"U1": ["remove"]}}
    if done_at is not None:
        entry["done_at"] = done_at
    data = actions.get_modqueue_file()
    data.setdefault(CHANNEL, {})[item_id] = entry
    actions.write_modqueue_file(data)
    slack.seed_message(ts, blocks)


def text_of(blocks: Any) -> str:
    """Everything a set of blocks would show, as one string."""
    return json.dumps(blocks, ensure_ascii=False)


def test_a_card_closed_past_the_window_loses_its_content_and_keeps_its_record(feed: Any, actions: RedditActions, slack: Any) -> None:
    log_item(actions, slack, done_at=time.time() - 31 * DAY)

    assert L._scrub_due_content(slack, feed) == 1

    shown = slack.last_update()["blocks"]
    assert BODY not in text_of(shown) and "someuser" not in text_of(shown) and "a_title_with_words" not in text_of(shown)
    assert shown[0]["text"]["text"] == "#7 · comment · ✅ DONE — terevos2"
    assert "/comments/p1/_/c1/" in text_of(shown), "the card still links to the item"
    assert {b.get("block_id") for b in shown} >= {"vote_tally_a1", "reopen_a1"}, "tally and controls survive"

    entry = actions.get_item_info(CHANNEL, "a1")
    assert "author" not in entry and entry["scrubbed_at"]
    assert BODY not in text_of(entry) and "someuser" not in text_of(entry)
    assert entry["queue_num"] == 7 and entry["votes"] == {"U1": ["remove"]}

    slack.updated.clear()
    assert L._scrub_due_content(slack, feed) == 0, "a scrubbed entry is not scrubbed again"
    assert not slack.updated


def test_open_and_recently_closed_cards_are_left_alone(feed: Any, actions: RedditActions, slack: Any) -> None:
    log_item(actions, slack, "open1", ts="900.0")
    log_item(actions, slack, "recent", ts="901.0", done_at=time.time() - 29 * DAY)

    assert L._scrub_due_content(slack, feed) == 0
    assert not slack.updated
    assert actions.get_item_info(CHANNEL, "open1")["author"] == "someuser"


def test_a_deletion_on_reddit_scrubs_an_open_card_at_once(feed: Any, actions: RedditActions, slack: Any, fake_reddit: Any) -> None:
    log_item(actions, slack)
    fake_reddit.subreddit("reformed").deleted += [(5_000, "never_seen"), (6_000, "a1")]

    assert L._scrub_due_content(slack, feed) == 1

    shown = slack.last_update()["blocks"]
    assert BODY not in text_of(shown) and "Deleted on Reddit" in text_of(shown)
    assert "actions_a1" in {b.get("block_id") for b in shown}, "an open card keeps its controls"
    assert actions.get_item_info(CHANNEL, "a1")["deleted_at"]
    assert actions.store.get_meta(actions._DELETIONS_CURSOR_KEY) == "6000", "the cursor moves past what was read"


def test_deletions_are_scrubbed_ahead_of_the_backlog(feed: Any, actions: RedditActions, slack: Any, fake_reddit: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(L, "_SCRUB_BATCH", 1)
    log_item(actions, slack, "old", ts="900.0", done_at=time.time() - 90 * DAY)
    log_item(actions, slack, "gone", ts="901.0")
    fake_reddit.subreddit("reformed").deleted.append((1_000, "gone"))

    L._scrub_due_content(slack, feed)

    assert "scrubbed_at" in actions.get_item_info(CHANNEL, "gone")
    assert "scrubbed_at" not in actions.get_item_info(CHANNEL, "old"), "the batch limit holds the rest for the next poll"


def test_a_failed_edit_is_retried_rather_than_forgotten(feed: Any, actions: RedditActions, slack: Any) -> None:
    log_item(actions, slack, done_at=time.time() - 31 * DAY)
    slack.fail_with = RuntimeError("slack is down")

    L._scrub_due_content(slack, feed)
    entry = actions.get_item_info(CHANNEL, "a1")
    assert "scrubbed_at" not in entry and entry["author"] == "someuser" and entry["scrub_failures"] == 1

    slack.fail_with = None
    L._scrub_due_content(slack, feed)
    assert "scrubbed_at" in actions.get_item_info(CHANNEL, "a1")


def test_a_card_slack_will_not_let_be_edited_is_deleted(feed: Any, actions: RedditActions, slack: Any, monkeypatch: Any) -> None:
    log_item(actions, slack, done_at=time.time() - 31 * DAY)

    class Refused(Exception):
        response = {"error": "edit_window_closed"}

    def refuse(**kwargs: Any) -> None:
        raise Refused()

    monkeypatch.setattr(slack, "chat_update", refuse)
    L._scrub_due_content(slack, feed)

    assert slack.deleted == [{"channel": CHANNEL, "ts": "900.0"}]
    assert "scrubbed_at" in actions.get_item_info(CHANNEL, "a1")


def test_a_card_deleted_by_hand_is_scrubbed_from_the_store_alone(feed: Any, actions: RedditActions, slack: Any) -> None:
    log_item(actions, slack, done_at=time.time() - 31 * DAY)
    slack.history.clear()

    L._scrub_due_content(slack, feed)

    assert not slack.updated
    entry = actions.get_item_info(CHANNEL, "a1")
    assert entry["scrubbed_at"] and BODY not in text_of(entry)


def test_reopening_a_scrubbed_card_makes_it_due_again(actions: RedditActions) -> None:
    entry = {"done_at": 1.0, "scrubbed_at": 2.0}
    actions.clear_done(entry)
    assert "scrubbed_at" not in entry


def test_a_closed_conversation_loses_its_card_text_and_its_replies(feed: Any, actions: RedditActions, slack: Any) -> None:
    blocks = actions._build_modmail_blocks("cv1", "m1", "someuser", "Ban appeal", BODY, "2026-07-29", conv_num=1)
    blocks[0] = actions.header_block("#A · u/someuser · Ban appeal · :completed: DONE — terevos2")
    root = slack.chat_postMessage(channel=MAIL_CHANNEL, blocks=blocks, text="#A. Modmail from u/someuser: Ban appeal")["ts"]
    reply = slack.chat_postMessage(
        channel=MAIL_CHANNEL, thread_ts=root, text="#A. Modmail from u/someuser: Ban appeal",
        blocks=actions._build_modmail_blocks("cv1", "m2", "someuser", "Ban appeal", "a second message", "2026-07-30", include_actions=False, is_reply=True),
    )["ts"]
    note = slack.chat_postMessage(channel=MAIL_CHANNEL, thread_ts=root, text=":file_cabinet: Archived on Reddit")["ts"]
    actions.write_modmail_file({MAIL_CHANNEL: {"modmail_conv": {"cv1": {
        "conv_num": 1, "subject": "Ban appeal", "author": "someuser", "slack_ts": root,
        "done_at": time.time() - 31 * DAY, "messages": {"m1": True, "m2": True},
    }}}})

    assert L._scrub_due_content(slack, feed) == 1

    updates = {u["ts"]: u for u in slack.updated}
    assert set(updates) == {root, reply}, "the thread note is the bot's own words and stays"
    assert note not in updates
    for update in updates.values():
        shown = text_of(update["blocks"]) + update["text"]
        assert BODY not in shown and "second message" not in shown and "someuser" not in shown and "Ban appeal" not in shown
    assert updates[root]["blocks"][0]["text"]["text"] == "#A · :completed: DONE — terevos2"

    done_button = [b for b in updates[root]["blocks"] if b.get("type") == "actions"][0]["elements"][-1]
    assert done_button["value"] == "mail|cv1|", "the control still parses, without the name"

    conv = actions.get_conv_info(MAIL_CHANNEL, "cv1")
    assert "subject" not in conv and "author" not in conv and conv["scrubbed_at"]
    assert conv["messages"] == {"m1": True, "m2": True}, "message IDs stay, or the thread would be posted again"

    slack.updated.clear()
    assert L._scrub_due_content(slack, feed) == 0


def test_exports_and_archives_are_written_without_content(feed: Any, actions: RedditActions, slack: Any) -> None:
    log_item(actions, slack)
    actions.write_modmail_file({MAIL_CHANNEL: {"modmail_conv": {"cv1": {"conv_num": 1, "subject": "Ban appeal", "author": "someuser", "messages": {"m1": True}}}}})

    written = actions.export_logs()
    actions.roll_log(actions.KIND_QUEUE, CHANNEL, 1)
    written += [os.path.join(actions.archive_dir, f) for f in os.listdir(actions.archive_dir)]

    assert len(written) == 3
    for path in written:
        with open(path) as f:
            content = f.read()
        assert BODY not in content and "someuser" not in content and "Ban appeal" not in content and "a_title_with_words" not in content, path
    with open(written[0]) as f:
        exported = json.load(f)[CHANNEL]["a1"]
    assert exported["queue_num"] == 7 and exported["votes"] == {"U1": ["remove"]}
    assert actions.get_item_info(CHANNEL, "a1")["author"] == "someuser", "the live store is untouched by an export"


def test_files_written_before_this_are_scrubbed_once(actions: RedditActions) -> None:
    os.makedirs(actions.export_dir, exist_ok=True)
    os.makedirs(actions.archive_dir, exist_ok=True)
    entry = {"queue_num": 7, "author": "someuser", "report_link": LINK, "slack_blocks": card()}
    paths = {
        os.path.join(actions.export_dir, "modqueue-20260101.json"): {CHANNEL: {"a1": entry}},
        os.path.join(actions.archive_dir, f"modqueue-{CHANNEL}-cycle001-20260101-000000.json"): {"archived_at": 1.0, "kind": "modqueue", "entries": {"a1": entry}},
        os.path.join(actions.export_dir, "modmail-20260101.json"): {MAIL_CHANNEL: {"modmail_conv": {"cv1": {"conv_num": 1, "subject": "Ban appeal", "author": "someuser"}}}},
        os.path.join(actions.log_dir, "modqueue.json"): {CHANNEL: {"a1": entry}, "C_OTHER_FEED": {"b2": entry}},
    }
    for path, data in paths.items():
        with open(path, "w") as f:
            json.dump(data, f)

    assert sorted(actions.scrub_log_files()) == sorted(paths)
    for path in paths:
        with open(path) as f:
            content = f.read()
        assert BODY not in content and "someuser" not in content and "Ban appeal" not in content, path
    assert actions.scrub_log_files() == [], "nothing left to rewrite"


def test_an_unhandled_error_logs_identifiers_not_the_card(caplog: Any) -> None:
    body = {"type": "block_actions", "user": {"id": "U1"}, "channel": {"id": CHANNEL},
            "actions": [{"action_id": "mark_done"}], "message": {"blocks": card()}}
    with caplog.at_level("ERROR"):
        L.handle_error(RuntimeError("boom"), body)
    assert "mark_done" in caplog.text and "U1" in caplog.text
    assert BODY not in caplog.text and "someuser" not in caplog.text
