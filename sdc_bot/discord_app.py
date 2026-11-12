import asyncio
import io
import json
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .config import Config
from .delivery import Dispatcher, is_board_delivery
from .discord_transport import DiscordTransport, board_channel_problem, channel_problem
from .formatting import label, safe
from .models import Actor, CheckinInput, PermissionDenied, Status, UserError
from .repository import Repository
from .services import Services

log = logging.getLogger(__name__)


async def reply(interaction: discord.Interaction, text: str, filename: str | None = None):
    kwargs = {
        "ephemeral": True,
        "allowed_mentions": discord.AllowedMentions.none(),
        "suppress_embeds": True,
    }
    if filename or len(text) > 1900:
        kwargs["file"] = discord.File(
            io.BytesIO(text.encode()), filename=filename or "sdc-details.md"
        )
        text = "Details attached." if filename else text[:1600] + "\n\nFull details attached."
    if interaction.response.is_done():
        await interaction.followup.send(text, **kwargs)
    else:
        await interaction.response.send_message(text, **kwargs)


async def report_error(interaction: discord.Interaction, error: Exception):
    original = getattr(error, "original", error)
    if isinstance(original, UserError):
        await reply(interaction, str(original))
    else:
        log.error("Interaction failed", exc_info=(type(original), original, original.__traceback__))
        await reply(
            interaction, "The action failed. Ask the bot operator to check the application logs."
        )


class GuardedView(discord.ui.View):
    async def on_error(self, interaction, error, item):
        await report_error(interaction, error)


class CheckinModal(discord.ui.Modal):
    def __init__(
        self, bot, actor: Actor, project: dict, round_: dict, existing: dict | None, status: Status
    ):
        super().__init__(title="Project check-in", timeout=900)
        self.bot = bot
        self.project_id = project["project_id"]
        self.round_id = round_["id"]
        self.author_id = actor.user_id
        self.version = existing["version"] if existing else 0
        self.status = status
        fields = [
            ("progress", "Progress since the previous update", True),
            ("next_steps", "Next steps and current milestone", True),
            ("blockers", "Blockers (optional)", False),
            ("assistance", "Assistance requested (optional)", False),
        ]
        self.inputs = {}
        for key, title, required in fields:
            item = discord.ui.TextInput(
                style=discord.TextStyle.paragraph,
                required=required,
                max_length=1500,
                default=existing[key] if existing else None,
                placeholder=None if required else "Leave blank when none",
            )
            self.inputs[key] = item
            self.add_item(
                discord.ui.Label(
                    text=title,
                    component=item,
                    description="Shared with your project channel and SDC board"
                    if key == "progress"
                    else None,
                )
            )

    async def on_submit(self, interaction):
        actor = self.bot.actor(interaction)
        if actor.user_id != self.author_id:
            raise PermissionDenied("Reopen the form using your own account.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        checkin = await self.bot.services.submit(
            actor,
            self.project_id,
            self.round_id,
            CheckinInput(self.status, **{key: item.value for key, item in self.inputs.items()}),
            self.version,
        )
        await reply(
            interaction,
            f"Saved revision {checkin['version']}"
            f"{' (late)' if checkin['late'] else ''}. "
            "Your update is queued for your project channel and the board summary.",
        )

    async def on_error(self, interaction, error):
        await report_error(interaction, error)


class StatusSelect(discord.ui.Select):
    def __init__(self, bot, project_id: int, round_id: int):
        super().__init__(
            placeholder="Choose your project's status",
            options=[
                discord.SelectOption(label=status.value, value=status.value) for status in Status
            ],
        )
        self.bot, self.project_id, self.round_id = bot, project_id, round_id

    async def callback(self, interaction):
        actor = self.bot.actor(interaction)
        project, round_, existing = await self.bot.services.checkin_context(
            actor,
            self.project_id,
            self.round_id,
        )
        await interaction.response.send_modal(
            CheckinModal(self.bot, actor, project, round_, existing, Status(self.values[0]))
        )


