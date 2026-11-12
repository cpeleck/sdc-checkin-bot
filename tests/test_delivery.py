import json
from dataclasses import replace
from datetime import timedelta

import pytest

from sdc_bot.delivery import AmbiguousDelivery, Dispatcher, PermanentDelivery, TransientDelivery
from sdc_bot.models import Actor, CheckinInput, PermissionDenied, Status, UserError, stamp
from sdc_bot.repository import Repository
from sdc_bot.services import Services


class FakeTransport:
    def __init__(self):
        self.messages = {}
        self.calls = []
        self.error = None

    async def publish(self, row, checkpoint):
        self.calls.append(row["id"])
        if self.error:
            raise self.error
        ids = json.loads(row["message_ids"])
        if not ids:
            ids = [len(self.messages) + 1000]
            await checkpoint(ids)
        self.messages[ids[0]] = json.loads(row["payload_json"])["text"]
        return ids


async def test_restart_keeps_prompts_updates_and_sends_no_completed_duplicates(
    services,
    board,
    member,
    repo,
    clock,
):
    transport = FakeTransport()
    dispatcher = Dispatcher(repo, transport, clock)
    round_ = await services.open_round(board, "Week 1", "2026-10-30 17:00")
    await dispatcher.flush()
    assert len(transport.messages) == 2
    # Reopen the actual database and construct a fresh service/worker.
    await repo.close()
    await repo.open()
    services = Services(repo, clock)
    dispatcher = Dispatcher(repo, transport, clock)
    await dispatcher.recover()
    await dispatcher.flush()
    assert len(transport.calls) == 2
    await services.submit(
        member, 1, round_["id"], CheckinInput(Status.ON_TRACK, "First", "Next"), 0
    )
    await dispatcher.flush()
    assert len(transport.messages) == 3
    await services.submit(
        member, 1, round_["id"], CheckinInput(Status.ON_TRACK, "Revised", "Next"), 1
    )
    await dispatcher.flush()
    assert len(transport.messages) == 3
    assert "Revised" in transport.messages[1002]


async def test_interrupted_send_requires_explicit_retry(services, board, repo, clock):
    await services.open_round(board, "Week 1", "2026-10-30 17:00")
    async with repo.transaction() as tx:
        await tx.update("deliveries", {"id": 1}, state="sending")
    transport = FakeTransport()
    dispatcher = Dispatcher(repo, transport, clock)
    await dispatcher.recover()
    await dispatcher.flush()
    assert transport.calls == [2]
    failures = await services.diagnostics(board)
    assert failures[0]["state"] == "ambiguous"
    await services.retry_delivery(board, 1)
    await dispatcher.flush()
    assert transport.calls == [2, 1]


@pytest.mark.parametrize(
    "error,state",
    [
        (PermanentDelivery("Restore channel permissions"), "failed"),
        (AmbiguousDelivery("Check Discord"), "ambiguous"),
        (TransientDelivery("Try later"), "retry"),
    ],
)
async def test_delivery_failure_classification(services, board, repo, clock, error, state):
    await services.request_support(replace(board, channel_id=501), "Need help")
    transport = FakeTransport()
    transport.error = error
    dispatcher = Dispatcher(repo, transport, clock)
    await dispatcher.flush()
    failures = await services.diagnostics(board)
    assert len(failures) == 2
    assert all(row["state"] == state for row in failures)
    if state == "retry":
        assert all(row["next_attempt_at"] for row in failures)
        transport.error = None
        clock.now += timedelta(minutes=10)
        await dispatcher.flush()
        assert not await services.diagnostics(board)


async def test_retarget_failed_channel_does_not_reuse_old_channel_message_ids(
    services,
    board,
    repo,
    clock,
):
    await services.request_support(replace(board, channel_id=500), "Need help")
    async with repo.transaction() as tx:
        await tx.update("deliveries", {"id": 2}, state="failed", message_ids="[123]")
    await services.retry_delivery(board, 2, channel_id=999)
    async with repo.transaction() as tx:
        row = await tx.one("deliveries", id=2)
    assert row["channel_id"] == 999
    assert row["message_ids"] == "[]"


async def test_retarget_failed_prompt_to_replacement_team_channel(services, board, member, repo):
    round_ = await services.open_round(board, "Week 1", "2026-10-30 17:00")
    async with repo.transaction() as tx:
        prompt = await tx.one("deliveries", delivery_key=f"prompt:{round_['id']}:1")
        await tx.update("deliveries", {"id": prompt["id"]}, state="failed")
    with pytest.raises(UserError, match="Register the replacement"):
        await services.retry_delivery(board, prompt["id"], channel_id=600)
    await services.save_project(board, project_id=1, channel_id=600)
    await services.retry_delivery(board, prompt["id"], channel_id=600)
    with pytest.raises(PermissionDenied, match="team channel for this round"):
        await services.checkin_context(member)
    new_member = replace(member, channel_id=600)
    participant, _, _ = await services.checkin_context(new_member)
    assert participant["project_id"] == 1
    saved = await services.submit(
        new_member, 1, round_["id"], CheckinInput(Status.ON_TRACK, "Done", "Next"), 0
    )
    async with repo.transaction() as tx:
        card = await tx.one("deliveries", delivery_key=f"checkin:{saved['id']}")
    assert card["channel_id"] == 600


