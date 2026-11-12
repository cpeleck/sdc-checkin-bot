import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import timedelta

import pytest

from sdc_bot.models import Actor, CheckinInput, Conflict, PermissionDenied, Status, UserError

UPDATE = CheckinInput(Status.ON_TRACK, "Built the prototype", "Test with users")
BLOCKED = CheckinInput(
    Status.BLOCKED,
    "Built the prototype",
    "Test with users",
    "Need deployment access",
    "A mentor for deployment",
)


async def opened(services, board):
    return await services.open_round(board, "Week 1", "2026-10-30 17:00")


async def test_setup_requires_manager_and_valid_timezone(repo, clock, member, admin):
    from sdc_bot.services import Services

    service = Services(repo, clock)
    with pytest.raises(PermissionDenied):
        await service.setup(member, 200, 400)
    with pytest.raises(UserError, match="timezone"):
        await service.setup(admin, 200, 400, "not/a/zone")
    with pytest.raises(UserError, match="everyone"):
        await service.setup(admin, 100, 400)


async def test_role_authorization_and_guild_isolation(services, admin, board, member):
    assert [p["name"] for p in await services.projects(member)] == ["Alpha", "Beta"]
    assert len(await services.projects(board)) == 2
    with pytest.raises(PermissionDenied):
        await services.save_project(member, name="Intruder", channel_id=502)
    round_ = await opened(services, board)
    with pytest.raises(PermissionDenied):
        await services.submit(member, 2, round_["id"], UPDATE, 0)
    with pytest.raises(UserError):
        await services.checkin_context(Actor(999, 3, frozenset({300})), 1)
    with pytest.raises(PermissionDenied):
        await services.summary(member, round_["id"])
    with pytest.raises(PermissionDenied):
        await services.board_support(member)
    with pytest.raises(PermissionDenied, match="board role"):
        await services.board_support(admin)
    with pytest.raises(PermissionDenied, match="board channel"):
        await services.board_support(replace(board, channel_id=500))
    beta_member = replace(member, channel_id=501)
    participant, _, _ = await services.checkin_context(beta_member)
    assert participant["project_id"] == 2
    await services.request_support(beta_member, "Need help")
    assert not await services.support_list(member)
    assert len(await services.board_support(board)) == 1


async def test_one_open_round_and_participants_are_snapshotted(services, board, repo):
    round_ = await opened(services, board)
    with pytest.raises(Conflict):
        await opened(services, board)
    third = await services.save_project(board, name="Gamma", channel_id=502)
    with pytest.raises(UserError, match="not in this check-in round"):
        await services.checkin_context(board, third["id"])
    await services.save_project(board, project_id=1, name="Renamed", active=0)
    async with repo.transaction() as tx:
        participants = await tx.all("round_projects", round_id=round_["id"])
    assert [p["name"] for p in participants] == ["Alpha", "Beta"]


async def test_submission_revision_and_optimistic_concurrency(services, board, member, repo):
    round_ = await opened(services, board)
    saved = await services.submit(member, 1, round_["id"], UPDATE, 0)
    assert saved["version"] == 1
    results = await asyncio.gather(
        services.submit(member, 1, round_["id"], UPDATE, 1),
        services.submit(replace(board, channel_id=500), 1, round_["id"], UPDATE, 1),
        return_exceptions=True,
    )
    assert sum(isinstance(result, Conflict) for result in results) == 1
    async with repo.transaction() as tx:
        assert len(await tx.all("checkins")) == 1
        revisions = await tx.all("checkin_revisions")
        assert len(revisions) == 2
        assert json.loads(revisions[0]["data_json"])["author_id"] == member.user_id
        assert len(await tx.all("deliveries", delivery_key=f"checkin:{saved['id']}")) == 1


async def test_database_enforces_unique_submission(services, board, member, repo):
    round_ = await opened(services, board)
    saved = await services.submit(member, 1, round_["id"], UPDATE, 0)
    with pytest.raises(sqlite3.IntegrityError):
        async with repo.transaction() as tx:
            await tx.insert(
                "checkins", **{key: value for key, value in saved.items() if key != "id"}
            )