class PromptView(GuardedView):
    def __init__(self, bot, project_id: int, round_id: int):
        super().__init__(timeout=None)
        self.bot, self.project_id, self.round_id = bot, project_id, round_id
        button = discord.ui.Button(
            label="Submit or edit update",
            style=discord.ButtonStyle.primary,
            custom_id=f"sdc:checkin:{round_id}:{project_id}",
        )
        button.callback = self.open_form
        self.add_item(button)

    async def open_form(self, interaction):
        actor = self.bot.actor(interaction)
        await self.bot.services.checkin_context(actor, self.project_id, self.round_id)
        view = GuardedView(timeout=300)
        view.add_item(StatusSelect(self.bot, self.project_id, self.round_id))
        await interaction.response.send_message(
            "Your answers will be shared in this project channel and with the SDC board. "
            "Choose a status to open the form.",
            view=view,
            ephemeral=True,
        )


class ResolutionModal(discord.ui.Modal):
    def __init__(self, bot, ticket_id: int):
        super().__init__(title=f"Resolve support #{ticket_id}")
        self.bot, self.ticket_id = bot, ticket_id
        self.note = discord.ui.TextInput(
            style=discord.TextStyle.paragraph, required=True, max_length=1500
        )
        self.add_item(discord.ui.Label(text="Resolution / resource links", component=self.note))

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.bot.services.act_on_ticket(
            self.bot.actor(interaction), self.ticket_id, "resolve", self.note.value
        )
        await reply(interaction, "Resolved. The team and board messages will be updated.")

    async def on_error(self, interaction, error):
        await report_error(interaction, error)