async def test_skip_stale_prompts_and_reminders(services, board, member, repo, clock):
    round_ = await services.open_round(board, "Week 1", "2026-10-30 17:00")
    await services.remind(board)
    await services.submit(member, 1, round_["id"], CheckinInput(Status.ON_TRACK, "Done", "Next"), 0)
    transport = FakeTransport()
    dispatcher = Dispatcher(repo, transport, clock)
    await dispatcher.flush()
    async with repo.transaction() as tx:
        reminders = await tx.all("deliveries", kind="reminder")
    assert {json.loads(r["payload_json"])["project_id"]: r["state"] for r in reminders} == {
        1: "skipped",
        2: "sent",
    }
    await services.close_round(board)
    async with repo.transaction() as tx:
        await tx.update("deliveries", {"id": 1}, state="pending")
    await dispatcher.flush()
    async with repo.transaction() as tx:
        assert (await tx.one("deliveries", id=1))["state"] == "skipped"


async def test_new_revision_queued_during_delivery_is_not_lost(
    services, board, member, repo, clock
):
    round_ = await services.open_round(board, "Week 1", "2026-10-30 17:00")
    transport = FakeTransport()
    dispatcher = Dispatcher(repo, transport, clock)
    await dispatcher.flush()
    await services.submit(member, 1, round_["id"], CheckinInput(Status.ON_TRACK, "Old", "Next"), 0)
    original_publish = transport.publish
    revised = False

    async def revise_while_publishing(row, checkpoint):
        nonlocal revised
        if row["kind"] == "checkin" and not revised:
            revised = True
            await services.submit(
                member, 1, round_["id"], CheckinInput(Status.ON_TRACK, "New", "Next"), 1
            )
        return await original_publish(row, checkpoint)

    transport.publish = revise_while_publishing
    await dispatcher.flush()
    assert "New" in transport.messages[1002]
    async with repo.transaction() as tx:
        assert (await tx.one("deliveries", kind="checkin"))["state"] == "sent"


async def test_single_process_database_guard(tmp_path):
    path = str(tmp_path / "guard.sqlite3")
    first, second = Repository(path), Repository(path)
    await first.open()
    try:
        with pytest.raises(RuntimeError, match="Another bot process"):
            await second.open()
    finally:
        await first.close()
        await second.close()


async def test_retry_exhaustion_is_visible(services, board, repo, clock):
    await services.request_support(replace(board, channel_id=500), "Help")
    transport = FakeTransport()
    transport.error = TransientDelivery("Still unavailable")
    dispatcher = Dispatcher(repo, transport, clock)
    for _ in range(5):
        await dispatcher.flush()
        clock.now += timedelta(minutes=10)
    assert all(row["state"] == "failed" for row in await services.diagnostics(board))


async def test_pending_automatic_reminder_is_skipped_after_deadline(services, board, repo, clock):
    round_ = await services.open_round(board, "Week 1", "2026-10-30 17:00")
    async with repo.transaction() as tx:
        from sdc_bot.models import instant

        clock.now = instant(round_["due_at"]) - timedelta(hours=23)
    await services.tick(100)
    clock.now += timedelta(days=2)
    await Dispatcher(repo, FakeTransport(), clock).flush()
    async with repo.transaction() as tx:
        reminders = await tx.all("deliveries", kind="reminder")
    assert all(row["state"] == "skipped" for row in reminders)


async def test_private_server_smoke_simulation(services, board, member, repo, clock):
    """Credential-free equivalent of the documented two-project Discord pilot."""
    transport = FakeTransport()
    dispatcher = Dispatcher(repo, transport, clock)
    round_ = await services.open_round(board, "Pilot", "2026-10-30 17:00")
    await dispatcher.flush()
    await services.submit(
        member,
        1,
        round_["id"],
        CheckinInput(Status.BLOCKED, "Prototype", "Deploy", "No hosting access"),
        0,
    )
    await dispatcher.flush()
    ticket = (await services.board_support(board))[0]
    await services.act_on_ticket(board, ticket["id"], "acknowledge")
    await services.act_on_ticket(board, ticket["id"], "resolve", "Hosting access granted")
    await dispatcher.flush()
    await repo.close()
    await repo.open()
    services = Services(repo, clock)
    dispatcher = Dispatcher(repo, transport, clock)
    await dispatcher.recover()
    await services.close_round(board)
    await dispatcher.flush()
    summary = await services.summary(board, round_["id"])
    assert "Submissions: **1/2**" in summary
    assert "Beta" in summary
    assert summary.endswith("Outstanding support requests\nNone")
    async with repo.transaction() as tx:
        assert (await tx.one("rounds", id=round_["id"]))["closed_at"] == stamp(clock.now)
        assert (await tx.one("deliveries", kind="summary"))["state"] == "sent"


async def test_delivery_scope_does_not_touch_another_servers_data(
    services,
    board,
    repo,
    clock,
):
    other = Actor(999, 1, frozenset({888}), manage_guild=True, channel_id=777)
    await services.setup(other, 888, 777)
    await services.save_project(other, name="Other server", channel_id=555)
    await services.request_support(
        replace(other, channel_id=555), "Private request from another server"
    )
    await services.request_support(replace(board, channel_id=500), "Current server request")
    async with repo.transaction() as tx:
        first = await tx.one("deliveries", guild_id=999)
        await tx.update("deliveries", {"id": first["id"]}, state="sending")
    transport = FakeTransport()
    dispatcher = Dispatcher(repo, transport, clock, guild_id=100)
    await dispatcher.recover()
    await dispatcher.flush()
    async with repo.transaction() as tx:
        other_rows = await tx.all("deliveries", guild_id=999)
    assert [r["state"] for r in other_rows] == ["sending", "pending"]
    assert len(transport.calls) == 2
    assert all(
        "Private request from another server" not in text for text in transport.messages.values()
    )
