import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta

from .formatting import label, render_checkin, render_summary, render_ticket, safe
from .models import (
    Actor,
    CheckinInput,
    Conflict,
    PermissionDenied,
    UserError,
    instant,
    parse_due,
    stamp,
    timezone,
    utc_now,
)
from .repository import Repository, UnitOfWork


class Services:
    def __init__(self, repository: Repository, clock=utc_now):
        self.repository = repository
        self.clock = clock

    async def settings(self, tx: UnitOfWork, guild_id: int) -> dict:
        settings = await tx.one("settings", guild_id=guild_id)
        if not settings:
            raise UserError("A server manager must run /sdc setup first.")
        return settings

    async def require_board(self, tx: UnitOfWork, actor: Actor) -> dict:
        settings = await self.settings(tx, actor.guild_id)
        if not self.is_board(actor, settings):
            raise PermissionDenied("This action requires the configured board role.")
        return settings

    @staticmethod
    def is_board(actor: Actor, settings: dict) -> bool:
        return actor.manage_guild or settings["board_role_id"] in actor.role_ids

    async def require_project(self, tx: UnitOfWork, actor: Actor, project_id: int) -> dict:
        settings = await self.settings(tx, actor.guild_id)
        project = await tx.one("projects", id=project_id, guild_id=actor.guild_id)
        if not project:
            raise UserError("Project not found in this server.")
        if not self.is_board(actor, settings) and project["role_id"] not in actor.role_ids:
            raise PermissionDenied("You need this project's team role or the board role.")
        return project

    async def setup(
        self, actor: Actor, board_role_id: int, board_channel_id: int, zone: str = "America/Chicago"
    ):
        if not actor.manage_guild:
            raise PermissionDenied("Setup requires Discord's Manage Server permission.")
        timezone(zone)
        if board_role_id == actor.guild_id:
            raise UserError("The board role cannot be @everyone.")
        async with self.repository.transaction() as tx:
            values = dict(
                board_role_id=board_role_id, board_channel_id=board_channel_id, timezone=zone
            )
            if await tx.one("settings", guild_id=actor.guild_id):
                # A changed timezone starts a new scheduling epoch, avoiding backfill.
                await tx.update(
                    "settings",
                    {"guild_id": actor.guild_id},
                    **values,
                    schedule_updated_at=stamp(self.clock()),
                )
            else:
                await tx.insert("settings", guild_id=actor.guild_id, **values)

    async def projects(self, actor: Actor, include_archived: bool = False) -> list[dict]:
        async with self.repository.transaction() as tx:
            settings = await self.settings(tx, actor.guild_id)
            projects = await tx.all("projects", guild_id=actor.guild_id)
            return [
                p
                for p in projects
                if (p["active"] or include_archived)
                and (self.is_board(actor, settings) or p["role_id"] in actor.role_ids)
            ]

    async def save_project(self, actor: Actor, *, project_id: int | None = None, **changes):
        allowed = {"name", "channel_id", "role_id", "contact_id", "milestone", "active"}
        if not changes.keys() <= allowed:
            raise ValueError("Unknown project field")
        if "name" in changes:
            changes["name"] = changes["name"].strip()
            if not 1 <= len(changes["name"]) <= 80 or "\n" in changes["name"]:
                raise UserError("Project names must be 1–80 characters on one line.")
        if len(changes.get("milestone", "")) > 1000:
            raise UserError("Milestones must be at most 1,000 characters.")
        if changes.get("role_id") == actor.guild_id:
            raise UserError("The project role cannot be @everyone.")
        try:
            async with self.repository.transaction() as tx:
                await self.require_board(tx, actor)
                if project_id is not None:
                    await self.require_project(tx, actor, project_id)
                    if changes:
                        await tx.update("projects", {"id": project_id}, **changes)
                else:
                    if not {"name", "channel_id", "role_id"} <= changes.keys():
                        raise UserError("Name, project channel, and team role are required.")
                    project_id = await tx.insert("projects", guild_id=actor.guild_id, **changes)
                return await tx.one("projects", id=project_id)
        except sqlite3.IntegrityError as exc:
            raise Conflict("A project with that name already exists; edit it instead.") from exc

    async def open_round(self, actor: Actor, title: str, due: str) -> dict:
        async with self.repository.transaction() as tx:
            settings = await self.require_board(tx, actor)
            return await self._open_round(
                tx, actor.guild_id, title, parse_due(due, settings["timezone"]), "manual"
            )

    async def _open_round(
        self,
        tx: UnitOfWork,
        guild_id: int,
        title: str,
        due: datetime,
        source: str,
        schedule_key: str | None = None,
    ) -> dict:
        now = self.clock()
        if not title.strip() or len(title) > 100:
            raise UserError("Use a round label of 1–100 characters.")
        if due <= now:
            raise UserError("The deadline must be in the future.")
        if await tx.one("rounds", guild_id=guild_id, closed_at=None):
            raise Conflict("A round is already open. Close it before opening another.")
        projects = await tx.all("projects", guild_id=guild_id, active=1)
        if not projects:
            raise UserError("Register at least one active project first.")
        round_id = await tx.insert(
            "rounds",
            guild_id=guild_id,
            label=title.strip(),
            opened_at=stamp(now),
            due_at=stamp(due),
            source=source,
            schedule_key=schedule_key,
        )
        for project in projects:
            await tx.insert(
                "round_projects",
                round_id=round_id,
                project_id=project["id"],
                **{
                    k: project[k]
                    for k in ("name", "channel_id", "role_id", "contact_id", "milestone")
                },
            )
            await tx.enqueue(
                guild_id=guild_id,
                key=f"prompt:{round_id}:{project['id']}",
                kind="prompt",
                entity_id=round_id,
                channel_id=project["channel_id"],
                now=stamp(now),
                payload={
                    "text": f"<@&{project['role_id']}> Weekly check-in: **{label(title)}**\n"
                    f"Due <t:{int(due.timestamp())}:F>. One update per project.\n"
                    "Your answers will be shared in this project channel and with "
                    "the SDC board. Any teammate with the project role can edit.",
                    "project_id": project["id"],
                    "round_id": round_id,
                    "role_ids": [project["role_id"]],
                    "view": "prompt",
                },
            )
        return await tx.one("rounds", id=round_id)

    async def checkin_context(
        self, actor: Actor, project_id: int, round_id: int | None = None
    ) -> tuple[dict, dict, dict | None]:
        async with self.repository.transaction() as tx:
            project = await self.require_project(tx, actor, project_id)
            round_ = await self._get_round(tx, actor.guild_id, round_id, open_only=True)
            if not await tx.one("round_projects", round_id=round_["id"], project_id=project_id):
                raise UserError("This project is not in this round; it will join the next round.")
            existing = await tx.one("checkins", round_id=round_["id"], project_id=project_id)
            return project, round_, existing

    async def submit(
        self,
        actor: Actor,
        project_id: int,
        round_id: int,
        data: CheckinInput,
        expected_version: int,
    ) -> dict:
        data = data.validated()
        now = stamp(self.clock())
        async with self.repository.transaction() as tx:
            project = await self.require_project(tx, actor, project_id)
            settings = await self.settings(tx, actor.guild_id)
            round_ = await self._get_round(tx, actor.guild_id, round_id, open_only=True)
            participant = await tx.one("round_projects", round_id=round_id, project_id=project_id)
            if not participant:
                raise UserError("This project is not part of that round.")
            existing = await tx.one("checkins", round_id=round_id, project_id=project_id)
            version = existing["version"] if existing else 0
            if version != expected_version:
                raise Conflict(
                    "A teammate edited this update. Reopen the form to load their version."
                )
            values = dict(
                **asdict(data),
                author_id=actor.user_id,
                updated_at=now,
                late=int(self.clock() > instant(round_["due_at"])),
                version=version + 1,
            )
            if existing:
                await tx.update("checkins", {"id": existing["id"], "version": version}, **values)
                checkin_id = existing["id"]
            else:
                checkin_id = await tx.insert(
                    "checkins", round_id=round_id, project_id=project_id, created_at=now, **values
                )
            checkin = await tx.one("checkins", id=checkin_id)
            await tx.insert(
                "checkin_revisions",
                checkin_id=checkin_id,
                version=version + 1,
                data_json=json.dumps(checkin),
            )
            await tx.enqueue(
                guild_id=actor.guild_id,
                key=f"checkin:{checkin_id}",
                kind="checkin",
                entity_id=checkin_id,
                channel_id=participant["channel_id"],
                now=now,
                payload={"text": render_checkin(participant, round_, checkin)},
            )
            ticket = await tx.one("support_tickets", checkin_id=checkin_id)
            if ticket or data.needs_support:
                description = (
                    f"Status: {data.status}\nBlockers: {data.blockers or 'None reported'}\n"
                    f"Assistance: {data.assistance or 'None requested'}"
                )
                if ticket:
                    await tx.update(
                        "support_tickets",
                        {"id": ticket["id"]},
                        description=description,
                        updated_at=now,
                    )
                    ticket_id = ticket["id"]
                else:
                    ticket_id = await tx.insert(
                        "support_tickets",
                        guild_id=actor.guild_id,
                        project_id=project_id,
                        checkin_id=checkin_id,
                        description=description,
                        state="open",
                        assignee_id=project["contact_id"],
                        reporter_id=actor.user_id,
                        created_at=now,
                        updated_at=now,
                    )
                await self._queue_ticket(tx, ticket_id, settings, notify=not ticket)
            return checkin

    async def request_support(self, actor: Actor, project_id: int, description: str) -> dict:
        description = description.strip()
        if not 1 <= len(description) <= 2000:
            raise UserError("Describe the assistance needed in 1–2,000 characters.")
        now = stamp(self.clock())
        async with self.repository.transaction() as tx:
            project = await self.require_project(tx, actor, project_id)
            settings = await self.settings(tx, actor.guild_id)
            ticket_id = await tx.insert(
                "support_tickets",
                guild_id=actor.guild_id,
                project_id=project_id,
                description=description,
                state="open",
                assignee_id=project["contact_id"],
                reporter_id=actor.user_id,
                created_at=now,
                updated_at=now,
            )
            await self._queue_ticket(tx, ticket_id, settings, notify=True)
            return await tx.one("support_tickets", id=ticket_id)

    async def act_on_ticket(
        self,
        actor: Actor,
        ticket_id: int,
        action: str,
        note: str = "",
        assignee_id: int | None = None,
    ) -> dict:
        if action not in ("acknowledge", "assign", "resolve"):
            raise ValueError("Unknown support action")
        if len(note) > 1500:
            raise UserError("Follow-up notes must be at most 1,500 characters.")
        if action == "resolve" and not note.strip():
            raise UserError("Include a resolution note or resource link.")
        now = stamp(self.clock())
        async with self.repository.transaction() as tx:
            settings = await self.require_board(tx, actor)
            ticket = await tx.one("support_tickets", id=ticket_id, guild_id=actor.guild_id)
            if not ticket:
                raise UserError("Support request not found in this server.")
            if ticket["state"] == "resolved":
                raise Conflict(
                    "This request is already resolved. Create a new request for new help."
                )
            values = {"updated_at": now}
            if action == "acknowledge":
                values.update(state="acknowledged", assignee_id=actor.user_id)
            elif action == "assign":
                if not assignee_id:
                    raise UserError("Choose a board member to assign.")
                values["assignee_id"] = assignee_id
            else:
                values.update(state="resolved", resolved_at=now)
            await tx.update("support_tickets", {"id": ticket_id}, **values)
            await tx.insert(
                "support_notes",
                ticket_id=ticket_id,
                author_id=actor.user_id,
                action=action,
                note=note.strip() or action.title(),
                created_at=now,
            )
            await self._queue_ticket(tx, ticket_id, settings, notify=action == "assign")
            return await tx.one("support_tickets", id=ticket_id)

    async def _queue_ticket(self, tx: UnitOfWork, ticket_id: int, settings: dict, notify: bool):
        ticket = await tx.one("support_tickets", id=ticket_id)
        project = await tx.one("projects", id=ticket["project_id"])
        notes = await tx.all("support_notes", ticket_id=ticket_id)
        text = render_ticket(ticket, project, notes)
        target = (
            f"<@{ticket['assignee_id']}>"
            if ticket["assignee_id"]
            else f"<@&{settings['board_role_id']}>"
        )
        for destination, channel_id in (
            ("board", settings["board_channel_id"]),
            ("team", project["channel_id"]),
        ):
            board = destination == "board"
            await tx.enqueue(
                guild_id=ticket["guild_id"],
                key=f"support-{destination}:{ticket_id}",
                kind="support",
                entity_id=ticket_id,
                channel_id=channel_id,
                now=stamp(self.clock()),
                payload={
                    "text": (f"{target}\n" if board else "") + text,
                    "view": "support" if board else None,
                    "ticket_id": ticket_id,
                    "resolved": ticket["state"] == "resolved",
                    "user_ids": [ticket["assignee_id"]]
                    if board and notify and ticket["assignee_id"]
                    else [],
                    "role_ids": [settings["board_role_id"]]
                    if board and notify and not ticket["assignee_id"]
                    else [],
                },
            )

    async def support_list(self, actor: Actor, project_id: int | None = None) -> list[dict]:
        async with self.repository.transaction() as tx:
            if project_id is None:
                await self.require_board(tx, actor)
                return await tx.all("support_tickets", guild_id=actor.guild_id)
            await self.require_project(tx, actor, project_id)
            return await tx.all("support_tickets", guild_id=actor.guild_id, project_id=project_id)

    async def _get_round(
        self, tx: UnitOfWork, guild_id: int, round_id: int | None, open_only: bool = False
    ) -> dict:
        where = {"guild_id": guild_id}
        if round_id is not None:
            where["id"] = round_id
        else:
            where["closed_at"] = None
        round_ = await tx.one("rounds", **where)
        if not round_:
            raise UserError("No matching round. Ask the board to open one with /round open.")
        if open_only and round_["closed_at"]:
            raise Conflict("This round is closed; its submissions are frozen.")
        return round_

    async def _summary(self, tx: UnitOfWork, round_: dict) -> str:
        if round_["summary"] is not None:
            return round_["summary"]
        projects = await tx.all("round_projects", round_id=round_["id"])
        # Include current contact assignments, then freeze them into the closed digest.
        for project in projects:
            current = await tx.one("projects", id=project["project_id"])
            project["contact_id"] = current["contact_id"]
        tickets = await tx.all("support_tickets", guild_id=round_["guild_id"])
        for ticket in tickets:
            project = await tx.one("projects", id=ticket["project_id"])
            ticket["project_name"] = project["name"]
        return render_summary(
            round_,
            projects,
            await tx.all("checkins", round_id=round_["id"]),
            tickets,
        )

    async def summary(self, actor: Actor, round_id: int, publish: bool = False) -> str:
        async with self.repository.transaction() as tx:
            settings = await self.require_board(tx, actor)
            round_ = await self._get_round(tx, actor.guild_id, round_id)
            summary = await self._summary(tx, round_)
            if publish:
                await self._queue_summary(tx, round_, settings, summary)
            return summary

    async def _queue_summary(self, tx: UnitOfWork, round_: dict, settings: dict, summary: str):
        await tx.enqueue(
            guild_id=round_["guild_id"],
            key=f"summary:{round_['id']}",
            kind="summary",
            entity_id=round_["id"],
            channel_id=settings["board_channel_id"],
            now=stamp(self.clock()),
            payload={"text": summary, "attachment": f"sdc-round-{round_['id']}.md"},
        )

    async def close_round(self, actor: Actor) -> dict:
        async with self.repository.transaction() as tx:
            settings = await self.require_board(tx, actor)
            round_ = await self._get_round(tx, actor.guild_id, None, open_only=True)
            return await self._close_round(tx, round_, settings)

    async def _close_round(self, tx: UnitOfWork, round_: dict, settings: dict) -> dict:
        summary = await self._summary(tx, round_)
        await tx.update(
            "rounds", {"id": round_["id"]}, closed_at=stamp(self.clock()), summary=summary
        )
        await self._queue_summary(tx, round_, settings, summary)
        return await tx.one("rounds", id=round_["id"])

    async def remind(self, actor: Actor) -> int:
        async with self.repository.transaction() as tx:
            await self.require_board(tx, actor)
            round_ = await self._get_round(tx, actor.guild_id, None, open_only=True)
            return await self._remind(tx, round_, f"manual:{stamp(self.clock())}")

    async def _remind(self, tx: UnitOfWork, round_: dict, event: str) -> int:
        count = 0
        for project in await tx.all("round_projects", round_id=round_["id"]):
            if await tx.one("checkins", round_id=round_["id"], project_id=project["project_id"]):
                continue
            await tx.enqueue(
                guild_id=round_["guild_id"],
                key=f"reminder:{round_['id']}:{project['project_id']}:{event}",
                kind="reminder",
                entity_id=round_["id"],
                channel_id=project["channel_id"],
                now=stamp(self.clock()),
                payload={
                    "text": f"<@&{project['role_id']}> Reminder: **{label(round_['label'])}** "
                    f"is missing your project update. Due "
                    f"<t:{int(instant(round_['due_at']).timestamp())}:F>. "
                    "Use the original prompt or /checkin submit.",
                    "role_ids": [project["role_id"]],
                    "project_id": project["project_id"],
                    "round_id": round_["id"],
                    "automatic": event == "automatic",
                },
            )
            count += 1
        return count

    async def overview(self, actor: Actor) -> str:
        async with self.repository.transaction() as tx:
            await self.require_board(tx, actor)
            projects = await tx.all("projects", guild_id=actor.guild_id, active=1)
            tickets = await tx.all("support_tickets", guild_id=actor.guild_id)
            unresolved = [ticket for ticket in tickets if ticket["state"] != "resolved"]
            unassigned = ", ".join(label(p["name"]) for p in projects if not p["contact_id"])
            round_ = await tx.one("rounds", guild_id=actor.guild_id, closed_at=None)
            lines = [
                "# SDC board overview",
                f"Unassigned project contacts: {unassigned or 'None'}",
                f"Open support requests: {len(unresolved)}",
            ]
            for ticket in unresolved:
                lines.append(
                    f"- #{ticket['id']} · project #{ticket['project_id']} · "
                    f"{ticket['state']} · {safe(ticket['description'])}"
                )
            if round_:
                if self.clock() > instant(round_["due_at"]):
                    lines.append(
                        "\n**Deadline passed. Manual rounds stay open until /round close.**"
                    )
                lines.append(await self._summary(tx, round_))
            else:
                lines.append("No open round.")
            return "\n".join(lines)

    async def diagnostics(self, actor: Actor) -> list[dict]:
        async with self.repository.transaction() as tx:
            await self.require_board(tx, actor)
            return [
                row
                for row in await tx.all("deliveries", guild_id=actor.guild_id)
                if row["state"] in ("failed", "ambiguous", "retry")
            ]

    async def retry_delivery(self, actor: Actor, delivery_id: int, channel_id: int | None = None):
        async with self.repository.transaction() as tx:
            await self.require_board(tx, actor)
            delivery = await tx.one("deliveries", id=delivery_id, guild_id=actor.guild_id)
            if not delivery or delivery["state"] not in ("failed", "ambiguous", "retry"):
                raise UserError(
                    "Choose a failed, ambiguous, or retrying delivery from /sdc status."
                )
            destination = {}
            if channel_id is not None and channel_id != delivery["channel_id"]:
                destination = {"channel_id": channel_id, "message_ids": "[]"}
            await tx.update(
                "deliveries",
                {"id": delivery_id},
                state="pending",
                attempts=0,
                next_attempt_at=None,
                error=None,
                updated_at=stamp(self.clock()),
                **destination,
            )

    async def configure_schedule(
        self, actor: Actor, open_day: int, open_time: str, close_day: int, close_time: str
    ):
        from .scheduler import WeeklySchedule

        schedule = WeeklySchedule.parse(open_day, open_time, close_day, close_time)
        async with self.repository.transaction() as tx:
            await self.require_board(tx, actor)
            await tx.update(
                "settings",
                {"guild_id": actor.guild_id},
                schedule_json=json.dumps(asdict(schedule)),
                schedule_updated_at=stamp(self.clock()),
            )

    async def disable_schedule(self, actor: Actor):
        async with self.repository.transaction() as tx:
            await self.require_board(tx, actor)
            await tx.update("settings", {"guild_id": actor.guild_id}, schedule_json=None)

    async def tick(self, guild_id: int):
        from .scheduler import WeeklySchedule

        now = self.clock()
        async with self.repository.transaction() as tx:
            settings = await tx.one("settings", guild_id=guild_id)
            if not settings:
                return
            round_ = await tx.one("rounds", guild_id=guild_id, closed_at=None)
            # Already-open automated rounds still finish if recurring opening is disabled.
            if round_ and round_["source"] == "schedule" and instant(round_["due_at"]) <= now:
                await self._close_round(tx, round_, settings)
                round_ = None
            if not round_ and settings["schedule_json"]:
                schedule = WeeklySchedule(**json.loads(settings["schedule_json"]))
                start, end = schedule.window(now, settings["timezone"])
                enabled_at = instant(settings["schedule_updated_at"])
                if start <= now < end and start >= enabled_at:
                    key = stamp(start)
                    if not await tx.one("rounds", guild_id=guild_id, schedule_key=key):
                        if await tx.one("projects", guild_id=guild_id, active=1):
                            round_ = await self._open_round(
                                tx,
                                guild_id,
                                f"Week of {start.astimezone(timezone(settings['timezone'])).date()}",
                                end,
                                "schedule",
                                key,
                            )
            if round_:
                due = instant(round_["due_at"])
                remind_at = due - timedelta(hours=24)
                if instant(round_["opened_at"]) <= remind_at <= now < due:
                    # enqueue only once, including when a late submission is later revised.
                    marker = f"reminder:{round_['id']}:automatic"
                    if not await tx.one("deliveries", delivery_key=marker):
                        await self._remind(tx, round_, "automatic")
                        await tx.enqueue(
                            guild_id=guild_id,
                            key=marker,
                            kind="marker",
                            entity_id=round_["id"],
                            channel_id=settings["board_channel_id"],
                            payload={},
                            now=stamp(now),
                        )
                        await tx.update("deliveries", {"delivery_key": marker}, state="sent")
