"""Reddit, by way of the bot's Devvit app.

This module is what replaced PRAW. The bot no longer holds Reddit credentials
or talks to Reddit's API: a Devvit app installed on each subreddit does that
(``devvit-app/``), and this is the client for the one endpoint it exposes,
``POST <install>/external/rpc``, authenticated with a managed app token.

The classes here deliberately keep the shape of the PRAW objects
``reddit_actions.py`` was written against — ``reddit.subreddit(name).mod.modqueue()``,
``item.mod.approve()``, ``sub.modmail(conv_id).archive()`` and so on — so the
move changed where Reddit is reached from and nothing about what the bot does
with the answers. Only the calls the bot makes are covered; this is not a
general Reddit client.

Three things differ from PRAW and are worth knowing:

- **One session is one subreddit.** An install acts on its own subreddit only,
  so there is one :class:`DevvitReddit` per feed, built from that feed's
  ``DEVVIT_URL``. ``subreddit(name)`` takes the name for the bot's own use; it
  does not choose where a call goes.
- **Objects are lazy the way PRAW's were.** ``reddit.comment(id=…)`` makes no
  request; the first attribute read does. A modmail conversation out of a
  listing carries no ``mod_actions``, and reading that costs one request —
  which is the cost ``sync_archived_conversations`` is written around.
- **``approved_by`` / ``banned_by`` are never in a listing.** Devvit's models
  do not carry them; the app records them from mod actions as they happen.
  Reading either on a modqueue item fetches that item.
"""
from __future__ import annotations

import logging
import threading
import time
from functools import cached_property
from typing import Any, Dict, Iterator, List, Optional

import requests

# Devvit allows 5 requests a second to an install's external endpoints. The
# poll thread and the Slack handlers share a session, so the spacing is
# enforced here rather than hoped for.
_MIN_CALL_INTERVAL: float = 0.21
# Devvit's own ceiling on a request is 30s; a little over, so its error is the
# one that surfaces rather than ours.
_TIMEOUT: float = 35.0

# PRAW's numeric modmail action types, by the name Devvit gives each one. The
# bot matches on the numbers (RedditActions._ACTION_ARCHIVED and friends).
_ACTION_TYPE_IDS: Dict[str, int] = {
    "Highlighted": 0,
    "Unhighlighted": 1,
    "Archived": 2,
    "Unarchived": 3,
    "ReportedToAdmins": 4,
    "Muted": 5,
    "Unmuted": 6,
    "Banned": 7,
    "Unbanned": 8,
    "Approved": 9,
    "Disapproved": 10,
    "Filtered": 11,
    "Unfiltered": 12,
}


class DevvitError(Exception):
    """A call to the Devvit app failed.

    ``response`` is the HTTP response when there was one, which is where the
    poll loop looks for a status code (``_is_server_error``).
    """

    def __init__(self, message: str, response: Any = None) -> None:
        """Keep the response alongside the message."""
        super().__init__(message)
        self.response = response


class ServerError(DevvitError):
    """The app, or Reddit behind it, answered 5xx.

    The name is load-bearing: the poll loop recognises a ``ServerError`` by
    name and retries sooner, as it did for prawcore's exception of that name.
    """


class Redditor:
    """A Reddit user: an object with a ``name`` that stringifies to it."""

    def __init__(self, name: str) -> None:
        """Store the username."""
        self.name: str = name

    def __str__(self) -> str:
        """The bot often stringifies an author directly."""
        return self.name

    def __repr__(self) -> str:
        """Identify the user in log output."""
        return f"Redditor(name={self.name!r})"


