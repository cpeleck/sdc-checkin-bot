"""Deterministic Markdown rendering with inert user-supplied mentions."""

import difflib
import re
from datetime import datetime

FIELDS = (
    ("status", "Status"),
    ("progress", "Progress"),
    ("next_steps", "Next steps"),
    ("blockers", "Blockers"),
    ("assistance", "Assistance"),
)
SEVERITY = {"On track": 0, "At risk": 1, "Blocked": 2}


def safe(value: str) -> str:
    value = value.replace("@", "@\u200b").replace("<", "‹").replace(">", "›")
    return re.sub(r"([\\`*_~|#\[\]])", r"\\\1", value)


def label(value: str) -> str:
    return safe(" ".join(value.splitlines()))


def split_message(text: str, limit: int = 1900) -> list[str]:
    """Keep even a single overlong line within Discord's 2,000 character limit."""
    if not text:
        return ["(empty)"]
    chunks = []
    while len(text.encode("utf-16-le")) // 2 > limit:
        low, high = 0, min(len(text), limit)
        while low < high:
            middle = (low + high + 1) // 2
            if len(text[:middle].encode("utf-16-le")) // 2 <= limit:
                low = middle
            else:
                high = middle - 1
        cut = text.rfind("\n", 0, low + 1)
        if cut < low // 2:
            cut = low
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


def shorten(value: str, limit: int) -> str:
    """Trim raw text before escaping so escapes are never cut in half."""
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def code(value: str) -> str:
    """Text for a code block: backticks are swapped so users cannot close the block."""
    return value.replace("`", "ˋ")


def changed_fields(previous: dict, current: dict) -> list[str]:
    changes = []
    for key, name in FIELDS:
        if previous[key] == current[key]:
            continue
        if key == "status":
            changes.append(f"Status ({previous[key]} → {current[key]})")
        else:
            changes.append(name)
    return changes


def render_checkin(project: dict, round_: dict, checkin: dict, previous: dict | None = None) -> str:
    late = " · Late" if checkin["late"] else ""
    changes = ""
    if previous is not None:
        fields = changed_fields(previous, checkin)
        changes = (
            f"Changed in rev {checkin['version']}: {', '.join(fields)}\n"
            if fields
            else f"No content changes in rev {checkin['version']}\n"
        )
    return (
        f"## {label(project['name'])} — {label(round_['label'])}\n"
        f"**{checkin['status']}**{late} · Revision {checkin['version']}\n"
        f"Updated by <@{checkin['author_id']}>\n{changes}\n"
        f"**Progress**\n{safe(checkin['progress'])}\n\n"
        f"**Next steps / milestone**\n{safe(checkin['next_steps'])}\n\n"
        f"**Blockers**\n{safe(checkin['blockers']) or 'None reported'}\n\n"
        f"**Assistance requested**\n{safe(checkin['assistance']) or 'None requested'}"
    )


def render_history(project_name: str, entries: list[dict], full: bool = False) -> str:
    """entries: newest first, each {"round", "checkin" (or None), "kudos"}."""
    lines = [f"## {label(project_name)} — check-in history (last {len(entries)} rounds)"]
    if not entries:
        lines.append("This project has not been part of any round yet.")
    for entry in entries:
        round_, checkin = entry["round"], entry["checkin"]
        state = "" if round_["closed_at"] else " · open"
        if checkin is None:
            lines.append(f"\n**{label(round_['label'])}**{state} · — no update submitted —")
            continue
        late = " · Late" if checkin["late"] else ""
        kudos = f" · 🎉 {entry['kudos']}" if entry["kudos"] else ""
        lines.append(
            f"\n**{label(round_['label'])}**{state} · {checkin['status']}{late} · "
            f"rev {checkin['version']} · <@{checkin['author_id']}>{kudos}"
        )
        for key, name in FIELDS[1:]:
            value = checkin[key]
            if not value and key in ("blockers", "assistance"):
                continue
            text = safe(value) if full else safe(shorten(value, 200))
            lines.append(f"> {name}: {text}" if not full else f"**{name}**\n{text}")
    return "\n".join(lines)


def render_changes(project_name: str, round_: dict, old: dict | None, new: dict) -> str:
    """Compare one revision with the one before it as a Discord diff block."""
    title = f"## {label(project_name)} — {label(round_['label'])} · revision {new['version']}"
    saved_at = int(datetime.fromisoformat(new["updated_at"]).timestamp())
    lines = [title, f"Saved by <@{new['author_id']}> <t:{saved_at}:f>"]
    if old is None:
        lines.append("First submission, so there is nothing earlier to compare.")
    body = []
    for key, name in FIELDS:
        before = old[key] if old else ""
        after = new[key]
        if key == "status":
            body.append(
                f"Status: {before} → {after}" if old and before != after else f"Status: {after}"
            )
            continue
        if old and before == after:
            body.append(f"{name}: unchanged")
            continue
        body.append(f"{name}:")
        for line in difflib.ndiff(before.splitlines(), after.splitlines()):
            if not line.startswith("? "):
                body.append(code(line))
    lines.append("```diff\n" + "\n".join(body) + "\n```")
    return "\n".join(lines)


