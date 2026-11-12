import asyncio
import io
import json

import discord

from .delivery import AmbiguousDelivery, PermanentDelivery, TransientDelivery, is_board_delivery
from .formatting import split_message


def channel_problem(
    channel: discord.TextChannel, member: discord.Member, attachment: bool = False
) -> str | None:
    permissions = channel.permissions_for(member)
    required = ["view_channel", "send_messages", "read_message_history"]
    if attachment:
        required.append("attach_files")
    missing = [name for name in required if not getattr(permissions, name)]
    if missing:
        return f"Channel #{channel.name}: grant the bot {', '.join(missing)}."
    return None


def board_channel_problem(channel: discord.TextChannel, board_role: discord.Role | None):
    guild = channel.guild
    if channel.permissions_for(guild.default_role).view_channel:
        return "Choose a private board channel: deny View Channel for @everyone."
    if not board_role or not channel.permissions_for(board_role).view_channel:
        return "Grant the configured board role View Channel in the board channel."
    allowed = {board_role.id, guild.me.id}
    if guild.self_role:
        allowed.add(guild.self_role.id)
    if any(
        overwrite.view_channel is True and target.id not in allowed
        for target, overwrite in channel.overwrites.items()
    ):
        return "Allow View Channel in the board channel only for the board role and the bot."
    return None


class DiscordTransport:
    def __init__(self, bot):
        self.bot = bot

    async def publish(self, delivery: dict, checkpoint) -> list[int]:
        try:
            channel = self.bot.get_channel(delivery["channel_id"])
            if channel is None:
                channel = await self.bot.fetch_channel(delivery["channel_id"])
            if (
                not isinstance(channel, discord.TextChannel)
                or channel.guild.id != delivery["guild_id"]
            ):
                raise PermanentDelivery("Select a text channel in the configured server.")
            payload = json.loads(delivery["payload_json"])
            if problem := channel_problem(
                channel, channel.guild.me, bool(payload.get("attachment"))
            ):
                raise PermanentDelivery(problem)
            if is_board_delivery(delivery):
                async with self.bot.repository.transaction() as tx:
                    settings = await tx.one("settings", guild_id=delivery["guild_id"])
                if not settings or channel.id != settings["board_channel_id"]:
                    raise PermanentDelivery("Retry this delivery in the configured board channel.")
                board_role = channel.guild.get_role(settings["board_role_id"])
                if problem := board_channel_problem(channel, board_role):
                    raise PermanentDelivery(problem)
            parts = split_message(payload["text"])
            ids = json.loads(delivery["message_ids"])
            for index, text in enumerate(parts):
                kwargs = dict(
                    content=text,
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False,
                        replied_user=False,
                        roles=[discord.Object(id=value) for value in payload.get("role_ids", [])],
                        users=[discord.Object(id=value) for value in payload.get("user_ids", [])],
                    ),
                    view=self.bot.make_view(payload) if index == 0 else None,
                )
                file = (
                    discord.File(
                        io.BytesIO(payload["text"].encode()), filename=payload["attachment"]
                    )
                    if payload.get("attachment") and index == len(parts) - 1
                    else None
                )
                message = None
                if index < len(ids):
                    try:
                        message = await channel.fetch_message(ids[index])
                    except discord.NotFound:
                        pass  # A definite deletion is safe to replace.
                if message:
                    # PATCH/DELETE are idempotent; retrying an uncertain edit is safe.
                    try:
                        await message.edit(
                            **kwargs, suppress=True, attachments=[file] if file else []
                        )
                    except (OSError, asyncio.TimeoutError) as exc:
                        raise TransientDelivery("Message edit interrupted; retrying.") from exc
                    except discord.HTTPException as exc:
                        if exc.status >= 500 or exc.status == 429:
                            raise TransientDelivery(
                                "Discord could not edit the message; retrying."
                            ) from exc
                        raise
                else:
                    try:
                        message = await channel.send(
                            **kwargs, suppress_embeds=True, **({"file": file} if file else {})
                        )
                    except (OSError, asyncio.TimeoutError) as exc:
                        raise AmbiguousDelivery(
                            "Send interrupted. Check Discord before /sdc retry."
                        ) from exc
                    except discord.HTTPException as exc:
                        if exc.status >= 500:
                            raise AmbiguousDelivery(
                                "Discord send returned a server error; check before retrying."
                            ) from exc
                        raise
                    if index < len(ids):
                        ids[index] = message.id
                    else:
                        ids.append(message.id)
                    await checkpoint(ids)
            for old_id in ids[len(parts) :]:
                try:
                    await channel.get_partial_message(old_id).delete()
                except discord.NotFound:
                    pass
            ids = ids[: len(parts)]
            await checkpoint(ids)
            return ids
        except discord.Forbidden as exc:
            raise PermanentDelivery(
                "Channel access denied. Restore the bot's channel permissions and /sdc retry."
            ) from exc
        except discord.NotFound as exc:
            raise PermanentDelivery(
                "Channel no longer exists. Update project/setup configuration and retry."
            ) from exc
        except discord.HTTPException as exc:
            if exc.status >= 500 or exc.status == 429:
                raise TransientDelivery("Discord is unavailable; retrying shortly.") from exc
            raise PermanentDelivery(
                f"Discord rejected the message (HTTP {exc.status}). Check logs/configuration."
            ) from exc
        except (OSError, asyncio.TimeoutError) as exc:
            # Only read/idempotent operations can reach this catch: creates are handled above.
            raise TransientDelivery("Discord connection unavailable; retrying shortly.") from exc
