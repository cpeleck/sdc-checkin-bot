import json
import sqlite3
from dataclasses import asdict
from datetime import date, datetime, timedelta

from .delivery import is_board_delivery
from .formatting import (
    label,
    render_changes,
    render_checkin,
    render_history,
    render_summary,
    render_ticket,
    safe,
)
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

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
TREND_ROUNDS = 4


def week_of(value: date) -> date:
    """The Monday of the week containing this date."""
    return value - timedelta(days=value.weekday())


class Services:
    def __init__(self, repository: Repository, clock=utc_now):
        self.repository = repository
        self.clock = clock

    async def settings(self, tx: UnitOfWork, guild_id: int) -> dict:
        settings = await tx.one("settings", guild_id=guild_id)
        if not settings:
            raise UserError("The bot has not been set up yet. Ask the server manager for help.")
        return settings

    async def require_board(self, tx: UnitOfWork, actor: Actor) -> dict:
        settings = await self.settings(tx, actor.guild_id)
        if not self.is_board(actor, settings):
            raise PermissionDenied("This action requires the configured board role.")
        if actor.channel_id != settings["board_channel_id"]:
            raise PermissionDenied("Use this action in the configured board channel.")
        return settings

    @staticmethod
    def is_board(actor: Actor, settings: dict) -> bool:
        return settings["board_role_id"] in actor.role_ids

    async def require_project(self, tx: UnitOfWork, guild_id: int, project_id: int) -> dict:
        project = await tx.one("projects", id=project_id, guild_id=guild_id)
        if not project:
            raise UserError("Project not found in this server.")
        return project

    async def channel_project(self, tx: UnitOfWork, actor: Actor) -> dict:
        projects = await tx.all("projects", guild_id=actor.guild_id, channel_id=actor.channel_id)
        if not projects:
            raise UserError("Use this command in a registered team channel.")
        if len(projects) > 1:
            raise UserError(
                "More than one project uses this channel. Ask the server manager for help."
            )
        return projects[0]

    async def checkin_channel(self, tx: UnitOfWork, participant: dict) -> int:
        prompt = await tx.one(
            "deliveries",
            delivery_key=f"prompt:{participant['round_id']}:{participant['project_id']}",
        )
        return prompt["channel_id"] if prompt else participant["channel_id"]

    async def setup(
        self, actor: Actor, board_role_id: int, board_channel_id: int, zone: str = "America/Chicago"
    ):
        if not actor.manage_guild:
            raise PermissionDenied("Setup requires Manage Server permission.")
        if actor.channel_id != board_channel_id:
            raise PermissionDenied("Run setup from the private channel you selected for the board.")
        timezone(zone)
        if board_role_id == actor.guild_id:
            raise UserError("The board role cannot be @everyone.")
        async with self.repository.transaction() as tx:
            if await tx.one("projects", guild_id=actor.guild_id, channel_id=board_channel_id):
                raise UserError("Choose a board channel that is separate from team channels.")
            open_round = await tx.one("rounds", guild_id=actor.guild_id, closed_at=None)
            if open_round and await tx.one(
                "round_projects", round_id=open_round["id"], channel_id=board_channel_id
            ):
                raise UserError("Choose a board channel that is separate from team channels.")
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
            await self.settings(tx, actor.guild_id)
            projects = await tx.all("projects", guild_id=actor.guild_id)
            return [p for p in projects if p["active"] or include_archived]

    async def save_project(self, actor: Actor, *, project_id: int | None = None, **changes):
        allowed = {"name", "channel_id", "contact_id", "milestone", "active"}
        if not changes.keys() <= allowed:
            raise ValueError("Unknown project field")
        if "name" in changes:
            changes["name"] = changes["name"].strip()
            if not 1 <= len(changes["name"]) <= 80 or "\n" in changes["name"]:
                raise UserError("Project names must be 1–80 characters on one line.")
        if len(changes.get("milestone", "")) > 1000:
            raise UserError("Milestones must be at most 1,000 characters.")
        try:
            async with self.repository.transaction() as tx:
                settings = await self.require_board(tx, actor)
                if "channel_id" in changes:
                    channel_id = changes["channel_id"]
                    if channel_id == settings["board_channel_id"]:
                        raise UserError(
                            "Choose a team channel that is separate from the board channel."
                        )
                    registered = await tx.all(
                        "projects", guild_id=actor.guild_id, channel_id=channel_id
                    )
                    open_round = await tx.one("rounds", guild_id=actor.guild_id, closed_at=None)
                    participants = (
                        await tx.all(
                            "round_projects", round_id=open_round["id"], channel_id=channel_id
                        )
                        if open_round
                        else []
                    )
                    if any(p["id"] != project_id for p in registered) or any(
                        p["project_id"] != project_id for p in participants
                    ):
                        raise Conflict("That channel is already in use by another project.")
                if project_id is not None:
                    await self.require_project(tx, actor.guild_id, project_id)
                    if changes:
                        await tx.update("projects", {"id": project_id}, **changes)
                else:
                    if not {"name", "channel_id"} <= changes.keys():
                        raise UserError("Name and team channel are required.")
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
                **{k: project[k] for k in ("name", "channel_id", "contact_id", "milestone")},
            )
            await tx.enqueue(
                guild_id=guild_id,
                key=f"prompt:{round_id}:{project['id']}",
                kind="prompt",
                entity_id=round_id,
                channel_id=project["channel_id"],
                now=stamp(now),
                payload={
                    "text": f"Weekly check-in: **{label(title)}**\n"
                    f"Due <t:{int(due.timestamp())}:F>. One update per project.\n"
                    "Your answers will be shared in this project channel and with "
                    "the SDC board. Anyone with access to this channel can edit.",
                    "project_id": project["id"],
                    "round_id": round_id,
                    "view": "prompt",
                },
            )
        return await tx.one("rounds", id=round_id)

    async def checkin_context(
        self, actor: Actor, project_id: int | None = None, round_id: int | None = None
    ) -> tuple[dict, dict, dict | None]:
        async with self.repository.transaction() as tx:
            await self.settings(tx, actor.guild_id)
            round_ = await self._get_round(tx, actor.guild_id, round_id, open_only=True)
            if project_id is None:
                participants = await tx.all(
                    "round_projects", round_id=round_["id"], channel_id=actor.channel_id
                )
                if len(participants) > 1:
                    raise UserError(
                        "More than one project uses this channel. Use your team's prompt."
                    )
                if participants:
                    project_id = participants[0]["project_id"]
                else:
                    project_id = (await self.channel_project(tx, actor))["id"]
            participant = await tx.one(
                "round_projects", round_id=round_["id"], project_id=project_id
            )
            if not participant:
                raise UserError("This project is not in this check-in round.")
            if await self.checkin_channel(tx, participant) != actor.channel_id:
                raise PermissionDenied("Use the team channel for this round's check-in.")
            existing = await tx.one(
                "checkins", round_id=round_["id"], project_id=participant["project_id"]
            )
            return participant, round_, existing

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
            settings = await self.settings(tx, actor.guild_id)
            round_ = await self._get_round(tx, actor.guild_id, round_id, open_only=True)
            participant = await tx.one("round_projects", round_id=round_id, project_id=project_id)
            if not participant:
                raise UserError("This project is not part of that round.")
            channel_id = await self.checkin_channel(tx, participant)
            if channel_id != actor.channel_id:
                raise PermissionDenied("Use the team channel for this round's check-in.")
            project = await self.require_project(tx, actor.guild_id, project_id)
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
                channel_id=channel_id,
                now=now,
                payload={
                    "text": render_checkin(participant, round_, checkin, existing),
                    "view": "checkin",
                    "checkin_id": checkin_id,
                },
            )
            if existing and existing["status"] != checkin["status"]:
                # Message edits do not notify anyone, so tell the board about status moves.
                await tx.enqueue(
                    guild_id=actor.guild_id,
                    key=f"status-change:{checkin_id}:{checkin['version']}",
                    kind="status_change",
                    entity_id=checkin_id,
                    channel_id=settings["board_channel_id"],
                    now=now,
                    payload={
                        "text": f"🔄 **{label(participant['name'])}** — "
                        f"{label(round_['label'])}: status changed "
                        f"**{existing['status']} → {checkin['status']}** "
                        f"(rev {checkin['version']} by <@{actor.user_id}>).\n"
                        f"Details: in <#{project['channel_id']}>, use /checkin changes "
                        f"revision:{checkin['version']} round_id:{round_id}."
                    },
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

    async def request_support(self, actor: Actor, description: str) -> dict:
        description = description.strip()
        if not 1 <= len(description) <= 2000:
            raise UserError("Describe the assistance needed in 1–2,000 characters.")
        now = stamp(self.clock())
        async with self.repository.transaction() as tx:
            settings = await self.settings(tx, actor.guild_id)
            project = await self.channel_project(tx, actor)
            ticket_id = await tx.insert(
                "support_tickets",
                guild_id=actor.guild_id,
                project_id=project["id"],
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

    async def support_list(self, actor: Actor) -> list[dict]:
        async with self.repository.transaction() as tx:
            await self.settings(tx, actor.guild_id)
            project = await self.channel_project(tx, actor)
            return await tx.all(
                "support_tickets", guild_id=actor.guild_id, project_id=project["id"]
            )

    async def board_support(self, actor: Actor) -> list[dict]:
        async with self.repository.transaction() as tx:
            await self.require_board(tx, actor)
            return await tx.all("support_tickets", guild_id=actor.guild_id)

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
            raise UserError("No matching round. Ask the board if a check-in round is open.")
        if open_only and round_["closed_at"]:
            raise Conflict("This round is closed; its submissions are frozen.")
        return round_

    async def _summary(self, tx: UnitOfWork, round_: dict, final: bool = False) -> str:
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
        checkins = await tx.all("checkins", round_id=round_["id"])
        kudos = {
            checkin["project_id"]: len(await tx.all("kudos", checkin_id=checkin["id"]))
            for checkin in checkins
        }
        return render_summary(
            round_,
            projects,
            checkins,
            tickets,
            trends=await self._trends(tx, round_, projects, final),
            kudos=kudos,
        )

    async def _trends(self, tx: UnitOfWork, round_: dict, projects: list[dict], final: bool):
        """Statuses per project over recent rounds, oldest first; None marks a missed round."""
        rounds = await tx.all("rounds", guild_id=round_["guild_id"])
        rounds = sorted((r for r in rounds if r["id"] <= round_["id"]), key=lambda r: r["id"])
        rounds = rounds[-TREND_ROUNDS:]
        if len(rounds) < 2:
            return []
        trends = []
        for project in projects:
            statuses = []
            for past in rounds:
                # Projects added later simply start their trend at the round they joined.
                if not await tx.one(
                    "round_projects", round_id=past["id"], project_id=project["project_id"]
                ):
                    continue
                checkin = await tx.one(
                    "checkins", round_id=past["id"], project_id=project["project_id"]
                )
                closing = final and past["id"] == round_["id"]
                if checkin is None and past["closed_at"] is None and not closing:
                    continue  # Still open: not missed yet.
                statuses.append(checkin["status"] if checkin else None)
            if len(statuses) >= 2:
                trends.append((project["name"], statuses))
        return trends

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
        summary = await self._summary(tx, round_, final=True)
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
                channel_id=await self.checkin_channel(tx, project),
                now=stamp(self.clock()),
                payload={
                    "text": f"Reminder: **{label(round_['label'])}** "
                    f"is missing your project update. Due "
                    f"<t:{int(instant(round_['due_at']).timestamp())}:F>. "
                    "Use the original prompt or /checkin submit.",
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
            settings = await self.require_board(tx, actor)
            delivery = await tx.one("deliveries", id=delivery_id, guild_id=actor.guild_id)
            if not delivery or delivery["state"] not in ("failed", "ambiguous", "retry"):
                raise UserError(
                    "Choose a failed, ambiguous, or retrying delivery from /sdc status."
                )
            destination = {}
            target = delivery["channel_id"] if channel_id is None else channel_id
            if is_board_delivery(delivery) and target != settings["board_channel_id"]:
                raise UserError("Retry this delivery in the configured board channel.")
            if target != delivery["channel_id"]:
                if delivery["kind"] == "prompt":
                    payload = json.loads(delivery["payload_json"])
                    project = await self.require_project(tx, actor.guild_id, payload["project_id"])
                    if target != project["channel_id"]:
                        raise UserError(
                            "Register the replacement as this project's team channel first."
                        )
                destination = {"channel_id": target, "message_ids": "[]"}
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
                    local_start = start.astimezone(timezone(settings["timezone"]))
                    skip = await tx.one(
                        "schedule_skips",
                        guild_id=guild_id,
                        week_start=week_of(local_start.date()).isoformat(),
                    )
                    if await tx.one("rounds", guild_id=guild_id, schedule_key=key):
                        pass  # This week's round already ran (or was closed early).
                    elif skip:
                        await self._skip_notices(tx, guild_id, skip, now)
                    elif await tx.one("projects", guild_id=guild_id, active=1):
                        round_ = await self._open_round(
                            tx, guild_id, f"Week of {local_start.date()}", end, "schedule", key
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
            await self._nudge(tx, settings, now)

    # --- History and revision changes -------------------------------------------------

    async def history(self, actor: Actor, rounds: int = 6, full: bool = False) -> str:
        if not 1 <= rounds <= 26:
            raise UserError("Choose between 1 and 26 rounds.")
        async with self.repository.transaction() as tx:
            await self.settings(tx, actor.guild_id)
            project = await self.channel_project(tx, actor)
            joined = await tx.all("round_projects", project_id=project["id"])
            entries = []
            for row in sorted(joined, key=lambda r: r["round_id"], reverse=True)[:rounds]:
                checkin = await tx.one(
                    "checkins", round_id=row["round_id"], project_id=project["id"]
                )
                kudos = len(await tx.all("kudos", checkin_id=checkin["id"])) if checkin else 0
                entries.append(
                    {
                        "round": await tx.one("rounds", id=row["round_id"]),
                        "checkin": checkin,
                        "kudos": kudos,
                    }
                )
            return render_history(project["name"], entries, full)

    async def changes(
        self,
        actor: Actor,
        revision: int | None = None,
        round_id: int | None = None,
    ) -> str:
        async with self.repository.transaction() as tx:
            await self.settings(tx, actor.guild_id)
            project = await self.channel_project(tx, actor)
            checkin = await self.find_checkin(tx, project["id"], round_id)
            round_ = await tx.one("rounds", id=checkin["round_id"], guild_id=actor.guild_id)
            if not round_:
                raise UserError("No matching round in this server.")
            latest = checkin["version"]
            revision = latest if revision is None else revision
            if not 1 <= revision <= latest:
                raise UserError(f"Choose a revision from 1 to {latest}.")
            saved = {
                row["version"]: json.loads(row["data_json"])
                for row in await tx.all("checkin_revisions", checkin_id=checkin["id"])
            }
            return render_changes(project["name"], round_, saved.get(revision - 1), saved[revision])

    # --- Kudos -----------------------------------------------------------------------

    async def find_checkin(self, tx: UnitOfWork, project_id: int, round_id: int | None) -> dict:
        if round_id is None:
            submitted = await tx.all("checkins", project_id=project_id)
            if not submitted:
                raise UserError("This project has not submitted any updates yet.")
            return max(submitted, key=lambda c: c["round_id"])
        checkin = await tx.one("checkins", round_id=round_id, project_id=project_id)
        if not checkin:
            raise UserError("This project has no update in that round.")
        return checkin

    async def give_kudos(
        self, actor: Actor, project_id: int, round_id: int | None = None, note: str = ""
    ) -> dict:
        async with self.repository.transaction() as tx:
            await self.require_board(tx, actor)
            await self.require_project(tx, actor.guild_id, project_id)
            checkin = await self.find_checkin(tx, project_id, round_id)
            return await self._record_kudos(tx, actor, checkin, note)

    async def kudos_card(self, tx: UnitOfWork, actor: Actor, checkin_id: int) -> dict:
        settings = await self.settings(tx, actor.guild_id)
        if not self.is_board(actor, settings):
            raise PermissionDenied("Only board members can give kudos.")
        card = await tx.one(
            "deliveries", guild_id=actor.guild_id, delivery_key=f"checkin:{checkin_id}"
        )
        checkin = await tx.one("checkins", id=checkin_id)
        if not card or not checkin:
            raise UserError("That update was not found in this server.")
        if card["channel_id"] != actor.channel_id:
            raise PermissionDenied("Use the Kudos button in the update's team channel.")
        return checkin

    async def give_kudos_from_card(self, actor: Actor, checkin_id: int, note: str) -> dict:
        async with self.repository.transaction() as tx:
            checkin = await self.kudos_card(tx, actor, checkin_id)
            return await self._record_kudos(tx, actor, checkin, note)

    async def _record_kudos(self, tx: UnitOfWork, actor: Actor, checkin: dict, note: str) -> dict:
        note = note.strip()
        if len(note) > 300:
            raise UserError("Keep kudos notes to 300 characters.")
        checkin_id = checkin["id"]
        round_ = await tx.one("rounds", id=checkin["round_id"], guild_id=actor.guild_id)
        if not round_:
            raise UserError("That update was not found in this server.")
        if await tx.one("kudos", checkin_id=checkin_id, author_id=actor.user_id):
            raise Conflict("You already gave kudos to this update.")
        participant = await tx.one(
            "round_projects", round_id=round_["id"], project_id=checkin["project_id"]
        )
        card = await tx.one(
            "deliveries", guild_id=actor.guild_id, delivery_key=f"checkin:{checkin_id}"
        )
        channel_id = card["channel_id"] if card else await self.checkin_channel(tx, participant)
        now = stamp(self.clock())
        kudos_id = await tx.insert(
            "kudos", checkin_id=checkin_id, author_id=actor.user_id, note=note, created_at=now
        )
        await tx.enqueue(
            guild_id=actor.guild_id,
            key=f"kudos:{kudos_id}",
            kind="kudos",
            entity_id=kudos_id,
            channel_id=channel_id,
            now=now,
            payload={
                "text": f"🎉 <@{actor.user_id}> gave **{label(participant['name'])}** "
                f"kudos for **{label(round_['label'])}**" + (f": {safe(note)}" if note else "!")
            },
        )
        return await tx.one("kudos", id=kudos_id)

    # --- Stale support nudges --------------------------------------------------------

    async def configure_nudges(self, actor: Actor, days: int):
        if not 0 <= days <= 60:
            raise UserError("Use 1–60 days, or 0 to turn nudges off.")
        async with self.repository.transaction() as tx:
            await self.require_board(tx, actor)
            await tx.update("settings", {"guild_id": actor.guild_id}, nudge_days=days or None)

    async def _nudge(self, tx: UnitOfWork, settings: dict, now: datetime):
        days = settings["nudge_days"]
        if not days:
            return
        for ticket in await tx.all("support_tickets", guild_id=settings["guild_id"]):
            if ticket["state"] == "resolved":
                continue
            notes = await tx.all("support_notes", ticket_id=ticket["id"])
            # Board activity resets the clock; a team revising its check-in does not.
            activity = max(
                [instant(ticket["created_at"])]
                + [instant(n["created_at"]) for n in notes if n["action"] != "nudge"]
            )
            touched = max(
                [activity] + [instant(n["created_at"]) for n in notes if n["action"] == "nudge"]
            )
            if now - touched < timedelta(days=days):
                continue
            project = await tx.one("projects", id=ticket["project_id"])
            assignee = ticket["assignee_id"]
            target = f"<@{assignee}>" if assignee else f"<@&{settings['board_role_id']}>"
            idle = (now - activity).days
            if ticket["state"] == "open":
                problem = f"has waited {idle} day(s) with no acknowledgement."
            else:
                problem = f"has had no board follow-up for {idle} day(s)."
            card = await tx.one("deliveries", delivery_key=f"support-board:{ticket['id']}")
            ids = json.loads(card["message_ids"]) if card else []
            link = (
                f"\nOriginal card: https://discord.com/channels/{settings['guild_id']}/"
                f"{card['channel_id']}/{ids[0]}"
                if ids
                else ""
            )
            await tx.insert(
                "support_notes",
                ticket_id=ticket["id"],
                author_id=0,
                action="nudge",
                note=target,
                created_at=stamp(now),
            )
            await tx.enqueue(
                guild_id=settings["guild_id"],
                key=f"nudge:{ticket['id']}:{stamp(now)}",
                kind="nudge",
                entity_id=ticket["id"],
                channel_id=settings["board_channel_id"],
                now=stamp(now),
                payload={
                    "text": f"⏰ {target} Support #{ticket['id']} — "
                    f"**{label(project['name'])}** {problem}{link}",
                    "view": "support",
                    "ticket_id": ticket["id"],
                    "resolved": False,
                    "user_ids": [assignee] if assignee else [],
                    "role_ids": [] if assignee else [settings["board_role_id"]],
                },
            )
            # Show the reminder in the follow-up history on both ticket cards.
            await self._queue_ticket(tx, ticket["id"], settings, notify=False)

    # --- Skipped weeks ---------------------------------------------------------------

    async def skip_week(self, actor: Actor, day: str, reason: str = "") -> date:
        try:
            chosen = date.fromisoformat(day.strip())
        except ValueError as exc:
            raise UserError("Use a date like 2026-11-23.") from exc
        reason = " ".join(reason.split())
        if len(reason) > 200:
            raise UserError("Keep the reason to 200 characters.")
        async with self.repository.transaction() as tx:
            settings = await self.require_board(tx, actor)
            today = self.clock().astimezone(timezone(settings["timezone"])).date()
            week = week_of(chosen)
            if week < week_of(today):
                raise UserError("That week has already passed.")
            if await tx.one("schedule_skips", guild_id=actor.guild_id, week_start=week.isoformat()):
                raise Conflict("That week is already skipped. Use /schedule unskip first.")
            await tx.insert(
                "schedule_skips",
                guild_id=actor.guild_id,
                week_start=week.isoformat(),
                reason=reason,
                created_by=actor.user_id,
                created_at=stamp(self.clock()),
            )
            return week

    async def unskip_week(self, actor: Actor, day: str) -> date:
        try:
            week = week_of(date.fromisoformat(day.strip()))
        except ValueError as exc:
            raise UserError("Use a date like 2026-11-23.") from exc
        async with self.repository.transaction() as tx:
            await self.require_board(tx, actor)
            if not await tx.delete(
                "schedule_skips", guild_id=actor.guild_id, week_start=week.isoformat()
            ):
                raise UserError("That week is not skipped.")
            return week

    async def skips(self, actor: Actor) -> list[dict]:
        async with self.repository.transaction() as tx:
            settings = await self.require_board(tx, actor)
            current = week_of(self.clock().astimezone(timezone(settings["timezone"])).date())
            rows = await tx.all("schedule_skips", guild_id=actor.guild_id)
            return sorted(
                (r for r in rows if r["week_start"] >= current.isoformat()),
                key=lambda r: r["week_start"],
            )

    async def _skip_notices(self, tx: UnitOfWork, guild_id: int, skip: dict, now: datetime):
        reason = f": {safe(skip['reason'])}" if skip["reason"] else ""
        for project in await tx.all("projects", guild_id=guild_id, active=1):
            key = f"skip-notice:{guild_id}:{skip['week_start']}:{project['id']}"
            if await tx.one("deliveries", delivery_key=key):
                continue  # Post once per skipped week, not every tick.
            await tx.enqueue(
                guild_id=guild_id,
                key=key,
                kind="skip_notice",
                entity_id=project["id"],
                channel_id=project["channel_id"],
                now=stamp(now),
                payload={
                    "text": f"No check-in this week{reason}. Regular check-ins resume next week."
                },
            )

    async def schedule_lines(self, actor: Actor) -> list[str]:
        """Human-readable schedule, next opening, and skipped weeks for /sdc status."""
        from .scheduler import WeeklySchedule

        async with self.repository.transaction() as tx:
            settings = await self.require_board(tx, actor)
            skips = {
                r["week_start"]: r for r in await tx.all("schedule_skips", guild_id=actor.guild_id)
            }
        lines = []
        if settings["nudge_days"]:
            lines.append(f"Stale-ticket nudges: after {settings['nudge_days']} day(s)")
        else:
            lines.append("Stale-ticket nudges: off")
        if not settings["schedule_json"]:
            return ["Schedule: Disabled (manual pilot)"] + lines
        schedule = WeeklySchedule(**json.loads(settings["schedule_json"]))
        zone = timezone(settings["timezone"])
        lines.insert(
            0,
            f"Schedule: opens {DAYS[schedule.open_day]} {schedule.open_time}, "
            f"closes {DAYS[schedule.close_day]} {schedule.close_time}",
        )
        now = self.clock()
        skipped = []
        for weeks in range(1, 9):
            start, _ = schedule.window(now + timedelta(weeks=weeks), settings["timezone"])
            local = start.astimezone(zone).date()
            if skip := skips.get(week_of(local).isoformat()):
                skipped.append(
                    f"{local.isoformat()} skipped{': ' + label(skip['reason']) if skip['reason'] else ''}"
                )
                continue
            extra = f" ({'; '.join(skipped)})" if skipped else ""
            lines.insert(1, f"Next opening: <t:{int(start.timestamp())}:F>{extra}")
            break
        return lines