async def test_late_submission_close_and_frozen_digest(services, board, member, clock):
    round_ = await opened(services, board)
    clock.now += timedelta(days=5)
    saved = await services.submit(member, 1, round_["id"], BLOCKED, 0)
    assert saved["late"] == 1
    closed = await services.close_round(board)
    assert "Submissions: **1/2**" in closed["summary"]
    assert "Beta" in closed["summary"].split("## Missing updates")[1].split("##")[0]
    assert "Alpha" in closed["summary"].split("## Projects needing attention")[1].split("##")[0]
    assert "Need deployment access" in closed["summary"]
    with pytest.raises(Conflict, match="closed"):
        await services.submit(member, 1, round_["id"], UPDATE, 1)
    ticket = (await services.support_list(member))[0]
    await services.act_on_ticket(board, ticket["id"], "resolve", "Access granted")
    await services.save_project(board, project_id=1, contact_id=None)
    assert await services.summary(board, round_["id"]) == closed["summary"]


async def test_support_lifecycle_revision_dedup_and_no_auto_resolution(
    services, board, member, repo
):
    round_ = await opened(services, board)
    await services.submit(member, 1, round_["id"], BLOCKED, 0)
    ticket = (await services.support_list(member))[0]
    assert ticket["assignee_id"] == board.user_id
    with pytest.raises(PermissionDenied):
        await services.act_on_ticket(member, ticket["id"], "acknowledge")
    await services.act_on_ticket(board, ticket["id"], "acknowledge", "I'll help")
    await services.submit(member, 1, round_["id"], UPDATE, 1)
    tickets = await services.support_list(member)
    assert len(tickets) == 1
    assert tickets[0]["state"] == "acknowledged"
    await services.act_on_ticket(board, ticket["id"], "assign", "Hand-off", assignee_id=4)
    with pytest.raises(UserError, match="resolution note"):
        await services.act_on_ticket(board, ticket["id"], "resolve")
    await services.act_on_ticket(board, ticket["id"], "resolve", "https://example.com/resources")
    await services.submit(member, 1, round_["id"], BLOCKED, 2)
    assert (await services.support_list(member))[0]["state"] == "resolved"
    with pytest.raises(Conflict):
        await services.act_on_ticket(board, ticket["id"], "acknowledge")
    async with repo.transaction() as tx:
        assert len(await tx.all("support_notes", ticket_id=ticket["id"])) == 3
        team = await tx.one("deliveries", delivery_key=f"support-team:{ticket['id']}")
        assert "resources" in json.loads(team["payload_json"])["text"]


async def test_support_outside_round_falls_back_to_board_role(services, board, repo):
    ticket = await services.request_support(replace(board, channel_id=501), "Need a designer")
    assert ticket["checkin_id"] is None
    async with repo.transaction() as tx:
        alert = await tx.one("deliveries", delivery_key=f"support-board:{ticket['id']}")
        payload = json.loads(alert["payload_json"])
    assert payload["role_ids"] == [200]
    assert payload["user_ids"] == []
    assert "Beta" in await services.overview(board)


async def test_validation_and_case_insensitive_project_names(services, board, member):
    with pytest.raises(Conflict):
        await services.save_project(board, name="alpha", channel_id=700)
    with pytest.raises(UserError, match="separate from the board channel"):
        await services.save_project(board, project_id=1, channel_id=400)
    with pytest.raises(Conflict, match="in use by another project"):
        await services.save_project(board, project_id=1, channel_id=501)
    round_ = await opened(services, board)
    with pytest.raises(UserError):
        await services.submit(
            member, 1, round_["id"], CheckinInput(Status.ON_TRACK, " ", "next"), 0
        )
    with pytest.raises(UserError):
        await services.submit(
            member, 1, round_["id"], CheckinInput(Status.ON_TRACK, "x" * 1501, "next"), 0
        )


async def test_summary_retry_uses_one_outbox_entry_and_preview_does_not_publish(
    services, board, repo
):
    round_ = await opened(services, board)
    await services.summary(board, round_["id"])
    async with repo.transaction() as tx:
        assert not await tx.all("deliveries", kind="summary")
    await services.summary(board, round_["id"], publish=True)
    await services.close_round(board)
    await services.summary(board, round_["id"], publish=True)
    async with repo.transaction() as tx:
        summaries = await tx.all("deliveries", kind="summary")
    assert len(summaries) == 1
    assert summaries[0]["version"] == 3