class DevvitReddit:
    """A connection to one subreddit's install of the Devvit app.

    Stands where ``praw.Reddit`` did.
    """

    def __init__(self, url: str, token: str, session: Optional[Any] = None) -> None:
        """Remember where the install lives; no request is made.

        Args:
            url: The install's external root, as the app reports it — e.g.
                ``https://reformedautomodv2-2th52-external.devvit.net/external/``.
            token: A managed app token (``devvit_at_…``) from the app's
                Developer Settings.
            session: Anything with ``requests.Session``'s ``post``. Tests pass
                a fake; by default a real session is opened lazily.
        """
        self._rpc_url: str = url.rstrip("/") + "/rpc"
        self._token: str = token
        self._session: Any = session
        self._lock = threading.Lock()
        self._last_call_at: float = 0.0

    def call(self, op: str, **args: Any) -> Dict[str, Any]:
        """Run one operation on the app and return its JSON result.

        Raises:
            ServerError: The app or Reddit answered 5xx.
            DevvitError: Any other failure — a refused token, a bad request,
                an unreachable host, a body that is not JSON.
        """
        with self._lock:
            wait = self._last_call_at + _MIN_CALL_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            if self._session is None:
                self._session = requests.Session()
            try:
                response = self._session.post(
                    self._rpc_url,
                    json={"op": op, "args": {k: v for k, v in args.items() if v is not None}},
                    headers={"Authorization": f"bearer {self._token}"},
                    timeout=_TIMEOUT,
                )
            except requests.RequestException as e:
                raise DevvitError(f"{op}: could not reach the Devvit app: {e}") from e
            finally:
                self._last_call_at = time.monotonic()

        status = response.status_code
        if status != 200:
            detail = _error_detail(response)
            cls = ServerError if status >= 500 else DevvitError
            raise cls(f"{op}: HTTP {status}{': ' + detail if detail else ''}", response)
        try:
            data = response.json()
        except ValueError as e:
            raise DevvitError(f"{op}: the Devvit app did not answer with JSON", response) from e
        return data if isinstance(data, dict) else {}

    def served_subreddit(self) -> str:
        """Ask the install which subreddit it serves.

        A ``DEVVIT_URL`` pasted into the wrong ``[Subreddit:…]`` section would
        otherwise post one subreddit's queue into another's channels with
        nothing to say so; ``_startup()`` compares this against the section.
        """
        info = self.call("info")
        logging.info(f"Devvit app {info.get('app')} v{info.get('version')} on r/{info.get('subreddit')}")
        return str(info.get("subreddit", ""))

    def subreddit(self, name: str) -> "Subreddit":
        """Return the subreddit this install serves."""
        return Subreddit(self, name)

    def comment(self, id: str) -> "Comment":
        """Return a comment by bare ID. Lazy: nothing is fetched yet."""
        return Comment(self, id=id)

    def submission(self, id: str) -> "Submission":
        """Return a post by bare ID. Lazy: nothing is fetched yet."""
        return Submission(self, id=id)


def _error_detail(response: Any) -> str:
    """Pull the app's ``error`` message out of a failed response, if any."""
    try:
        body = response.json()
    except ValueError:
        return (getattr(response, "text", "") or "")[:200]
    return str(body.get("error", "")) if isinstance(body, dict) else ""


# ---------------------------------------------------------------------------
# Posts and comments
# ---------------------------------------------------------------------------

