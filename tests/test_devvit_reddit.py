"""The Devvit client: the wire format, laziness, and how failures surface."""
from __future__ import annotations

from typing import Any, Dict, List

import pytest
import requests

import devvit_reddit as D
import reformed_listener as L
from reddit_actions import RedditActions


class FakeResponse:
    """A ``requests`` response with a status and a JSON (or not) body."""

    def __init__(self, status: int = 200, body: Any = None, text: str = "") -> None:
        """Hold what the app answered."""
        self.status_code = status
        self._body = body
        self.text = text

    def json(self) -> Any:
        """Return the body, or fail the way requests does for non-JSON."""
        if self._body is None:
            raise ValueError("not json")
        return self._body


class FakeApp:
    """Stands in for ``requests.Session``, answering as the Devvit app would."""

    def __init__(self) -> None:
        """Start with no canned answers and no calls recorded."""
        self.answers: Dict[str, Any] = {}
        self.posts: List[Dict[str, Any]] = []

    @property
    def ops(self) -> List[str]:
        """The ops called, in order."""
        return [p["json"]["op"] for p in self.posts]

    def post(self, url: str, json: Dict[str, Any], headers: Dict[str, str], timeout: float) -> FakeResponse:
        """Record the call and return the canned answer for its op."""
        self.posts.append({"url": url, "json": json, "headers": headers})
        answer = self.answers.get(json["op"], {})
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, FakeResponse) else FakeResponse(200, answer)


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    """The call spacing is real time; the tests do not need to wait for it."""
    monkeypatch.setattr(D, "_MIN_CALL_INTERVAL", 0.0)


@pytest.fixture
def app() -> FakeApp:
    """A fake Devvit app."""
    return FakeApp()


@pytest.fixture
def reddit(app: FakeApp) -> D.DevvitReddit:
    """A session against the fake app."""
    return D.DevvitReddit("https://bot-abc-external.devvit.net/external/", "devvit_at_secret", session=app)


def thing(id: str, kind: str = "submission", **over: Any) -> Dict[str, Any]:
    """A wire ``Thing`` as the app sends one in a modqueue listing."""
    data: Dict[str, Any] = {
        "id": id, "kind": kind, "author": "someuser", "permalink": f"/r/reformed/comments/{id}",
        "created_utc": 1_700_000_000, "edited": False, "user_reports": [["Rule 2", 1]],
        "mod_reports": [["check this", "terevos2"]], "approved": False, "removed": False, "spam": False,
    }
    data.update({"body": "a comment"} if kind == "comment" else {"title": "A post", "url": "https://example.com/x"})
    data.update(over)
    return data


# ---------------------------------------------------------------------------
# The call itself
# ---------------------------------------------------------------------------

def test_a_call_posts_the_op_to_the_rpc_endpoint_with_the_token(reddit: D.DevvitReddit, app: FakeApp) -> None:
    app.answers["moderators"] = {"names": ["terevos2", "bishopofreddit"]}

    mods = reddit.subreddit("reformed").moderator()

    assert [str(m) for m in mods] == ["terevos2", "bishopofreddit"]
    assert app.posts == [{
        "url": "https://bot-abc-external.devvit.net/external/rpc",
        "json": {"op": "moderators", "args": {}},
        "headers": {"Authorization": "bearer devvit_at_secret"},
    }]


def test_unset_arguments_are_left_out_of_the_request(reddit: D.DevvitReddit, app: FakeApp) -> None:
    list(reddit.subreddit("reformed").modmail.conversations(state="archived"))
    assert app.posts[0]["json"] == {"op": "modmail_conversations", "args": {"state": "archived"}}


def test_a_5xx_is_a_server_error_the_poll_loop_recognises(reddit: D.DevvitReddit, app: FakeApp) -> None:
    app.answers["modqueue"] = FakeResponse(502, {"error": "reddit is down", "status": 502})

    with pytest.raises(D.ServerError, match="modqueue: HTTP 502: reddit is down") as caught:
        reddit.subreddit("reformed").mod.modqueue()
    assert L._is_server_error(caught.value)


