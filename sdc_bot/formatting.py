"""Deterministic Markdown rendering with inert user-supplied mentions."""

import re


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


def render_checkin(project: dict, round_: dict, checkin: dict) -> str:
    late = " · Late" if checkin["late"] else ""
    return (
        f"## {label(project['name'])} — {label(round_['label'])}\n"
        f"**{checkin['status']}**{late} · Revision {checkin['version']}\n"
        f"Updated by <@{checkin['author_id']}>\n\n"
        f"**Progress**\n{safe(checkin['progress'])}\n\n"
        f"**Next steps / milestone**\n{safe(checkin['next_steps'])}\n\n"
        f"**Blockers**\n{safe(checkin['blockers']) or 'None reported'}\n\n"
        f"**Assistance requested**\n{safe(checkin['assistance']) or 'None requested'}"
    )


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
            lines.append(
                f"- {note['created_at']} · <@{note['author_id']}> · {note['action']}: "
                f"{safe(note['note'])}"
            )
    return "\n".join(lines)


def render_summary(
    round_: dict, projects: list[dict], checkins: list[dict], tickets: list[dict]
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
        "\n## Project updates",
    ]
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