class _Thing:
    """A post or comment. Fetched on first use when built from a bare ID."""

    kind: str = ""

    def __init__(self, reddit: Any, id: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Build from an ID alone, or from a listing entry.

        A listing entry fills in everything but ``approved_by`` / ``banned_by``,
        so the object stays un-fetched and reading either still asks the app.
        """
        self._reddit = reddit
        self.id: str = id
        self._fetched: bool = False
        if data is not None:
            self._load(data)

    def _load(self, data: Dict[str, Any]) -> None:
        """Take on the fields of a wire ``Thing``."""
        for key, value in data.items():
            if key in ("id", "kind"):
                continue
            if key in ("author", "approved_by", "banned_by"):
                value = Redditor(value) if value else None
            elif key in ("user_reports", "mod_reports"):
                # Tuples, as PRAW had them; the card builders index into these.
                value = [tuple(report) for report in value]
            self.__dict__[key] = value
        if "created_utc" in data:
            self.__dict__["created"] = data["created_utc"]

    def _fetch(self) -> None:
        """Load the full item, including who resolved it."""
        self._fetched = True  # first, so a failed fetch is not retried per attribute
        self._load(self._reddit.call("item", id=self.id, kind=self.kind)["item"])

    def __getattr__(self, name: str) -> Any:
        """Fetch on the first read of a field this object does not have yet."""
        if name.startswith("_"):
            raise AttributeError(name)
        if not self.__dict__.get("_fetched", True):
            self._fetch()
            if name in self.__dict__:
                return self.__dict__[name]
        raise AttributeError(f"{type(self).__name__} has no attribute {name!r}")

    @cached_property
    def mod(self) -> "_ThingModeration":
        """The moderation actions for this item."""
        return _ThingModeration(self)

    def reply(self, body: str) -> "Comment":
        """Reply to this item as the app account."""
        result = self._reddit.call("reply", id=self.id, kind=self.kind, text=body)
        reply = Comment(self._reddit, id=result["id"])
        reply.__dict__["permalink"] = result.get("permalink", "")
        return reply

    def __repr__(self) -> str:
        """Identify the item in log output."""
        return f"{type(self).__name__}(id={self.id!r})"


class Comment(_Thing):
    """A comment. ``get_modqueue`` tells the two kinds apart by class."""

    kind = "comment"


class Submission(_Thing):
    """A post."""

    kind = "submission"


class _ThingModeration:
    """``item.mod`` — the actions a moderator takes on a post or comment."""

    def __init__(self, thing: _Thing) -> None:
        """Bind to the item being moderated."""
        self._thing = thing

    def _call(self, op: str, **args: Any) -> Dict[str, Any]:
        """Run *op* against this item."""
        return self._thing._reddit.call(op, id=self._thing.id, kind=self._thing.kind, **args)

    def approve(self) -> None:
        """Approve the item."""
        self._call("approve")

    def remove(self, spam: bool = False) -> None:
        """Remove the item, optionally as spam."""
        self._call("remove", spam=spam)

    def ignore_reports(self) -> None:
        """Stop future reports on the item from re-queuing it."""
        self._call("ignore_reports")

    def distinguish(self, sticky: bool = False) -> None:
        """Mark the item as posted by a moderator."""
        self._call("distinguish", sticky=sticky)

    def send_removal_message(self, message: str, title: str = "ignored", type: str = "public") -> Any:
        """Tell a post's author why it was removed.

        Devvit has no single call for this, so it is built from the two it
        does have: a stickied, distinguished comment for ``public``, a modmail
        conversation with the author for anything else.

        Returns:
            For a private message, an object whose ``id`` is the modmail
            conversation ID. ``None`` for a public one — the caller builds a
            modmail link from the ID, and a comment has no such link.
        """
        thing = self._thing
        if type == "public":
            self._thing._reddit.call("reply", id=thing.id, kind=thing.kind, text=message, distinguish=True, sticky=True)
            return None
        author = thing.author
        if author is None:
            return None
        return ModmailConversation(thing._reddit, self._thing._reddit.call("modmail_create", subject=title, body=message, to=author.name)["id"])


# ---------------------------------------------------------------------------
# Modmail
# ---------------------------------------------------------------------------

class ModmailMessage:
    """One message in a modmail conversation."""

    def __init__(self, data: Dict[str, Any]) -> None:
        """Build from a wire ``ModmailMessage``."""
        self.id: str = data["id"]
        self.author: Optional[Redditor] = Redditor(data["author"]) if data.get("author") else None
        self.body_markdown: str = data.get("body_markdown", "")
        self.date: str = data.get("date", "")


class ModmailAction:
    """An entry in a conversation's ``mod_actions`` (archive, unarchive, …)."""

    def __init__(self, data: Dict[str, Any]) -> None:
        """Build from a wire ``ModmailAction``, numbering the type as PRAW did."""
        self.action_type_id: int = _ACTION_TYPE_IDS.get(data.get("action_type", ""), -1)
        self.date: str = data.get("date", "")
        self.author: str = data.get("author", "")


class ModmailConversation:
    """A modmail conversation, from a listing or by ID."""

    def __init__(self, reddit: Any, id: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Build from an ID alone, or from a listing entry."""
        self._reddit = reddit
        self.id: str = id
        self._fetched: bool = False
        if data is not None:
            self._load(data)

    def _load(self, data: Dict[str, Any]) -> None:
        """Take on the fields of a wire ``ModmailConversation``."""
        self.__dict__["subject"] = data.get("subject", "")
        self.__dict__["is_auto"] = bool(data.get("is_auto", False))
        self.__dict__["state"] = data.get("state", "")
        self.__dict__["messages"] = [ModmailMessage(m) for m in data.get("messages", [])]
        if "mod_actions" in data:
            self.__dict__["mod_actions"] = [ModmailAction(a) for a in data["mod_actions"]]

    def __getattr__(self, name: str) -> Any:
        """Fetch the whole conversation on the first read of a missing field.

        This is the request ``mod_actions`` costs on a listed conversation.
        """
        if name.startswith("_"):
            raise AttributeError(name)
        if not self.__dict__.get("_fetched", True):
            self._fetched = True
            self._load(self._reddit.call("modmail_conversation", id=self.id)["conversation"])
            if name in self.__dict__:
                return self.__dict__[name]
        raise AttributeError(f"ModmailConversation has no attribute {name!r}")

    def reply(self, body: str, author_hidden: bool = False) -> None:
        """Reply to the conversation, optionally as the subreddit."""
        self._reddit.call("modmail_reply", id=self.id, body=body, author_hidden=author_hidden)

    def archive(self) -> None:
        """Archive the conversation for the whole mod team."""
        self._reddit.call("modmail_archive", id=self.id)

    def unarchive(self) -> None:
        """Move the conversation back out of the archive."""
        self._reddit.call("modmail_unarchive", id=self.id)

    def mute(self, num_hours: int = 72) -> None:
        """Stop the user replying for 72, 168 or 672 hours."""
        self._reddit.call("modmail_mute", id=self.id, hours=num_hours)

    def __repr__(self) -> str:
        """Identify the conversation in log output."""
        return f"ModmailConversation(id={self.id!r})"


class _Modmail:
    """``subreddit.modmail`` — listings, lookup by ID, and new conversations."""

    def __init__(self, reddit: Any) -> None:
        """Bind to the install."""
        self._reddit = reddit

    def conversations(self, state: Optional[str] = None, limit: Optional[int] = None) -> Iterator[ModmailConversation]:
        """Yield conversations, newest activity first, optionally by state."""
        result = self._reddit.call("modmail_conversations", state=state, limit=limit)
        return iter([ModmailConversation(self._reddit, c["id"], c) for c in result.get("conversations", [])])

    def __call__(self, conv_id: str) -> ModmailConversation:
        """``sub.modmail(conv_id)`` — a conversation by ID. Lazy."""
        return ModmailConversation(self._reddit, conv_id)

    def create(self, subject: str, body: str, recipient: str) -> ModmailConversation:
        """Start a conversation with *recipient*, from the subreddit."""
        result = self._reddit.call("modmail_create", subject=subject, body=body, to=recipient)
        return ModmailConversation(self._reddit, result["id"])


# ---------------------------------------------------------------------------
# The subreddit
# ---------------------------------------------------------------------------

class RemovalReason:
    """One of the subreddit's configured removal reasons."""

    def __init__(self, data: Dict[str, Any]) -> None:
        """Build from a wire ``RemovalReason``."""
        self.id: str = data["id"]
        self.title: str = data.get("title", "")
        self.message: str = data.get("message", "")


class _SubredditModeration:
    """``subreddit.mod`` — the modqueue and the removal reasons."""

    def __init__(self, reddit: Any) -> None:
        """Bind to the install."""
        self._reddit = reddit

    def modqueue(self, limit: Optional[int] = None) -> Iterator[_Thing]:
        """Yield everything in the modqueue, newest first."""
        result = self._reddit.call("modqueue", limit=limit)
        items: List[_Thing] = []
        for data in result.get("items", []):
            cls = Comment if data.get("kind") == "comment" else Submission
            items.append(cls(self._reddit, data["id"], data))
        return iter(items)

    @property
    def removal_reasons(self) -> List[RemovalReason]:
        """The subreddit's removal reasons. One request per read, as with PRAW."""
        return [RemovalReason(r) for r in self._reddit.call("removal_reasons").get("reasons", [])]


class _Banned:
    """``subreddit.banned`` — ban and unban."""

    def __init__(self, reddit: Any) -> None:
        """Bind to the install."""
        self._reddit = reddit

    def add(self, username: str, ban_reason: str = "", note: str = "", duration: Optional[int] = None) -> None:
        """Ban *username*; ``duration`` in days, permanent when ``None``."""
        self._reddit.call("ban", username=username, reason=ban_reason, note=note, duration=duration)

    def remove(self, username: str) -> None:
        """Lift a ban."""
        self._reddit.call("unban", username=username)


class Subreddit:
    """The subreddit an install serves, with the surfaces the bot uses."""

    def __init__(self, reddit: Any, name: str) -> None:
        """Bind to the install; no request is made."""
        self._reddit = reddit
        self.display_name: str = name
        self.mod = _SubredditModeration(reddit)
        self.modmail = _Modmail(reddit)
        self.banned = _Banned(reddit)

    def moderator(self) -> List[Redditor]:
        """Return the subreddit's moderators."""
        return [Redditor(name) for name in self._reddit.call("moderators").get("names", [])]

    def deletions(self, since: int = 0) -> Dict[str, Any]:
        """Return the posts and comments deleted since *since* (unix ms).

        ``{"ids": [...], "cursor": int, "more": bool}`` — bare IDs oldest
        first, and the cursor to pass back next time. Not a PRAW surface: PRAW
        had no such listing, and the bot never removed what was deleted.
        """
        result = self._reddit.call("deletions", since=since)
        return {
            "ids": [str(i) for i in result.get("ids", [])],
            "cursor": int(result.get("cursor", since) or since),
            "more": bool(result.get("more")),
        }