def test_a_refused_token_is_an_error_but_not_a_server_error(reddit: D.DevvitReddit, app: FakeApp) -> None:
    app.answers["modqueue"] = FakeResponse(401, None, text="unauthorized")

    with pytest.raises(D.DevvitError, match="HTTP 401: unauthorized") as caught:
        reddit.subreddit("reformed").mod.modqueue()
    assert not L._is_server_error(caught.value)


def test_an_unreachable_app_is_a_devvit_error(reddit: D.DevvitReddit, app: FakeApp) -> None:
    app.answers["modqueue"] = requests.ConnectionError("no route")

    with pytest.raises(D.DevvitError, match="could not reach the Devvit app"):
        reddit.subreddit("reformed").mod.modqueue()


def test_a_non_json_answer_is_a_devvit_error(reddit: D.DevvitReddit, app: FakeApp) -> None:
    app.answers["modqueue"] = FakeResponse(200, None, text="<html>")

    with pytest.raises(D.DevvitError, match="did not answer with JSON"):
        reddit.subreddit("reformed").mod.modqueue()


def test_calls_are_spaced_to_stay_under_the_rate_limit(reddit: D.DevvitReddit, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    slept: List[float] = []

    def sleep(seconds: float) -> None:
        """Advance the fake clock instead of waiting."""
        slept.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(D, "_MIN_CALL_INTERVAL", 0.2)
    monkeypatch.setattr(D.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(D.time, "sleep", sleep)

    reddit.call("info")
    reddit.call("info")  # immediately after: has to wait out the interval
    clock[0] += 5
    reddit.call("info")  # long after: does not

    assert slept == [pytest.approx(0.2)]


def test_served_subreddit_reports_what_the_install_says(reddit: D.DevvitReddit, app: FakeApp) -> None:
    app.answers["info"] = {"subreddit": "reformed", "app": "reformedautomodv2", "version": "0.0.1"}
    assert reddit.served_subreddit() == "reformed"


# ---------------------------------------------------------------------------
# Posts and comments
# ---------------------------------------------------------------------------

def test_modqueue_items_are_the_classes_get_modqueue_branches_on(reddit: D.DevvitReddit, app: FakeApp) -> None:
    app.answers["modqueue"] = {"items": [thing("p1"), thing("c1", "comment", author=None)]}

    post, comment = list(reddit.subreddit("reformed").mod.modqueue())

    assert isinstance(post, D.Submission) and not isinstance(post, D.Comment)
    assert isinstance(comment, D.Comment)
    assert (post.id, post.title, post.url, post.author.name) == ("p1", "A post", "https://example.com/x", "someuser")
    assert (comment.body, comment.author) == ("a comment", None)
    assert post.created == post.created_utc == 1_700_000_000
    assert post.user_reports == [("Rule 2", 1)] and post.mod_reports == [("check this", "terevos2")]
    assert app.ops == ["modqueue"]  # reading listing fields fetched nothing more


def test_who_resolved_a_listed_item_costs_one_fetch(reddit: D.DevvitReddit, app: FakeApp) -> None:
    app.answers["modqueue"] = {"items": [thing("p1")]}
    app.answers["item"] = {"item": thing("p1", approved=True, approved_by="terevos2", banned_by=None)}
    (post,) = reddit.subreddit("reformed").mod.modqueue()

    assert post.approved_by.name == "terevos2"
    assert post.banned_by is None
    assert post.approved is True  # the fetch refreshed the listing's fields too
    assert app.ops == ["modqueue", "item"]


def test_an_item_by_id_is_not_fetched_until_read(reddit: D.DevvitReddit, app: FakeApp) -> None:
    app.answers["item"] = {"item": thing("c9", "comment", banned_by="AutoModerator", approved_by=None, removed=True)}

    comment = reddit.comment(id="c9")
    assert app.ops == []

    assert comment.banned_by.name == "AutoModerator"
    assert app.posts[0]["json"] == {"op": "item", "args": {"id": "c9", "kind": "comment"}}


def test_a_field_reddit_never_sends_is_an_attribute_error_after_one_fetch(reddit: D.DevvitReddit, app: FakeApp) -> None:
    app.answers["item"] = {"item": thing("p1", approved_by=None, banned_by=None)}
    post = reddit.submission(id="p1")

    assert getattr(post, "removed_by", None) is None
    assert getattr(post, "removed_by", None) is None
    assert app.ops == ["item"]


def test_moderating_an_item_needs_no_fetch(reddit: D.DevvitReddit, app: FakeApp) -> None:
    item = reddit.submission(id="p1")

    item.mod.ignore_reports()
    item.mod.approve()
    reddit.comment(id="c1").mod.remove()

    assert [p["json"] for p in app.posts] == [
        {"op": "ignore_reports", "args": {"id": "p1", "kind": "submission"}},
        {"op": "approve", "args": {"id": "p1", "kind": "submission"}},
        {"op": "remove", "args": {"id": "c1", "kind": "comment", "spam": False}},
    ]


def test_get_item_resolution_reads_through_the_client(reddit: D.DevvitReddit, app: FakeApp, tmp_path: Any) -> None:
    """The bot's own resolver, end to end against the wire format."""
    actions = RedditActions("reformed", reddit=reddit, log_dir=str(tmp_path), mod_list=["terevos2"])

    app.answers["item"] = {"item": thing("p1", approved=True, approved_by="terevos2", banned_by=None)}
    assert actions.get_item_resolution("p1", "submission") == ("terevos2", "approved")

    app.answers["item"] = {"item": thing("c1", "comment", removed=True, approved_by=None, banned_by="bishopofreddit")}
    assert actions.get_item_resolution("c1", "comment") == ("bishopofreddit", "removed")

    app.answers["item"] = {"item": thing("p2", approved_by=None, banned_by=None)}
    assert actions.get_item_resolution("p2", "submission") == ("", "")


def test_a_public_removal_message_is_a_stickied_distinguished_reply(reddit: D.DevvitReddit, app: FakeApp) -> None:
    app.answers["reply"] = {"id": "r1", "permalink": "/r/reformed/comments/p1/_/r1"}

    result = reddit.submission(id="p1").mod.send_removal_message(message="Rule 2", title="Post Removal", type="public")

    assert result is None  # a comment has no modmail link to hand back
    assert app.posts[0]["json"] == {"op": "reply", "args": {"id": "p1", "kind": "submission", "text": "Rule 2", "distinguish": True, "sticky": True}}


def test_a_private_removal_message_is_modmail_to_the_author(reddit: D.DevvitReddit, app: FakeApp) -> None:
    app.answers["item"] = {"item": thing("p1", approved_by=None, banned_by=None)}
    app.answers["modmail_create"] = {"id": "conv7"}

    result = reddit.submission(id="p1").mod.send_removal_message(message="Rule 2", title="Post Removal", type="private")

    assert result.id == "conv7"
    assert app.posts[-1]["json"] == {"op": "modmail_create", "args": {"subject": "Post Removal", "body": "Rule 2", "to": "someuser"}}


# ---------------------------------------------------------------------------
# Modmail
# ---------------------------------------------------------------------------

def conversation(id: str, **over: Any) -> Dict[str, Any]:
    """A wire ``ModmailConversation`` as a listing sends one."""
    data: Dict[str, Any] = {
        "id": id, "subject": "Ban appeal", "is_auto": False, "state": "New",
        "messages": [{"id": f"{id}m1", "author": "someuser", "body_markdown": "please", "date": "2026-10-01T12:00:00Z"}],
    }
    data.update(over)
    return data


def test_a_listed_conversation_carries_its_messages(reddit: D.DevvitReddit, app: FakeApp) -> None:
    app.answers["modmail_conversations"] = {"conversations": [conversation("a"), conversation("b", is_auto=True)]}

    first, second = list(reddit.subreddit("reformed").modmail.conversations())

    assert (first.id, first.subject, first.is_auto, second.is_auto) == ("a", "Ban appeal", False, True)
    message = first.messages[0]
    assert (message.id, str(message.author), message.body_markdown, message.date) == ("am1", "someuser", "please", "2026-10-01T12:00:00Z")
    assert app.ops == ["modmail_conversations"]


def test_mod_actions_cost_one_fetch_and_are_numbered_as_the_bot_expects(reddit: D.DevvitReddit, app: FakeApp) -> None:
    app.answers["modmail_conversations"] = {"conversations": [conversation("a")]}
    app.answers["modmail_conversation"] = {"conversation": conversation("a", mod_actions=[
        {"action_type": "Archived", "date": "2026-10-01T13:00:00Z", "author": "bishopofreddit"},
        {"action_type": "Unarchived", "date": "2026-10-01T14:00:00Z", "author": "terevos2"},
        {"action_type": "SomethingNew", "date": "2026-10-01T15:00:00Z", "author": "terevos2"},
    ])}
    (conv,) = reddit.subreddit("reformed").modmail.conversations()

    assert RedditActions._last_action_author(conv, RedditActions._ACTION_ARCHIVED) == "bishopofreddit"
    assert RedditActions._last_action_author(conv, RedditActions._ACTION_UNARCHIVED) == "terevos2"
    assert [a.action_type_id for a in conv.mod_actions] == [2, 3, -1]
    assert app.ops == ["modmail_conversations", "modmail_conversation"]


def test_a_failed_conversation_fetch_loses_the_attribution_not_the_poll(reddit: D.DevvitReddit, app: FakeApp) -> None:
    app.answers["modmail_conversations"] = {"conversations": [conversation("a")]}
    app.answers["modmail_conversation"] = FakeResponse(502, {"error": "reddit is down"})
    (conv,) = reddit.subreddit("reformed").modmail.conversations()

    assert RedditActions._last_action_author(conv, RedditActions._ACTION_ARCHIVED) == ""


def test_archiving_by_id_needs_no_fetch(reddit: D.DevvitReddit, app: FakeApp) -> None:
    modmail = reddit.subreddit("reformed").modmail

    modmail("conv1").archive()
    modmail("conv1").unarchive()
    modmail("conv1").reply(body="hello", author_hidden=True)

    assert [p["json"] for p in app.posts] == [
        {"op": "modmail_archive", "args": {"id": "conv1"}},
        {"op": "modmail_unarchive", "args": {"id": "conv1"}},
        {"op": "modmail_reply", "args": {"id": "conv1", "body": "hello", "author_hidden": True}},
    ]


def test_a_ban_passes_its_reason_note_and_duration(reddit: D.DevvitReddit, app: FakeApp) -> None:
    banned = reddit.subreddit("reformed").banned

    banned.add("troll", ban_reason="Rule 1", note="third strike", duration=7)
    banned.add("spammer", ban_reason="Spam")  # permanent: no duration sent
    banned.remove("troll")

    assert [p["json"] for p in app.posts] == [
        {"op": "ban", "args": {"username": "troll", "reason": "Rule 1", "note": "third strike", "duration": 7}},
        {"op": "ban", "args": {"username": "spammer", "reason": "Spam", "note": ""}},
        {"op": "unban", "args": {"username": "troll"}},
    ]


def test_a_reddit_actions_without_a_session_says_so() -> None:
    with pytest.raises(ValueError, match="needs a reddit session"):
        RedditActions("reformed")
