"""History, revision changes, trends, stale nudges, kudos, and skipped weeks."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from sdc_bot.config import Config
from sdc_bot.discord_app import KudosView, SDCBot
from sdc_bot.formatting import describe_trend
from sdc_bot.models import CheckinInput, Conflict, PermissionDenied, Status, UserError

ON = CheckinInput(Status.ON_TRACK, "Built the prototype", "Test with users")
RISK = CheckinInput(Status.AT_RISK, "Slow week", "Catch up", "Exams")
BLOCKED = CheckinInput(Status.BLOCKED, "Stuck", "Wait", "Need AWS credentials")


async def run_round(services, board, clock, submissions: dict, label="Week"):
    """Open, submit {project_id: input}, close, then move the clock a week ahead."""
    round_ = await services.open_round(board, label, (clock.now + timedelta(days=3)).isoformat())
    for project_id, data in submissions.items():
        actor = board  # Board members may submit for any project.
        await services.submit(actor, project_id, round_["id"], data, 0)
    closed = await services.close_round(board)
    clock.now += timedelta(days=7)
    return closed


async def deliveries(repo, kind):
    async with repo.transaction() as tx:
        return await tx.all("deliveries", kind=kind)


# --- 1. History --------------------------------------------------------------------


async def test_history_shows_past_rounds_missed_weeks_and_permissions(
    services, board, member, clock
):
    await run_round(services, board, clock, {1: ON}, "Week 1")
    await run_round(services, board, clock, {}, "Week 2")
    await run_round(services, board, clock, {1: CheckinInput(Status.ON_TRACK, "x" * 400, "y")})
    text = await services.history(member, 1)
    assert text.index("Week 2") < text.index("Week 1")  # Newest first.
    assert "no update submitted" in text
    assert "x" * 400 not in text and "…" in text
    assert "x" * 400 in await services.history(member, 1, full=True)
    assert "last 2 rounds" in await services.history(member, 1, rounds=2)
    with pytest.raises(PermissionDenied):
        await services.history(member, 2)
    with pytest.raises(UserError):
        await services.history(member, 1, rounds=0)


# --- 2. Revision changes -----------------------------------------------------------


async def test_revision_card_diff_and_board_status_alert(services, board, member, repo, clock):
    round_ = await services.open_round(board, "Week 1", "2026-10-30 17:00")
    saved = await services.submit(member, 1, round_["id"], BLOCKED, 0)
    assert not await deliveries(repo, "status_change")  # First submissions are not "changes".
    fixed = CheckinInput(Status.ON_TRACK, "Stuck\nFixed with ```code```", "Wait")
    await services.submit(member, 1, round_["id"], fixed, 1)
    async with repo.transaction() as tx:
        card = await tx.one("deliveries", delivery_key=f"checkin:{saved['id']}")
    payload = json.loads(card["payload_json"])
    assert "Changed in rev 2: Status (Blocked → On track), Progress, Blockers" in payload["text"]
    assert payload["view"] == "checkin"
    alerts = await deliveries(repo, "status_change")
    assert len(alerts) == 1 and alerts[0]["channel_id"] == 400
    assert "Blocked → On track" in json.loads(alerts[0]["payload_json"])["text"]

    diff = await services.changes(member, 1)
    assert "revision 2" in diff and "```diff" in diff
    assert "Status: Blocked → On track" in diff
    assert "+ Fixed with" in diff and "- Need AWS credentials" in diff
    assert "Next steps: unchanged" in diff
    assert diff.count("```") == 2  # User backticks cannot close the block early.
    assert "First submission" in await services.changes(member, 1, revision=1)
    with pytest.raises(UserError, match="1 to 2"):
        await services.changes(member, 1, revision=3)
    with pytest.raises(PermissionDenied):
        await services.changes(member, 2)


# --- 3. Trends ---------------------------------------------------------------------


def test_trend_rules():
    assert describe_trend(["On track", "At risk", "Blocked", "Blocked"]) == [
        "worsening",
        "blocked 2 rounds",
    ]
    assert describe_trend(["Blocked", "At risk", "On track"]) == ["improving"]
    assert describe_trend(["On track", None, None, "At risk"]) == ["worsening", "2 missed"]
    assert describe_trend(["On track", "Blocked", "On track"]) == []


async def test_digest_trends_cover_recent_rounds_and_mark_missed(services, board, clock):
    await run_round(services, board, clock, {1: ON, 2: ON})
    await run_round(services, board, clock, {1: RISK})
    await run_round(services, board, clock, {1: BLOCKED})
    gamma = await services.save_project(board, name="Gamma", role_id=302, channel_id=502)
    closed = await run_round(services, board, clock, {1: BLOCKED, gamma["id"]: ON})
    trends = closed["summary"].split("## Trends (last 4 rounds)")[1].split("\n## ")[0]
    assert "⚠️ Alpha: On track → At risk → Blocked → Blocked (worsening, blocked 2 rounds)" in trends
    assert "⚠️ Beta: On track → — → — → — (3 missed)" in trends
    assert "Gamma" not in trends  # Only one round of history so far.


async def test_open_round_preview_does_not_count_pending_projects_as_missed(services, board, clock):
    await run_round(services, board, clock, {1: ON, 2: ON})
    await run_round(services, board, clock, {1: ON, 2: ON})
    round_ = await services.open_round(board, "Now", (clock.now + timedelta(days=3)).isoformat())
    await services.submit(board, 1, round_["id"], RISK, 0)
    preview = await services.summary(board, round_["id"])
    assert "Alpha: On track → On track → At risk (worsening)" in preview
    assert "Beta: On track → On track\n" in preview  # Beta can still submit this round.
    closed = await services.close_round(board)
    assert "\nBeta: On track → On track → —\n" in closed["summary"]  # One miss: no warning.


async def test_first_round_has_no_trend_section(services, board, clock):
    closed = await run_round(services, board, clock, {1: ON})
    assert "## Trends" not in closed["summary"]
    assert "## Kudos" not in closed["summary"]  # No empty heading without kudos.


# --- 4. Stale-ticket nudges ---------------------------------------------------------


async def test_stale_ticket_nudges(services, board, member, repo, clock):
    await services.tick(100)  # Off by default.
    alpha = await services.request_support(member, 1, "Need a reviewer")
    beta = await services.request_support(board, 2, "Need a designer")
    with pytest.raises(PermissionDenied):
        await services.configure_nudges(member, 3)
    await services.configure_nudges(board, 3)
    clock.now += timedelta(days=2)
    await services.tick(100)
    assert not await deliveries(repo, "nudge")
    clock.now += timedelta(days=1)
    await services.tick(100)
    await services.tick(100)
    nudges = {
        json.loads(n["payload_json"])["ticket_id"]: n for n in await deliveries(repo, "nudge")
    }
    assert len(nudges) == 2
    alpha_payload = json.loads(nudges[alpha["id"]]["payload_json"])
    assert alpha_payload["user_ids"] == [2] and "no acknowledgement" in alpha_payload["text"]
    assert json.loads(nudges[beta["id"]]["payload_json"])["role_ids"] == [200]
    async with repo.transaction() as tx:
        team = await tx.one("deliveries", delivery_key=f"support-team:{alpha['id']}")
    assert "Reminder sent to <@2>" in json.loads(team["payload_json"])["text"]

    # Board follow-up resets the clock; resolved tickets are never nudged again.
    await services.act_on_ticket(board, alpha["id"], "acknowledge", "On it")
    await services.act_on_ticket(board, beta["id"], "resolve", "Found a designer")
    clock.now += timedelta(days=2)
    await services.tick(100)
    assert len(await deliveries(repo, "nudge")) == 2
    clock.now += timedelta(days=1)
    await services.tick(100)
    latest = [
        n
        for n in await deliveries(repo, "nudge")
        if n["id"] not in {r["id"] for r in nudges.values()}
    ]
    assert len(latest) == 1
    assert "no board follow-up for 3 day(s)" in json.loads(latest[0]["payload_json"])["text"]

    await services.configure_nudges(board, 0)
    clock.now += timedelta(days=10)
    await services.tick(100)
    assert len(await deliveries(repo, "nudge")) == 3


async def test_queued_nudge_is_dropped_once_ticket_is_resolved(services, board, repo, clock):
    from sdc_bot.delivery import Dispatcher

    ticket = await services.request_support(board, 2, "Need a designer")
    await services.configure_nudges(board, 1)
    clock.now += timedelta(days=1)
    await services.tick(100)
    await services.act_on_ticket(board, ticket["id"], "resolve", "Done")
    transport = SimpleNamespace(publish=AsyncMock(return_value=[1]))
    await Dispatcher(repo, transport, clock).flush()
    assert (await deliveries(repo, "nudge"))[0]["state"] == "skipped"


# --- 5. Kudos -----------------------------------------------------------------------


async def test_kudos_board_only_once_per_member_and_in_digest(services, board, member, repo, clock):
    round_ = await services.open_round(board, "Week 1", "2026-10-30 17:00")
    checkin = await services.submit(member, 1, round_["id"], ON, 0)
    with pytest.raises(PermissionDenied):
        await services.give_kudos(member, checkin["id"])
    await services.give_kudos(board, checkin["id"], "Great @everyone demo")
    with pytest.raises(Conflict):
        await services.give_kudos(board, checkin["id"])
    posts = await deliveries(repo, "kudos")
    assert len(posts) == 1 and posts[0]["channel_id"] == 500
    text = json.loads(posts[0]["payload_json"])["text"]
    assert "gave **Alpha** kudos" in text and "@everyone" not in text
    closed = await services.close_round(board)
    assert "## Kudos this round\nAlpha (1)" in closed["summary"]
    assert "🎉 1" in await services.history(member, 1)


async def test_kudos_button_is_persistent_and_rejects_team_members(services, repo):
    bot = SDCBot(Config("test", 100, ":memory:", "INFO"))
    bot.services, bot.repository = services, repo
    view = KudosView(bot, 7)
    assert view.is_persistent()
    assert isinstance(bot.make_view({"view": "checkin", "checkin_id": 7}), KudosView)
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild_id = 100
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 3
    interaction.user.roles = [SimpleNamespace(id=300)]
    interaction.user.guild_permissions.manage_guild = False
    with pytest.raises(PermissionDenied):
        await view.give(interaction)


# --- 6. Skipped weeks ---------------------------------------------------------------


async def test_skipped_week_opens_nothing_posts_once_and_resumes(services, board, repo, clock):
    # Monday 2026-10-26 09:00 Chicago; rounds open Mondays at 10:00.
    await services.configure_schedule(board, 0, "10:00", 4, "17:00")
    await services.skip_week(board, "2026-10-29", "Fall break")  # Any day in the week works.
    with pytest.raises(Conflict):
        await services.skip_week(board, "2026-10-26")
    lines = await services.schedule_lines(board)
    assert "Schedule: opens Monday 10:00, closes Friday 17:00" in lines
    assert any("Next opening" in line and "2026-11-02" not in line for line in lines)

    clock.now = datetime(2026, 10, 26, 15, 30, tzinfo=UTC)
    await services.tick(100)
    await services.tick(100)
    async with repo.transaction() as tx:
        assert not await tx.all("rounds")
    notices = await deliveries(repo, "skip_notice")
    assert len(notices) == 2  # Alpha and Beta, once each.
    assert "Fall break" in json.loads(notices[0]["payload_json"])["text"]

    clock.now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)  # Window over: nothing is caught up.
    await services.tick(100)
    clock.now = datetime(2026, 11, 2, 16, 30, tzinfo=UTC)  # Next Monday 10:30 CST.
    await services.tick(100)
    async with repo.transaction() as tx:
        rounds = await tx.all("rounds")
    assert len(rounds) == 1 and rounds[0]["label"] == "Week of 2026-11-02"


async def test_skip_validation_listing_and_unskip(services, board, member, repo, clock):
    with pytest.raises(UserError, match="already passed"):
        await services.skip_week(board, "2026-10-01")
    with pytest.raises(UserError, match="2026-11-23"):
        await services.skip_week(board, "next week")
    with pytest.raises(PermissionDenied):
        await services.skip_week(member, "2026-11-23")
    week = await services.skip_week(board, "2026-11-26", "Thanksgiving")
    assert week.isoformat() == "2026-11-23"
    assert [row["week_start"] for row in await services.skips(board)] == ["2026-11-23"]
    await services.unskip_week(board, "2026-11-23")
    assert await services.skips(board) == []
    with pytest.raises(UserError, match="not skipped"):
        await services.unskip_week(board, "2026-11-23")


async def test_skip_after_round_opened_does_not_post_notice(services, board, repo, clock):
    await services.configure_schedule(board, 0, "10:00", 4, "17:00")
    clock.now = datetime(2026, 10, 26, 15, 30, tzinfo=UTC)
    await services.tick(100)
    await services.close_round(board)  # Closed early in the same window.
    await services.skip_week(board, "2026-10-26")
    await services.tick(100)
    assert not await deliveries(repo, "skip_notice")