def describe_trend(statuses: list[str | None]) -> list[str]:
    """Plain rules only: no guessing. None means the project missed that round."""
    flags = []
    seen = [SEVERITY[value] for value in statuses if value is not None]
    if len(seen) >= 2:
        steps = list(zip(seen, seen[1:]))
        if seen[-1] > seen[0] and all(b >= a for a, b in steps):
            flags.append("worsening")
        elif seen[-1] < seen[0] and all(b <= a for a, b in steps):
            flags.append("improving")
    blocked = 0
    for value in reversed(statuses):
        if value != "Blocked":
            break
        blocked += 1
    if blocked >= 2:
        flags.append(f"blocked {blocked} rounds")
    missed = statuses.count(None)
    if missed >= 2:
        flags.append(f"{missed} missed")
    return flags


def trend_needs_attention(flags: list[str]) -> bool:
    return any(flag != "improving" for flag in flags)


def render_ticket(ticket: dict, project: dict, notes: list[dict]) -> str:
    assignee = f"<@{ticket['assignee_id']}>" if ticket["assignee_id"] else "Unassigned"
    lines = [
        f"## Support #{ticket['id']} — {label(project['name'])}",
        f"**{ticket['state'].title()}** · Contact: {assignee}",
        safe(ticket["description"]),
    ]
    if notes:
        lines.append("\n**Follow-up history**")
        for note in notes:
            if note["action"] == "nudge":
                lines.append(f"- {note['created_at']} · Reminder sent to {note['note']}")
                continue
            lines.append(
                f"- {note['created_at']} · <@{note['author_id']}> · {note['action']}: "
                f"{safe(note['note'])}"
            )
    return "\n".join(lines)


def render_summary(
    round_: dict,
    projects: list[dict],
    checkins: list[dict],
    tickets: list[dict],
    trends: list[tuple[str, list[str | None]]] | None = None,
    kudos: dict[int, int] | None = None,
) -> str:
    by_project = {row["project_id"]: row for row in checkins}
    unresolved = [ticket for ticket in tickets if ticket["state"] != "resolved"]
    supported = {ticket["project_id"] for ticket in unresolved}
    missing = [p for p in projects if p["project_id"] not in by_project]
    attention = [
        p
        for p in projects
        if p["project_id"] in supported
        or (
            (c := by_project.get(p["project_id"]))
            and (c["status"] != "On track" or c["blockers"] or c["assistance"])
        )
    ]
    lines = [
        f"# SDC weekly summary — {label(round_['label'])}",
        f"Round #{round_['id']} · Deadline: {round_['due_at']}",
        f"Submissions: **{len(checkins)}/{len(projects)}** · "
        f"Late: {sum(bool(c['late']) for c in checkins)}",
        "\n## Missing updates",
        ", ".join(label(p["name"]) for p in missing) or "None",
        "\n## Projects needing attention",
        ", ".join(label(p["name"]) for p in attention) or "None",
    ]
    if trends:
        rounds = max(len(statuses) for _, statuses in trends)
        lines.append(f"\n## Trends (last {rounds} rounds)")
        for name, statuses in trends:
            flags = describe_trend(statuses)
            marker = "⚠️ " if trend_needs_attention(flags) else ""
            path = " → ".join(value or "—" for value in statuses)
            note = f" ({', '.join(flags)})" if flags else ""
            lines.append(f"{marker}{label(name)}: {path}{note}")
    if kudos and any(kudos.values()):
        lines.append("\n## Kudos this round")
        lines.append(
            " · ".join(
                f"{label(p['name'])} ({kudos[p['project_id']]})"
                for p in projects
                if kudos.get(p["project_id"])
            )
        )
    lines.append("\n## Project updates")
    for project in projects:
        contact = f"<@{project['contact_id']}>" if project["contact_id"] else "Unassigned"
        lines.extend([f"\n### {label(project['name'])}", f"Board contact: {contact}"])
        if project["milestone"]:
            lines.append(f"Registered milestone: {safe(project['milestone'])}")
        if checkin := by_project.get(project["project_id"]):
            lines.extend(
                [
                    f"**{checkin['status']}**" + (" · Late" if checkin["late"] else ""),
                    f"Progress: {safe(checkin['progress'])}",
                    f"Next steps / milestone: {safe(checkin['next_steps'])}",
                    f"Blockers: {safe(checkin['blockers']) or 'None reported'}",
                    f"Assistance: {safe(checkin['assistance']) or 'None requested'}",
                    f"Submitted by <@{checkin['author_id']}> · Revision {checkin['version']}",
                ]
            )
        else:
            lines.append("No update submitted.")
    names = {p["project_id"]: p["name"] for p in projects}
    lines.append("\n## Outstanding support requests")
    for ticket in unresolved:
        contact = f"<@{ticket['assignee_id']}>" if ticket["assignee_id"] else "Unassigned"
        lines.append(
            f"- #{ticket['id']} · {label(ticket.get('project_name', names.get(ticket['project_id'], 'Other project')))} · "
            f"{ticket['state']} · {contact}\n{safe(ticket['description'])}"
        )
    if not unresolved:
        lines.append("None")
    return "\n".join(lines)
