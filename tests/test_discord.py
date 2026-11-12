import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, create_autospec

import discord
import pytest

from sdc_bot.config import Config
from sdc_bot.delivery import AmbiguousDelivery, PermanentDelivery
from sdc_bot.discord_app import CheckinModal, PromptView, SDCBot, SDCCommands, SupportView
from sdc_bot.discord_transport import DiscordTransport
from sdc_bot.formatting import safe, split_message
from sdc_bot.models import Actor, PermissionDenied, Status, UserError


def interaction_for(member, role_ids, guild_id=100, channel_id=500):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild_id = guild_id
    interaction.channel_id = channel_id
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = member
    interaction.user.roles = [SimpleNamespace(id=role) for role in role_ids]
    interaction.user.guild_permissions.manage_guild = False
    interaction.response = SimpleNamespace(
        defer=AsyncMock(),
        send_modal=AsyncMock(),
        send_message=AsyncMock(),
        is_done=lambda: True,
    )
    interaction.followup.send = AsyncMock()
    return interaction


def test_safe_mentions_and_splitting():
    text = "@everyone <@123> <@&200> **fake**\n" + "x" * 9000
    escaped = safe(text)
    assert "@everyone" not in escaped and "<@" not in escaped
    chunks = split_message(escaped)
    assert len(chunks) > 4
    assert all(len(part) <= 1900 for part in chunks)
    assert "".join(chunks).count("x") == 9000
    assert all(len(part.encode("utf-16-le")) // 2 <= 1900 for part in split_message("🚀" * 2500))


async def test_command_tree_and_views_are_valid(services, repo, monkeypatch):
    bot = SDCBot(Config("test", 100, ":memory:", "INFO"))
    bot.repository = repo
    bot.services = services
    cog = SDCCommands(bot)
    await bot.add_cog(cog)
    for command in bot.tree.walk_commands():
        if isinstance(command, discord.app_commands.Command) and any(
            parameter.name == "project" for parameter in command.parameters
        ):
            command.autocomplete("project")(cog.project_autocomplete)
    definitions = [command.to_dict(bot.tree) for command in bot.tree.get_commands()]
    assert {command["name"] for command in definitions} == {
        "sdc",
        "project",
        "round",
        "checkin",
        "support",
        "summary",
        "schedule",
        "board",
    }
    checkin = next(command for command in definitions if command["name"] == "checkin")
    assert len(checkin["options"][0]["options"][0]["choices"]) == 3
    assert PromptView(bot, 1, 1).is_persistent()
    assert SupportView(bot, 1).is_persistent()
    assert all(item.disabled for item in SupportView(bot, 1, resolved=True).children)
    # Do not close the shared fixture repository through bot.close().
    await bot.remove_cog(cog.qualified_name)


async def test_button_checks_channel_and_form_checks_author(services, repo, board, member):
    bot = SDCBot(Config("test", 100, ":memory:", "INFO"))
    bot.services, bot.repository = services, repo
    round_ = await services.open_round(board, "Week 1", "2026-10-30 17:00")
    with pytest.raises(PermissionDenied):
        await PromptView(bot, 2, round_["id"]).open_form(interaction_for(3, []))
    project, round_, existing = await services.checkin_context(member, 1)
    modal = CheckinModal(bot, member, project, round_, existing, Status.ON_TRACK)
    modal.inputs["progress"]._value = "Done"
    modal.inputs["next_steps"]._value = "Next"
    # A form belongs to its original author and round channel.
    with pytest.raises(PermissionDenied):
        await modal.on_submit(interaction_for(4, []))
    with pytest.raises(PermissionDenied):
        await modal.on_submit(interaction_for(3, [], channel_id=501))
    with pytest.raises(PermissionDenied):
        await SupportView(bot, 1).acknowledge(interaction_for(3, []))
    with pytest.raises(PermissionDenied):
        await SupportView(bot, 1).resolve(interaction_for(3, []))
    with pytest.raises(PermissionDenied):
        bot.actor(interaction_for(3, [300], guild_id=999))


def fake_channel():
    channel = create_autospec(discord.TextChannel, instance=True)
    channel.id = 500
    channel.name = "alpha"
    channel.guild.id = 100
    channel.permissions_for.return_value = SimpleNamespace(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        attach_files=True,
    )
    messages = {}

    async def send(**kwargs):
        message = create_autospec(discord.Message, instance=True)
        message.id = len(messages) + 1
        message.kwargs = kwargs
        messages[message.id] = message
        return message

    channel.send.side_effect = send
    channel.fetch_message.side_effect = lambda id: messages[id]
    channel.get_partial_message.return_value.delete = AsyncMock()
    return channel, messages


async def test_transport_splits_attaches_and_edits_existing_messages():
    channel, messages = fake_channel()
    bot = SimpleNamespace(get_channel=lambda id: channel, make_view=lambda payload: None)
    transport = DiscordTransport(bot)
    row = {
        "guild_id": 100,
        "kind": "checkin",
        "delivery_key": "checkin:1",
        "channel_id": 500,
        "message_ids": "[]",
        "payload_json": json.dumps({"text": "x" * 7000, "attachment": "details.md"}),
    }
    checkpoint = AsyncMock()
    ids = await transport.publish(row, checkpoint)
    assert len(ids) == 4
    assert all(len(message.kwargs["content"]) <= 1900 for message in messages.values())
    assert messages[4].kwargs["file"].filename == "details.md"
    assert not messages[1].kwargs["allowed_mentions"].everyone
    row["message_ids"] = json.dumps(ids)
    await transport.publish(row, checkpoint)
    assert channel.send.await_count == 4
    assert all(message.edit.await_count == 1 for message in messages.values())


async def test_transport_reports_lost_channel_permission():
    channel, _ = fake_channel()
    channel.permissions_for.return_value.send_messages = False
    transport = DiscordTransport(SimpleNamespace(get_channel=lambda id: channel))
    with pytest.raises(PermanentDelivery, match="send_messages"):
        await transport.publish(
            {
                "guild_id": 100,
                "kind": "checkin",
                "delivery_key": "checkin:1",
                "channel_id": 500,
                "payload_json": '{"text":"test"}',
            },
            AsyncMock(),
        )


async def test_uncertain_new_send_is_never_automatically_retried():
    channel, _ = fake_channel()
    channel.send = AsyncMock(side_effect=TimeoutError)
    transport = DiscordTransport(
        SimpleNamespace(get_channel=lambda id: channel, make_view=lambda payload: None)
    )
    with pytest.raises(AmbiguousDelivery):
        await transport.publish(
            {
                "guild_id": 100,
                "kind": "checkin",
                "delivery_key": "checkin:1",
                "channel_id": 500,
                "message_ids": "[]",
                "payload_json": '{"text":"test"}',
            },
            AsyncMock(),
        )


async def test_deleted_message_is_replaced_and_shrinking_update_removes_surplus():
    channel, messages = fake_channel()
    bot = SimpleNamespace(get_channel=lambda id: channel, make_view=lambda payload: None)
    transport = DiscordTransport(bot)
    row = {
        "guild_id": 100,
        "kind": "checkin",
        "delivery_key": "checkin:1",
        "channel_id": 500,
        "message_ids": "[]",
        "payload_json": json.dumps({"text": "x" * 7000}),
    }
    ids = await transport.publish(row, AsyncMock())
    response = SimpleNamespace(status=404, reason="Not Found")
    channel.fetch_message.side_effect = discord.NotFound(response, "Deleted")
    row.update(message_ids=json.dumps(ids), payload_json='{"text":"Short revision"}')
    result = await transport.publish(row, AsyncMock())
    assert len(result) == 1 and result[0] not in ids
    assert channel.send.await_count == 5
    assert channel.get_partial_message.return_value.delete.await_count == 3


async def test_board_channel_privacy_and_contact_validation(services, repo, board):
    bot = SDCBot(Config("test", 100, ":memory:", "INFO"))
    bot.repository, bot.services = repo, services
    cog = SDCCommands(bot)
    channel, _ = fake_channel()
    with pytest.raises(UserError, match="private board channel"):
        await cog.validate_channel(channel, board=True)
    contact = MagicMock(spec=discord.Member)
    contact.bot = False
    contact.roles = [SimpleNamespace(id=300)]
    contact.guild_permissions.manage_guild = False
    with pytest.raises(UserError, match="configured board role"):
        await cog.validate_contact(board, contact)
    contact.roles = [SimpleNamespace(id=200)]
    await cog.validate_contact(board, contact)


@pytest.mark.parametrize(
    "kind,key",
    [
        ("summary", "summary:1"),
        ("support", "support-board:1"),
        ("status_change", "status-change:1:2"),
        ("nudge", "nudge:1"),
    ],
)
async def test_board_deliveries_require_the_configured_private_channel(repo, services, kind, key):
    channel, messages = fake_channel()
    bot = SimpleNamespace(get_channel=lambda id: channel, repository=repo, make_view=lambda p: None)
    transport = DiscordTransport(bot)
    row = {
        "guild_id": 100,
        "kind": kind,
        "delivery_key": key,
        "channel_id": 500,
        "message_ids": "[]",
        "payload_json": '{"text":"Board update"}',
    }
    with pytest.raises(PermanentDelivery, match="configured board channel"):
        await transport.publish(row, AsyncMock())

    channel.id = row["channel_id"] = 400
    board_role = discord.Object(id=200)
    channel.guild.me.id = 101
    channel.guild.self_role = discord.Object(id=102)
    channel.guild.get_role.return_value = board_role
    with pytest.raises(PermanentDelivery, match="@everyone"):
        await transport.publish(row, AsyncMock())
    defaults = channel.guild.default_role
    allowed = channel.permissions_for.return_value
    channel.permissions_for.side_effect = lambda target: (
        SimpleNamespace(view_channel=False) if target is defaults else allowed
    )
    channel.overwrites = {discord.Object(id=300): discord.PermissionOverwrite(view_channel=True)}
    with pytest.raises(PermanentDelivery, match="only for the board role and the bot"):
        await transport.publish(row, AsyncMock())
    assert not messages
    channel.overwrites = {board_role: discord.PermissionOverwrite(view_channel=True)}
    await transport.publish(row, AsyncMock())
    assert messages[1].kwargs["content"] == "Board update"


async def test_startup_restores_persistent_views_and_syncs_only_configured_guild(
    tmp_path,
    monkeypatch,
):
    bot = SDCBot(Config("test", 100, str(tmp_path / "bot.sqlite3"), "INFO"))
    admin = Actor(100, 1, frozenset({200}), manage_guild=True, channel_id=400)
    await bot.repository.open()
    await bot.services.setup(admin, 200, 400)
    await bot.services.save_project(admin, name="Alpha", channel_id=500)
    # Use a relative future deadline so this startup test is independent of today's date.
    from datetime import timedelta

    from sdc_bot.models import utc_now

    await bot.services.open_round(admin, "Pilot", (utc_now() + timedelta(days=3)).isoformat())
    await bot.services.request_support(replace(admin, channel_id=500), "Need a reviewer")
    async with bot.repository.transaction() as tx:
        for row in await tx.all("deliveries"):
            await tx.update(
                "deliveries",
                {"id": row["id"]},
                state="sent",
                message_ids=json.dumps([1000 + row["id"]]),
            )
    await bot.repository.close()
    monkeypatch.setattr(bot.tree, "sync", AsyncMock())
    monkeypatch.setattr(bot.worker, "start", MagicMock())
    try:
        await bot.setup_hook()
        assert len(bot.persistent_views) == 2  # Project prompt and board support controls.
        assert bot.tree.sync.await_args.kwargs["guild"].id == 100
        assert bot.tree.sync.await_count == 1
        assert bot.tree.get_commands(guild=discord.Object(id=100))
    finally:
        await bot.close()