class SupportView(GuardedView):
    def __init__(self, bot, ticket_id: int, resolved: bool = False):
        super().__init__(timeout=None)
        self.bot, self.ticket_id = bot, ticket_id
        ack = discord.ui.Button(
            label="Acknowledge", custom_id=f"sdc:support:ack:{ticket_id}", disabled=resolved
        )
        resolve = discord.ui.Button(
            label="Resolve",
            custom_id=f"sdc:support:resolve:{ticket_id}",
            style=discord.ButtonStyle.success,
            disabled=resolved,
        )
        ack.callback = self.acknowledge
        resolve.callback = self.resolve
        self.add_item(ack)
        self.add_item(resolve)

    async def acknowledge(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.bot.services.act_on_ticket(
            self.bot.actor(interaction), self.ticket_id, "acknowledge"
        )
        await reply(interaction, "Acknowledged and assigned to you. The team will see the update.")

    async def resolve(self, interaction):
        async with self.bot.repository.transaction() as tx:
            await self.bot.services.require_board(tx, self.bot.actor(interaction))
        await interaction.response.send_modal(ResolutionModal(self.bot, self.ticket_id))


class KudosModal(discord.ui.Modal):
    def __init__(self, bot, checkin_id: int):
        super().__init__(title="Give kudos")
        self.bot, self.checkin_id = bot, checkin_id
        self.note = discord.ui.TextInput(
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=300,
            placeholder="Optional: what stood out?",
        )
        self.add_item(
            discord.ui.Label(
                text="Note (posted in the project channel)",
                component=self.note,
            )
        )

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.bot.services.give_kudos_from_card(
            self.bot.actor(interaction), self.checkin_id, self.note.value
        )
        await reply(interaction, "Kudos queued. It will appear in the project channel.")

    async def on_error(self, interaction, error):
        await report_error(interaction, error)


class KudosView(GuardedView):
    def __init__(self, bot, checkin_id: int):
        super().__init__(timeout=None)
        self.bot, self.checkin_id = bot, checkin_id
        button = discord.ui.Button(
            label="Kudos",
            emoji="🎉",
            style=discord.ButtonStyle.secondary,
            custom_id=f"sdc:kudos:{checkin_id}",
        )
        button.callback = self.give
        self.add_item(button)

    async def give(self, interaction):
        actor = self.bot.actor(interaction)
        async with self.bot.repository.transaction() as tx:
            await self.bot.services.kudos_card(tx, actor, self.checkin_id)
        await interaction.response.send_modal(KudosModal(self.bot, self.checkin_id))


class SDCCommands(commands.Cog):
    sdc = app_commands.Group(name="sdc", description="Configure and diagnose SDC", guild_only=True)
    project = app_commands.Group(name="project", description="SDC projects", guild_only=True)
    round = app_commands.Group(name="round", description="Weekly check-in rounds", guild_only=True)
    checkin = app_commands.Group(
        name="checkin", description="Submit and review project updates", guild_only=True
    )
    support = app_commands.Group(
        name="support", description="Request and coordinate help", guild_only=True
    )
    summary = app_commands.Group(name="summary", description="Board digests", guild_only=True)
    schedule = app_commands.Group(
        name="schedule", description="Optional weekly scheduling", guild_only=True
    )
    board = app_commands.Group(
        name="board", description="Project support overview", guild_only=True
    )

    def __init__(self, bot):
        self.bot = bot
        self.services = bot.services

    async def defer(self, interaction):
        actor = self.bot.actor(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        return actor

    async def validate_channel(self, channel: discord.TextChannel, *, board=False, board_role=None):
        if channel.guild.id != self.bot.config.guild_id:
            raise UserError("Choose a channel in this server.")
        if problem := channel_problem(channel, channel.guild.me, attachment=board):
            raise UserError(problem)
        if board and (problem := board_channel_problem(channel, board_role)):
            raise UserError(problem)

    async def validate_contact(self, actor: Actor, member: discord.Member | None):
        if member is None:
            return
        async with self.bot.repository.transaction() as tx:
            settings = await self.services.require_board(tx, actor)
        if member.bot or settings["board_role_id"] not in {role.id for role in member.roles}:
            raise UserError("Choose a person with the configured board role as the contact.")

    @sdc.command(name="setup", description="Set the board role, private channel, and timezone")
    async def setup(
        self,
        interaction: discord.Interaction,
        board_role: discord.Role,
        board_channel: discord.TextChannel,
        timezone: str = "America/Chicago",
    ):
        actor = await self.defer(interaction)
        if not actor.manage_guild:
            raise PermissionDenied("Setup requires Manage Server permission.")
        await self.validate_channel(board_channel, board=True, board_role=board_role)
        await self.services.setup(actor, board_role.id, board_channel.id, timezone)
        await reply(
            interaction,
            "Setup saved. Register projects with /project add. "
            "Use /sdc status to check scheduling and channel access.",
        )

    @sdc.command(name="status", description="Show schedule, channel checks, and delivery failures")
    async def status(self, interaction: discord.Interaction):
        actor = await self.defer(interaction)
        async with self.bot.repository.transaction() as tx:
            settings = await self.services.require_board(tx, actor)
        failures = await self.services.diagnostics(actor)
        lines = [
            f"Timezone: {settings['timezone']}",
            *await self.services.schedule_lines(actor),
            "The local process must stay running for delivery.",
        ]
        channels = {p["channel_id"]: False for p in await self.services.projects(actor)}
        channels[settings["board_channel_id"]] = True
        board_role = interaction.guild.get_role(settings["board_role_id"])
        for channel_id, board in channels.items():
            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(
                    channel_id
                )
                if not isinstance(channel, discord.TextChannel):
                    raise UserError("Select a server text channel.")
                await self.validate_channel(channel, board=board, board_role=board_role)
            except (UserError, discord.HTTPException) as exc:
                lines.append(f"Channel {channel_id}: {safe(str(exc))}")
        for row in failures:
            lines.append(
                f"Delivery #{row['id']} · {row['state']} · {row['kind']} · "
                f"channel {row['channel_id']} · {safe(row['error'] or '')}"
            )
        if failures:
            lines.append(
                "Repair channel access first. Check Discord for ambiguous sends before "
                "/sdc retry; retrying an uncertain send may duplicate it."
            )
        else:
            lines.append("No failed or uncertain deliveries.")
        await reply(interaction, "\n".join(lines))

    @sdc.command(
        name="retry",
        description="Explicitly retry a failed/uncertain delivery; may duplicate a send",
    )
    async def retry(
        self,
        interaction: discord.Interaction,
        delivery_id: int,
        channel: discord.TextChannel | None = None,
    ):
        actor = await self.defer(interaction)
        async with self.bot.repository.transaction() as tx:
            settings = await self.services.require_board(tx, actor)
            row = await tx.one("deliveries", id=delivery_id, guild_id=actor.guild_id)
        if not row or row["state"] not in ("failed", "ambiguous", "retry"):
            raise UserError("Choose a failed, ambiguous, or retrying delivery from /sdc status.")
        board = is_board_delivery(row)
        destination = channel.id if channel else row["channel_id"]
        if board and destination != settings["board_channel_id"]:
            raise UserError("Retry this delivery in the configured board channel.")
        if channel:
            await self.validate_channel(
                channel,
                board=board,
                board_role=interaction.guild.get_role(settings["board_role_id"]) if board else None,
            )
        await self.services.retry_delivery(actor, delivery_id, channel.id if channel else None)
        await reply(interaction, "Delivery queued for retry. Check /sdc status for the result.")

    @project.command(name="add", description="Register a project and its team channel")
    async def project_add(
        self,
        interaction: discord.Interaction,
        name: str,
        channel: discord.TextChannel,
        contact: discord.Member | None = None,
        milestone: str = "",
    ):
        actor = await self.defer(interaction)
        async with self.bot.repository.transaction() as tx:
            await self.services.require_board(tx, actor)
        await self.validate_channel(channel)
        await self.validate_contact(actor, contact)
        project = await self.services.save_project(
            actor,
            name=name,
            channel_id=channel.id,
            contact_id=contact.id if contact else None,
            milestone=milestone,
        )
        await reply(interaction, f"Registered project #{project['id']}: {label(project['name'])}.")

    @project.command(name="edit", description="Edit a project; use '-' to clear its milestone")
    async def project_edit(
        self,
        interaction: discord.Interaction,
        project: int,
        name: str | None = None,
        channel: discord.TextChannel | None = None,
        contact: discord.Member | None = None,
        clear_contact: bool = False,
        milestone: str | None = None,
        active: bool | None = None,
    ):
        actor = await self.defer(interaction)
        async with self.bot.repository.transaction() as tx:
            await self.services.require_board(tx, actor)
        if contact and clear_contact:
            raise UserError("Choose a contact or clear_contact, not both.")
        if channel:
            await self.validate_channel(channel)
        await self.validate_contact(actor, contact)
        changes = {
            key: value
            for key, value in {
                "name": name,
                "channel_id": channel.id if channel else None,
                "milestone": milestone,
                "active": int(active) if active is not None else None,
            }.items()
            if value is not None
        }
        if milestone == "-":
            changes["milestone"] = ""
        if clear_contact or contact:
            changes["contact_id"] = contact.id if contact else None
        await self.services.save_project(actor, project_id=project, **changes)
        await reply(
            interaction,
            "Project updated. Channel/name/milestone changes apply to future "
            "rounds; the current round retains its registered project snapshot.",
        )

    @project.command(
        name="archive", description="Exclude a project from future rounds; keep history"
    )
    async def project_archive(self, interaction: discord.Interaction, project: int):
        await self.services.save_project(
            await self.defer(interaction), project_id=project, active=0
        )
        await reply(
            interaction,
            "Archived. Existing rounds and history are retained. "
            "Use /project edit active:True to reactivate.",
        )

    @project.command(name="list", description="List registered projects and their channels")
    async def project_list(self, interaction: discord.Interaction, include_archived: bool = False):
        projects = await self.services.projects(await self.defer(interaction), include_archived)
        await reply(
            interaction,
            "\n".join(
                f"#{p['id']} · {label(p['name'])} · {'Active' if p['active'] else 'Archived'} · "
                f"<#{p['channel_id']}> · contact: "
                f"{('<@' + str(p['contact_id']) + '>') if p['contact_id'] else 'Unassigned'}\n"
                f"Milestone: {safe(p['milestone']) or 'Not set'}"
                for p in projects
            )
            or "No projects to show.",
        )

    @round.command(
        name="open", description="Manually open a round; due_at: YYYY-MM-DD HH:MM [offset]"
    )
    async def round_open(self, interaction: discord.Interaction, label: str, due_at: str):
        round_ = await self.services.open_round(await self.defer(interaction), label, due_at)
        await reply(
            interaction,
            f"Opened round #{round_['id']}. Prompts are queued; "
            f"deadline {round_['due_at']}. Close manually with /round close.",
        )

    @round.command(name="close", description="Freeze the open round and publish its board summary")
    async def round_close(self, interaction: discord.Interaction):
        round_ = await self.services.close_round(await self.defer(interaction))
        await reply(
            interaction,
            f"Round #{round_['id']} closed. The frozen summary is queued for the board channel.",
        )

    @round.command(name="remind", description="Remind projects that have not submitted")
    async def round_remind(self, interaction: discord.Interaction):
        count = await self.services.remind(await self.defer(interaction))
        await reply(interaction, f"Queued reminders for {count} missing project(s).")

    @round.command(
        name="status", description="Show participation and support for the open round (board)"
    )
    async def round_status(self, interaction: discord.Interaction):
        await reply(interaction, await self.services.overview(await self.defer(interaction)))

    @checkin.command(
        name="submit", description="Shared with your project channel and board; opens a form"
    )
    async def checkin_submit(self, interaction: discord.Interaction, status: Status):
        actor = self.bot.actor(interaction)
        project_, round_, existing = await self.services.checkin_context(actor)
        await interaction.response.send_modal(
            CheckinModal(self.bot, actor, project_, round_, existing, status)
        )

    @checkin.command(name="history", description="Show a project's past weekly updates")
    async def checkin_history(
        self,
        interaction: discord.Interaction,
        rounds: app_commands.Range[int, 1, 26] = 6,
        full: bool = False,
    ):
        text = await self.services.history(await self.defer(interaction), rounds, full)
        await reply(interaction, text)

    @checkin.command(
        name="changes", description="Compare an update revision with the one before it"
    )
    async def checkin_changes(
        self,
        interaction: discord.Interaction,
        revision: app_commands.Range[int, 1] | None = None,
        round_id: int | None = None,
    ):
        text = await self.services.changes(await self.defer(interaction), revision, round_id)
        await reply(interaction, text)

    @support.command(
        name="request", description="Request help now; shared with your project and board"
    )
    async def support_request(self, interaction: discord.Interaction, description: str):
        ticket = await self.services.request_support(await self.defer(interaction), description)
        await reply(
            interaction,
            f"Support request #{ticket['id']} opened. Team and board alerts are queued.",
        )

    @support.command(name="list", description="See support requests for the current team channel")
    async def support_list(self, interaction: discord.Interaction):
        tickets = await self.services.support_list(await self.defer(interaction))
        await self.reply_with_tickets(interaction, tickets)

    async def reply_with_tickets(self, interaction: discord.Interaction, tickets: list[dict]):
        await reply(
            interaction,
            "\n\n".join(
                f"#{t['id']} · project #{t['project_id']} · {t['state']} · "
                f"{('<@' + str(t['assignee_id']) + '>') if t['assignee_id'] else 'Unassigned'}\n"
                f"{safe(t['description'])}"
                for t in tickets
            )
            or "No support requests.",
        )

    @support.command(name="acknowledge", description="Take ownership of a support request")
    async def support_ack(self, interaction: discord.Interaction, ticket: int, note: str = ""):
        await self.services.act_on_ticket(
            await self.defer(interaction), ticket, "acknowledge", note
        )
        await reply(
            interaction,
            "Acknowledged and assigned to you. Updates are queued for the team and board.",
        )

    @support.command(name="assign", description="Assign a request to a board contact")
    async def support_assign(
        self, interaction: discord.Interaction, ticket: int, contact: discord.Member, note: str = ""
    ):
        actor = await self.defer(interaction)
        await self.validate_contact(actor, contact)
        await self.services.act_on_ticket(actor, ticket, "assign", note, contact.id)
        await reply(interaction, "Assignment saved. Team and board updates are queued.")

    @support.command(
        name="resolve", description="Resolve a request and record the outcome/resources"
    )
    async def support_resolve(self, interaction: discord.Interaction, ticket: int, note: str):
        await self.services.act_on_ticket(await self.defer(interaction), ticket, "resolve", note)
        await reply(interaction, "Resolved. The team and board messages will be updated.")

    @support.command(
        name="nudges", description="Re-ping stale support requests after N days (0 turns off)"
    )
    async def support_nudges(
        self, interaction: discord.Interaction, days: app_commands.Range[int, 0, 60]
    ):
        await self.services.configure_nudges(await self.defer(interaction), days)
        await reply(
            interaction,
            f"Stale requests will be re-pinged after {days} day(s) without board follow-up."
            if days
            else "Stale-request nudges are off.",
        )

    @summary.command(name="preview", description="Preview a board digest without posting it")
    async def summary_preview(self, interaction: discord.Interaction, round_id: int):
        summary = await self.services.summary(await self.defer(interaction), round_id)
        await reply(interaction, summary, f"sdc-round-{round_id}-preview.md")

    @summary.command(
        name="publish",
        description="Publish or update a digest; closed rounds use a frozen snapshot",
    )
    async def summary_publish(self, interaction: discord.Interaction, round_id: int):
        await self.services.summary(await self.defer(interaction), round_id, publish=True)
        await reply(
            interaction, "Summary queued. Existing summary messages will be updated where possible."
        )

    @schedule.command(
        name="configure",
        description="Enable weekly rounds: weekdays 0=Monday ... 6=Sunday, times HH:MM",
    )
    async def schedule_configure(
        self,
        interaction: discord.Interaction,
        open_day: app_commands.Range[int, 0, 6],
        open_time: str,
        close_day: app_commands.Range[int, 0, 6],
        close_time: str,
    ):
        await self.services.configure_schedule(
            await self.defer(interaction), open_day, open_time, close_day, close_time
        )
        await reply(
            interaction,
            "Weekly scheduling enabled in the server's configured timezone. "
            "The first round opens at the next scheduled opening; no historical rounds are created.",
        )

    @schedule.command(
        name="disable",
        description="Stop future scheduled openings; an existing automated round still closes",
    )
    async def schedule_disable(self, interaction: discord.Interaction):
        await self.services.disable_schedule(await self.defer(interaction))
        await reply(
            interaction,
            "Future weekly openings disabled. Existing automated rounds "
            "will still close at their deadline; manual rounds close with /round close.",
        )

    @schedule.command(
        name="skip", description="Skip the automatic round for the week containing a date"
    )
    async def schedule_skip(self, interaction: discord.Interaction, date: str, reason: str = ""):
        week = await self.services.skip_week(await self.defer(interaction), date, reason)
        await reply(
            interaction,
            f"The week of Monday {week.isoformat()} is marked to skip. The bot skips an eligible "
            "automatic opening and can post a notice in project channels. Manual rounds still work.",
        )

    @schedule.command(name="unskip", description="Undo a skipped week")
    async def schedule_unskip(self, interaction: discord.Interaction, date: str):
        week = await self.services.unskip_week(await self.defer(interaction), date)
        await reply(
            interaction,
            f"The week of Monday {week.isoformat()} is back on the schedule. An eligible "
            "round can open automatically if its scheduled window is still active.",
        )

    @schedule.command(name="skips", description="List upcoming skipped weeks")
    async def schedule_skips(self, interaction: discord.Interaction):
        rows = await self.services.skips(await self.defer(interaction))
        await reply(
            interaction,
            "\n".join(
                f"Week of {row['week_start']}"
                + (f": {label(row['reason'])}" if row["reason"] else "")
                for row in rows
            )
            or "No upcoming skipped weeks.",
        )

    @board.command(
        name="overview", description="See missing updates, support needs, and unassigned projects"
    )
    async def board_overview(self, interaction: discord.Interaction):
        await reply(interaction, await self.services.overview(await self.defer(interaction)))

    @board.command(name="support", description="List support requests across all projects")
    async def board_support(self, interaction: discord.Interaction):
        tickets = await self.services.board_support(await self.defer(interaction))
        await self.reply_with_tickets(interaction, tickets)

    @board.command(name="kudos", description="Post kudos for an update in its project channel")
    async def board_kudos(
        self,
        interaction: discord.Interaction,
        project: int,
        round_id: int | None = None,
        note: str = "",
    ):
        await self.services.give_kudos(await self.defer(interaction), project, round_id, note)
        await reply(interaction, "Kudos queued. It will appear in the project channel.")

    async def project_autocomplete(self, interaction, current: str):
        current = str(current)
        try:
            actor = self.bot.actor(interaction)
            async with self.bot.repository.transaction() as tx:
                await self.services.require_board(tx, actor)
            projects = await self.services.projects(actor, include_archived=True)
        except UserError:
            return []
        return [
            app_commands.Choice(name=f"{p['name']} (#{p['id']})"[:100], value=p["id"])
            for p in projects
            if current.casefold() in p["name"].casefold() or current == str(p["id"])
        ][:25]


class SDCBot(commands.Bot):
    def __init__(self, config: Config):
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
            help_command=None,
        )
        self.config = config
        self.repository = Repository(config.database_path)
        self.services = Services(self.repository)
        self.dispatcher = Dispatcher(
            self.repository, DiscordTransport(self), guild_id=config.guild_id
        )
        self.tree.on_error = report_error

    def actor(self, interaction: discord.Interaction) -> Actor:
        if interaction.guild_id != self.config.guild_id or not isinstance(
            interaction.user, discord.Member
        ):
            raise PermissionDenied("Use this bot inside the configured SDC server.")
        return Actor(
            interaction.guild_id,
            interaction.user.id,
            frozenset(role.id for role in interaction.user.roles),
            interaction.user.guild_permissions.manage_guild,
            interaction.channel_id,
        )

    def make_view(self, payload: dict):
        if payload.get("view") == "prompt":
            return PromptView(self, payload["project_id"], payload["round_id"])
        if payload.get("view") == "support":
            return SupportView(self, payload["ticket_id"], payload["resolved"])
        if payload.get("view") == "checkin":
            return KudosView(self, payload["checkin_id"])
        return None

    async def setup_hook(self):
        await self.repository.open()
        await self.dispatcher.recover()
        cog = SDCCommands(self)
        await self.add_cog(cog)
        for command in self.tree.walk_commands():
            if isinstance(command, app_commands.Command) and any(
                parameter.name == "project" for parameter in command.parameters
            ):
                command.autocomplete("project")(cog.project_autocomplete)
        guild = discord.Object(id=self.config.guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        async with self.repository.transaction() as tx:
            for row in await tx.all("deliveries", guild_id=self.config.guild_id):
                ids = json.loads(row["message_ids"])
                payload = json.loads(row["payload_json"])
                if ids and (view := self.make_view(payload)):
                    self.add_view(view, message_id=ids[0])
        self.worker.start()

    @tasks.loop(seconds=5, reconnect=True)
    async def worker(self):
        try:
            await self.services.tick(self.config.guild_id)
        except Exception:
            log.exception("Scheduler reconciliation failed")
        try:
            await self.dispatcher.flush()
        except Exception:
            log.exception("Delivery reconciliation failed")

    @worker.before_loop
    async def before_worker(self):
        await self.wait_until_ready()

    async def on_ready(self):
        log.info("Connected as %s for guild %s; database ready", self.user, self.config.guild_id)
        if self.get_guild(self.config.guild_id) is None:
            log.error(
                "Bot is not installed in DISCORD_GUILD_ID; use the invite instructions in README.md"
            )

    async def close(self):
        task = self.worker.get_task()
        self.worker.cancel()
        if task:
            try:
                await task
            except asyncio.CancelledError:
                pass
        await super().close()
        await self.repository.close()
