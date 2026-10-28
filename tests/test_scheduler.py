import json
from datetime import UTC, datetime, timedelta

import pytest

from sdc_bot.models import CheckinInput, Status, UserError, instant, parse_due
from sdc_bot.scheduler import WeeklySchedule


async def test_manual_pilot_no_schedule_and_24h_reminder(services, board, member, repo, clock):
    await services.tick(100)
    async with repo.transaction() as tx:
        assert not await tx.all("rounds")
    round_ = await services.open_round(board, "Week 1", "2026-10-30 17:00")
    await services.submit(member, 1, round_["id"], CheckinInput(Status.ON_TRACK, "Done", "Next"), 0)
    clock.now = instant(round_["due_at"]) - timedelta(hours=24)
    await services.tick(100)
    await services.tick(100)
    async with repo.transaction() as tx:
        reminders = await tx.all("deliveries", kind="reminder")
    assert len(reminders) == 1
    assert json.loads(reminders[0]["payload_json"])["project_id"] == 2
    clock.now += timedelta(days=3)
    await services.tick(100)
    async with repo.transaction() as tx:
        assert (await tx.one("rounds", id=round_["id"]))["closed_at"] is None
        assert len(await tx.all("deliveries", kind="reminder")) == 1


async def test_short_round_skips_automatic_reminder(services, board, repo, clock):
    await services.open_round(board, "Short", (clock.now + timedelta(hours=20)).isoformat())
    await services.tick(100)
    async with repo.transaction() as tx:
        assert not await tx.all("deliveries", kind="reminder")


async def test_manual_reminder_only_missing(services, board, member, repo):
    round_ = await services.open_round(board, "Week 1", "2026-10-30 17:00")
    await services.submit(member, 1, round_["id"], CheckinInput(Status.ON_TRACK, "Done", "Next"), 0)
    assert await services.remind(board) == 1


async def test_schedule_enable_waits_next_open_then_closes_when_disabled(
    services, board, repo, clock
):
    # Enabled Monday at 09:00 Chicago: this week's 08:00 opening is in the past.
    await services.configure_schedule(board, 0, "08:00", 4, "17:00")
    await services.tick(100)
    async with repo.transaction() as tx:
        assert not await tx.all("rounds")
    clock.now = datetime(2026, 11, 2, 14, 0, tzinfo=UTC)  # 08:00 CST after DST ends.
    await services.tick(100)
    await services.tick(100)
    async with repo.transaction() as tx:
        rounds = await tx.all("rounds")
    assert len(rounds) == 1
    assert rounds[0]["source"] == "schedule"
    assert instant(rounds[0]["due_at"]).hour == 23
    await services.disable_schedule(board)
    clock.now = datetime(2026, 11, 6, 23, 5, tzinfo=UTC)
    await services.tick(100)
    async with repo.transaction() as tx:
        assert (await tx.one("rounds", id=rounds[0]["id"]))["closed_at"]
        assert len(await tx.all("deliveries", kind="summary")) == 1
    clock.now += timedelta(days=7)
    await services.tick(100)
    async with repo.transaction() as tx:
        assert len(await tx.all("rounds")) == 1


async def test_offline_reconciliation_no_historical_rounds(services, board, repo, clock):
    await services.configure_schedule(board, 0, "10:00", 4, "17:00")
    clock.now = datetime(2026, 12, 5, 12, tzinfo=UTC)  # Saturday after many missed windows.
    await services.tick(100)
    async with repo.transaction() as tx:
        assert not await tx.all("rounds")
    clock.now = datetime(2026, 12, 7, 20, tzinfo=UTC)  # Current Monday, after 10am.
    await services.tick(100)
    async with repo.transaction() as tx:
        assert len(await tx.all("rounds")) == 1


async def test_recovered_current_window_uses_actual_opening_for_reminder_cutoff(
    services,
    board,
    repo,
    clock,
):
    await services.configure_schedule(board, 0, "10:00", 4, "17:00")
    clock.now = datetime(2026, 10, 30, 20, tzinfo=UTC)  # Friday, only two hours left.
    await services.tick(100)
    async with repo.transaction() as tx:
        assert len(await tx.all("rounds")) == 1
        assert not await tx.all("deliveries", kind="reminder")


def test_timezone_and_cross_week_schedule():
    schedule = WeeklySchedule.parse(4, "17:00", 0, "09:00")
    start, end = schedule.window(datetime(2026, 11, 1, 12, tzinfo=UTC), "America/Chicago")
    assert start == datetime(2026, 10, 30, 22, tzinfo=UTC)
    assert end == datetime(2026, 11, 2, 15, tzinfo=UTC)
    assert parse_due("2026-10-30 17:00", "America/Chicago").hour == 22
    with pytest.raises(UserError, match="does not exist"):
        parse_due("2026-03-08 02:30", "America/Chicago")
    with pytest.raises(UserError, match="ambiguous"):
        parse_due("2026-11-01 01:30", "America/Chicago")
    assert parse_due("2026-11-01T01:30:00-05:00", "America/Chicago").hour == 6


@pytest.mark.parametrize(
    "args",
    [
        (0, "08:00", 0, "08:00"),
        (8, "09:00", 4, "17:00"),
        (0, "noon", 4, "17:00"),
        (0, "01:30", 4, "17:00"),
    ],
)
def test_invalid_schedules(args):
    with pytest.raises(UserError):
        WeeklySchedule.parse(*args)
