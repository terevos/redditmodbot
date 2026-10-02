"""Serving several subreddits at once: config parsing, routing, and the poll
loop keeping each feed's state and channels separate."""
from __future__ import annotations

import configparser
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

import reformed_listener as L
from conftest import MOD_LIST, FakeConversation, FakeItem, FakeReddit, FakeSlackClient
from reddit_actions import RedditActions


def parse(text: str) -> configparser.ConfigParser:
    """Read an inline slack.ini fragment."""
    cfg = configparser.ConfigParser()
    cfg.read_string(text)
    return cfg


# ---------------------------------------------------------------------------
# _load_feeds
# ---------------------------------------------------------------------------

TWO_SUBS = """
[Subreddit:reformed]
MODQUEUE_CHANNEL = mod_actions
MODMAIL_CHANNEL  = mod_mail

[Subreddit:whatcouldgowrong]
MODQUEUE_CHANNEL = wcgw_reports
MODMAIL_CHANNEL  = wcgw_mail
"""


def test_each_subreddit_section_becomes_a_feed() -> None:
    feeds = L._load_feeds(parse(TWO_SUBS))
    assert [f.subreddit for f in feeds] == ["reformed", "whatcouldgowrong"]
    assert feeds[1].raw_modqueue_channel == "wcgw_reports"
    assert feeds[1].raw_modmail_channel == "wcgw_mail"


def test_a_subreddit_may_configure_one_half_of_its_feed() -> None:
    feeds = L._load_feeds(parse("[Subreddit:reformed]\nMODQUEUE_CHANNEL = mod_actions\n"))
    assert feeds[0].raw_modmail_channel is None
    assert feeds[0].is_configured()


def test_an_r_prefix_in_the_section_name_is_tolerated() -> None:
    feeds = L._load_feeds(parse("[Subreddit:r/reformed]\nMODQUEUE_CHANNEL = mod_actions\n"))
    assert feeds[0].subreddit == "reformed"


def test_the_legacy_channels_section_still_makes_a_feed() -> None:
    """An un-migrated slack.ini keeps working."""
    feeds = L._load_feeds(parse("[Channels]\nMODQUEUE_CHANNEL = mod_actions\nMODMAIL_CHANNEL = mod_mail\n"))
    assert len(feeds) == 1
    assert feeds[0].subreddit == "reformed"
    assert feeds[0].raw_modqueue_channel == "mod_actions"


def test_the_legacy_section_honours_a_configured_subreddit() -> None:
    feeds = L._load_feeds(parse("[Default]\nSUBREDDIT = whatcouldgowrong\n[Channels]\nMODQUEUE_CHANNEL = c\n"))
    assert feeds[0].subreddit == "whatcouldgowrong"


def test_subreddit_sections_win_over_the_legacy_section() -> None:
    feeds = L._load_feeds(parse(TWO_SUBS + "\n[Channels]\nMODQUEUE_CHANNEL = old_channel\n"))
    assert [f.subreddit for f in feeds] == ["reformed", "whatcouldgowrong"]
    assert "old_channel" not in [f.raw_modqueue_channel for f in feeds]


def test_no_configuration_yields_no_feeds() -> None:
    assert L._load_feeds(parse("[Default]\nPOLL_INTERVAL = 30\n")) == []


def test_per_subreddit_mods_are_attached_to_their_feed() -> None:
    feeds = L._load_feeds(parse(TWO_SUBS + "\n[Mods:whatcouldgowrong]\nU_WCGW = wcgw_mod\n"))
    assert feeds[0].mods == {}
    assert feeds[1].mods == {"U_WCGW": "wcgw_mod"}


def test_the_global_mods_section_is_not_a_feeds_own_list() -> None:
    """[Mods] stays global; it is applied by is_authorized_mod, not per feed."""
    feeds = L._load_feeds(parse(TWO_SUBS + "\n[Mods]\nU_MOD = terevos2\n"))
    assert all(f.mods == {} for f in feeds)


def test_each_feed_names_its_own_devvit_install() -> None:
    text = TWO_SUBS.replace("MODMAIL_CHANNEL  = mod_mail", "MODMAIL_CHANNEL  = mod_mail\nDEVVIT_URL = https://bot-aaa-external.devvit.net/external/")
    feeds = L._load_feeds(parse(text))
    assert [f.devvit_url for f in feeds] == ["https://bot-aaa-external.devvit.net/external/", ""]


def test_a_feed_may_name_its_own_devvit_token() -> None:
    """A subreddit served by a second Devvit app has that app's token."""
    feeds = L._load_feeds(parse(TWO_SUBS + "DEVVIT_TOKEN = devvit_at_wcgw\n"))
    assert [f.devvit_token for f in feeds] == ["", "devvit_at_wcgw"]


class FakeSession:
    """Stands in for a DevvitReddit: answers the startup identity check."""

    opened: List[str] = []
    serves: Dict[str, Any] = {}

    def __init__(self, url: str, token: str) -> None:
        """Record the install asked for, and the token it was asked with."""
        self.url = url
        self.token = token
        FakeSession.opened.append(url)

    def served_subreddit(self) -> str:
        """Name the subreddit this URL's install serves, or fail to reach it."""
        answer = FakeSession.serves[self.url]
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def startup(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Make ``_startup`` runnable: tokens set, sessions and RedditActions faked.

    Returns a function that installs feeds built from ``(subreddit, url)``
    pairs, each install answering for the subreddit named in ``serves`` (or its
    own, when not given).
    """
    FakeSession.opened = []
    FakeSession.serves = {}
    monkeypatch.setattr(L, "slack_token", "xoxb-test")
    monkeypatch.setattr(L, "app_token", "xapp-test")
    monkeypatch.setattr(L, "devvit_token", "devvit_at_test")
    monkeypatch.setattr(L, "DevvitReddit", FakeSession)

    def install(pairs: List[Any], serves: Optional[Dict[str, Any]] = None) -> List[Any]:
        """Install the feeds and say what each URL's install answers."""
        built = [L.Feed(sub, None, None, devvit_url=url) for sub, url in pairs]
        FakeSession.serves = {url: sub for sub, url in pairs}
        FakeSession.serves.update(serves or {})
        monkeypatch.setattr(L, "feeds", built)
        # After the feeds exist: Feed itself reads RedditActions.parse_controls.
        monkeypatch.setattr(L, "RedditActions", lambda sub, reddit, controls: type("RA", (), {"session": reddit, "adopt_legacy_logs": lambda s, c: None, "migrate_done_state": lambda s: None, "refresh_mod_list": lambda s: None})())
        return built

    return install


def test_startup_opens_one_session_per_feed(startup: Any) -> None:
    """An install acts on its own subreddit only, so no two feeds share one."""
    built = startup([("reformed", "https://a/external/"), ("whatcouldgowrong", "https://b/external/")])

    L._startup()

    assert FakeSession.opened == ["https://a/external/", "https://b/external/"]
    assert built[0].reddit.session is not built[1].reddit.session
    assert built[0].reddit.session.token == "devvit_at_test"


def test_startup_names_a_feed_with_no_devvit_url(startup: Any) -> None:
    startup([("reformed", "https://a/external/"), ("whatcouldgowrong", None)])

    with pytest.raises(SystemExit, match=r"no DEVVIT_URL for r/whatcouldgowrong"):
        L._startup()
    assert FakeSession.opened == []  # nothing is contacted on a config mistake


def test_startup_refuses_to_run_without_a_devvit_token(startup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    startup([("reformed", "https://a/external/")])
    monkeypatch.setattr(L, "devvit_token", "")

    with pytest.raises(SystemExit, match=r"DEVVIT_TOKEN"):
        L._startup()


def test_startup_uses_a_feeds_own_token_over_the_default(startup: Any) -> None:
    built = startup([("reformed", "https://a/external/"), ("whatcouldgowrong", "https://b/external/")])
    built[1].devvit_token = "devvit_at_wcgw"

    L._startup()

    assert [f.reddit.session.token for f in built] == ["devvit_at_test", "devvit_at_wcgw"]


def test_startup_needs_no_default_token_when_every_feed_has_its_own(startup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    built = startup([("reformed", "https://a/external/")])
    built[0].devvit_token = "devvit_at_own"
    monkeypatch.setattr(L, "devvit_token", "")

    L._startup()

    assert built[0].reddit.session.token == "devvit_at_own"


def test_startup_refuses_a_url_that_belongs_to_another_subreddit(startup: Any) -> None:
    """Two URLs swapped in slack.ini would cross-post two subreddits' queues."""
    startup([("reformed", "https://a/external/")], serves={"https://a/external/": "whatcouldgowrong"})

    with pytest.raises(SystemExit, match=r"r/reformed has the DEVVIT_URL of the install on r/whatcouldgowrong"):
        L._startup()


def test_startup_rides_out_an_unreachable_install(startup: Any) -> None:
    """An outage at startup is not a config mistake: the poll loop retries."""
    built = startup([("Reformed", "https://a/external/")], serves={"https://a/external/": RuntimeError("down")})

    L._startup()

    assert built[0].reddit is not None


def test_the_subreddit_check_ignores_case(startup: Any) -> None:
    built = startup([("Reformed", "https://a/external/")], serves={"https://a/external/": "reformed"})

    L._startup()

    assert built[0].reddit is not None


# ---------------------------------------------------------------------------
# two live feeds
# ---------------------------------------------------------------------------

class StopLoop(Exception):
    """Raised from the patched sleep to end the loop after one pass."""


@pytest.fixture
def two_feeds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, slack: FakeSlackClient) -> Any:
    """Two fully wired feeds sharing one Slack workspace and one log directory.

    The logs are deliberately shared, as they are in production: they are keyed
    by channel, so two subreddits never collide.
    """
    built = []
    for sub, queue, mail in (("reformed", "C_QUEUE", "C_MAIL"), ("whatcouldgowrong", "C_WCGW", "C_WCGW_MAIL")):
        reddit = FakeReddit()
        feed = L.Feed(sub, queue, mail)
        feed.reddit = RedditActions(sub, reddit=reddit, log_dir=str(tmp_path / "logs"), mod_list=MOD_LIST)
        feed.modqueue_channel = queue
        feed.modmail_channel = mail
        built.append((feed, reddit))

    monkeypatch.setattr(L, "feeds", [f for f, _ in built])
    monkeypatch.setattr(L, "_last_digest_slot", "already-fired")
    monkeypatch.setattr(L, "SlackWebClient", lambda token: slack)
    monkeypatch.setattr(L.config, "get", lambda *a, **k: "30")

    def stop(seconds: float) -> None:
        """End the loop after its first pass."""
        raise StopLoop

    monkeypatch.setattr(L.time, "sleep", stop)
    return built, slack


def run_one_pass() -> None:
    """Run the loop until the patched sleep stops it."""
    with pytest.raises(StopLoop):
        L._poll_loop()


def test_each_subreddit_posts_to_its_own_channel(two_feeds: Any) -> None:
    (reformed, reformed_reddit), (wcgw, wcgw_reddit) = two_feeds[0]
    slack = two_feeds[1]
    reformed_reddit.add_queue_item(FakeItem("a1", created_utc=1.0))
    wcgw_reddit.add_queue_item(FakeItem("b1", created_utc=1.0))

    run_one_pass()

    channels = {p["channel"] for p in slack.cards()}
    assert channels == {"C_QUEUE", "C_WCGW"}
    assert reformed.reddit.get_item_info("C_QUEUE", "a1")["slack_ts"]
    assert wcgw.reddit.get_item_info("C_WCGW", "b1")["slack_ts"]


def test_the_two_feeds_do_not_see_each_others_items(two_feeds: Any) -> None:
    """The shared log is keyed by channel, so each feed reads only its own."""
    (reformed, reformed_reddit), (wcgw, _) = two_feeds[0]
    reformed_reddit.add_queue_item(FakeItem("a1", created_utc=1.0))

    run_one_pass()

    assert wcgw.reddit.get_item_info("C_WCGW", "a1") == {}
    assert reformed.reddit.get_item_info("C_QUEUE", "a1")["queue_num"] == 1


def test_queue_numbers_are_counted_per_channel(two_feeds: Any) -> None:
    (_, reformed_reddit), (_, wcgw_reddit) = two_feeds[0]
    reformed_reddit.add_queue_item(FakeItem("a1", created_utc=1.0))
    reformed_reddit.add_queue_item(FakeItem("a2", created_utc=2.0))
    wcgw_reddit.add_queue_item(FakeItem("b1", created_utc=1.0))

    run_one_pass()

    feeds = [f for f, _ in two_feeds[0]]
    assert feeds[0].reddit.get_item_info("C_QUEUE", "a2")["queue_num"] == 2
    assert feeds[1].reddit.get_item_info("C_WCGW", "b1")["queue_num"] == 1, "wcgw numbering starts at 1"


def test_modmail_is_routed_to_each_subreddits_own_channel(two_feeds: Any) -> None:
    (_, reformed_reddit), (_, wcgw_reddit) = two_feeds[0]
    slack = two_feeds[1]
    reformed_reddit._sub.modmail.all = [FakeConversation("c1", subject="reformed question")]
    wcgw_reddit._sub.modmail.all = [FakeConversation("c2", subject="wcgw question")]

    run_one_pass()

    by_channel = {p["channel"]: p["text"] for p in slack.cards()}
    assert "reformed question" in by_channel["C_MAIL"]
    assert "wcgw question" in by_channel["C_WCGW_MAIL"]


def test_a_broken_subreddit_does_not_stop_the_other(two_feeds: Any) -> None:
    """One subreddit's outage must not silence the rest of the workspace."""
    (_, reformed_reddit), (_, wcgw_reddit) = two_feeds[0]
    slack = two_feeds[1]

    def boom(*args: Any, **kwargs: Any) -> None:
        """Fail the way an unreachable subreddit does."""
        raise ValueError("reformed is broken")

    reformed_reddit._sub.modqueue = boom
    wcgw_reddit.add_queue_item(FakeItem("b1", created_utc=1.0))

    run_one_pass()

    assert slack.cards("C_WCGW")


def test_each_feed_keeps_its_own_status_message(two_feeds: Any) -> None:
    feeds = [f for f, _ in two_feeds[0]]
    slack = two_feeds[1]

    run_one_pass()

    assert feeds[0].queue_status.ts and feeds[1].queue_status.ts
    assert feeds[0].queue_status.ts != feeds[1].queue_status.ts
    all_clear = [p["channel"] for p in slack.posted if "Mod queue is clear" in p["text"]]
    assert set(all_clear) == {"C_QUEUE", "C_WCGW"}


# ---------------------------------------------------------------------------
# digest
# ---------------------------------------------------------------------------

def at_hour(monkeypatch: pytest.MonkeyPatch, hour: int) -> None:
    """Freeze the digest clock at a scheduled local hour."""
    from datetime import datetime as real

    class FrozenDatetime(real):
        """A datetime whose ``now()`` is pinned to the time under test."""

        @classmethod
        def now(cls, tz: Any = None) -> Any:
            """Return the pinned local time, honouring the requested tzinfo."""
            return real(2026, 7, 29, hour, 0, tzinfo=tz)

    monkeypatch.setattr(L, "datetime", FrozenDatetime)


def test_a_busy_feed_does_not_suppress_a_quiet_ones_digest(monkeypatch: pytest.MonkeyPatch, two_feeds: Any) -> None:
    feeds = [f for f, _ in two_feeds[0]]
    slack = two_feeds[1]
    at_hour(monkeypatch, L._DIGEST_HOURS[0])
    monkeypatch.setattr(L, "_last_digest_slot", None)
    feeds[0].last_activity_at = time.time()   # r/reformed just posted
    feeds[1].last_activity_at = 0.0           # r/whatcouldgowrong has been silent

    assert L._maybe_post_digest(slack) is True

    posted_to = {p["channel"] for p in slack.posted}
    assert "C_WCGW" in posted_to
    assert "C_QUEUE" not in posted_to, "the busy feed is left alone"
