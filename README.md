# SDC Discord Check-in Bot

A local Discord bot for weekly project updates, board summaries, and support follow-up.
One teammate submits an update for the whole project. Other teammates can revise it;
the bot records who changed each revision. Teams and the board see updates and support
outcomes in their existing Discord channels.

The pilot uses manually opened and closed rounds. Weekly scheduling is available but
disabled until the board configures it. The dashboard, GitHub integration, demo features,
and automatic mentor matching are deferred.

## Local installation

Requires Python 3.14 and macOS or Linux. Run one bot process against one SQLite database.
Keep the process and computer awake and connected for notifications to work.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '.[dev]'
cp .env.example .env
```

Edit `.env` with your bot token and numeric Discord server ID:

| Variable | Purpose |
| --- | --- |
| `DISCORD_TOKEN` | Bot token from the Discord Developer Portal |
| `DISCORD_GUILD_ID` | The single server the bot serves |
| `DATABASE_PATH` | SQLite file; defaults to `data/sdc.sqlite3` |
| `LOG_LEVEL` | `INFO` by default; also accepts DEBUG/WARNING/ERROR/CRITICAL |

The token and database are ignored by Git. Keep the token local; never put it in a
slash command. Reset it in the Developer Portal if exposed. Running from the project
directory makes `.env` and relative database paths predictable.

```sh
python -m sdc_bot --check-config
python -m sdc_bot
```

`sdc-bot` is an equivalent installed entry point. Stop with Ctrl+C. Migrations apply
automatically at startup. A lock file prevents two processes from using the same database.
The delivery/scheduler worker checks for work every five seconds.

`requirements.lock` captures the tested Python 3.14 runtime and development dependencies.
For a repeatable installation instead of resolving the version ranges again:

```sh
python -m pip install -r requirements.lock
python -m pip install --no-deps --no-build-isolation .
```

## Create and install the Discord application

1. Open the [Discord Developer Portal](https://discord.com/developers/applications), create
   an application, and create/reset its **Bot** token. Save that token in `.env`.
2. Keep **Server Members**, **Presence**, and **Message Content** privileged intents off.
   This bot uses interactions rather than reading members' conversations.
3. Under **Installation** or **OAuth2 URL Generator**, choose a server installation with
   the `bot` and `applications.commands` scopes. Request **View Channels**, **Send Messages**,
   **Read Message History**, and **Attach Files**. Attach Files is required in the board
   channel for complete Markdown summaries. Do not grant Administrator.
4. Install the bot into your private test server first. No public interaction endpoint,
   website, incoming port, or OAuth client secret is needed: it connects over the Gateway.
5. Enable Discord Developer Mode, copy the server ID, and set `DISCORD_GUILD_ID`.
6. Create a board role, a private board text channel, and a team role/text channel for each
   project. Give the bot the required permissions in those channels. Give the board role
   access to project channels and keep team roles out of the board channel. Server/channel
   permissions determine who can read posted content; the bot does not rewrite permissions.
7. Start the bot. It registers server-scoped slash commands for `DISCORD_GUILD_ID` at startup.
   Leave the Interactions Endpoint URL unset. If commands do not appear, check the server ID,
   installation scopes, and Discord's **Use Application Commands** permission.

Project-role and fallback board-role pings work when those roles are mentionable. The bot
does not require Mention Everyone. Contact user mentions work without that permission.
User-provided text cannot trigger role, user, or everyone pings, and link previews are suppressed.

## Board setup and manual pilot

A server manager runs:

```text
/sdc setup board_role:@SDC-Board board_channel:#board-checkins timezone:America/Chicago
/project add name:Alpha channel:#alpha team_role:@Alpha contact:@BoardContact milestone:Prototype
/project add name:Beta channel:#beta team_role:@Beta
/project list
```

Choose existing Discord roles; the bot does not maintain a separate member roster.
Setup requires **Manage Server** at runtime. Board commands require either the configured
board role or Manage Server. Project submissions, lists, buttons, and forms check the
invoking member's current roles, including when a form is submitted after a role change.
Commands may appear to unauthorized users in Discord, but their actions are rejected.

Open a round using a future deadline:

```text
/round open label:Week 1 due_at:2026-10-30 17:00
```

Naive dates use the configured timezone; explicit offsets such as
`2026-10-30T17:00:00-05:00` are also accepted. Nonexistent or ambiguous local DST times
are rejected unless an explicit offset disambiguates them.

Each active project's channel receives a **Submit or edit update** button. A member
chooses On track, At risk, or Blocked, then completes the form. Alternatively:

```text
/checkin submit project:Alpha status:On track
```

Project fields use autocomplete; their stored numeric IDs also work. Progress and next
steps are required, including an explicit "No progress this week" when appropriate.
Leave blockers/assistance blank when none. Each field accepts up to 1,500 characters.
Answers are shared with the project channel and the board. Concurrent edits prompt the
second editor to reopen the form instead of overwriting a teammate's newer revision.

There is one current submission per project/round. Revisions edit the existing channel
messages, retain all previous revisions in SQLite, and record the editor. The current
revision is marked late if saved after the deadline. Manual rounds remain editable until
closed, even after the deadline.

```text
/round status
/round remind
/summary preview round_id:1
/round close
```

Only missing projects receive reminders. Automatic reminders run 24 hours before the
deadline; rounds actually opened with less than 24 hours remaining skip them. Manual
`/round remind` works while the round is open, including after the deadline.

Closing freezes submissions and the summary, then queues the digest to the private board
channel. The digest includes submitted text, contacts, participation/late counts, missing
updates, explicit attention flags, and outstanding support requests. Long digests are split
across messages with a complete Markdown attachment. No AI or progress-percentage inference
is used. A later support resolution does not rewrite a closed round's historical snapshot.

`/summary publish round_id:1` publishes or updates a summary, including after a delivery
failure. Publishing an open round is a live preview; closing replaces it with the snapshot.

## Projects and support follow-up

```text
/project edit project:Alpha contact:@NewContact milestone:Beta release
/project edit project:Alpha clear_contact:True
/project archive project:Alpha
/project edit project:Alpha active:True
/support request project:Alpha description:Need help reviewing the deployment plan
/support list project:Alpha
/support acknowledge ticket:1 note:I will meet the team on Thursday
/support assign ticket:1 contact:@OtherBoardMember note:Deployment expertise
/support resolve ticket:1 note:Review completed; resources at https://example.com/resources
/board overview
```

At risk/Blocked updates, or nonempty blocker/assistance fields, create a support ticket.
The board card mentions the project's assigned contact, or falls back to the board role.
Revisions update that ticket without duplicating it or automatically resolving it. A resolved
ticket remains resolved even if its check-in is revised; use `/support request` for new help.
The **Acknowledge** and **Resolve** buttons perform the same permission-checked actions.
Acknowledge assigns the ticket to the actor; resolution requires an outcome/resource note.
Both team and board cards show the follow-up history.

Board contacts selected through Discord must have the board role or Manage Server permission.
Existing tickets keep their assigned owner when a project's default contact changes; use
`/support assign` to transfer them. `/support list` without a project is board-only.

**Stale-ticket nudges** are off by default. `/support nudges days:3` re-pings a request in
the board channel when it has gone that many days without board activity: the assigned
contact (or the board role) for unacknowledged requests, and the owner for acknowledged
ones that have stalled. Acknowledging, assigning, or a previous nudge resets the clock;
team revisions do not. Each nudge carries Acknowledge/Resolve buttons and appears in the
ticket's follow-up history. Resolved requests are never nudged. `days:0` turns this off.

Archiving excludes a project from future rounds. An already-open round keeps its original
participants, names, destination channels, and milestones. Current team roles govern who
can submit, and current project contacts appear in the digest until it is frozen. Use `-`
to clear a milestone in `/project edit`.

## History, changes, trends, and kudos

```text
/checkin history project:Alpha
/checkin history project:Alpha rounds:12 full:True
/checkin changes project:Alpha
/checkin changes project:Alpha revision:2 round_id:5
```

`/checkin history` lists a project's recent rounds, newest first, including rounds it
missed. Entries are shortened unless `full:True`. `/checkin changes` compares a revision
with the one before it (default: the latest revision of the project's most recent update).
Both are private replies, available to the project's team and the board.

Revised update cards show which fields changed. Because message edits do not notify anyone,
a revision that changes the status (for example Blocked → On track) also posts a short
alert to the board channel.

From the second round on, digests include a **Trends** section covering up to the last four
rounds. It flags, by fixed rules only: worsening (status got worse and never improved in the
window), blocked two or more rounds in a row, and two or more missed updates. Improving
projects are labelled but not flagged. In a live preview, a project that has not submitted
yet is not counted as missed.

Update cards have a **🎉 Kudos** button. Board members can give each update kudos once,
with an optional note; it is posted in the project channel. Digests list kudos per project,
and history shows the count.

## Optional weekly schedule

After testing the manual workflow:

```text
/schedule configure open_day:0 open_time:09:00 close_day:4 close_time:17:00
/schedule disable
```

Days are 0=Monday through 6=Sunday. Times use the configured server timezone and HH:MM.
For recurring rounds, choose times at or after 03:00 to avoid DST transition hours.
Closing can fall in the following week. Opening and closing cannot be identical.

Configuration begins with the next scheduled opening; it does not immediately open a round
for an earlier opening. After downtime, the bot can open the current active window, closes
an existing overdue automated round once, and skips fully missed historical weeks and
obsolete reminders. It never interrupts a manual round. Manually closing an automated
round early does not cause it to reopen during the same window.

Skip holiday weeks without disabling the schedule:

```text
/schedule skip date:2026-11-26 reason:Thanksgiving break
/schedule skips
/schedule unskip date:2026-11-26
```

Any date skips the Monday–Sunday week containing it. That week's automatic round does not
open; each active project channel gets one short note instead, and the schedule resumes the
following week. Skipped weeks are never caught up later and do not count as missed in
trends. Skipping a week whose round already opened does not affect that round. Unskipping
during the week opens its round right away. Manual rounds still work in skipped weeks.
`/sdc status` shows the next opening and any skipped weeks before it.

Disabling stops future openings. An already-open automated round still closes at its
recorded deadline and publishes its summary. An already-open manual round always requires
`/round close`. Reconfiguring setup preserves an enabled schedule; its local times use
the new timezone from the next opening. Deadlines of existing rounds do not move.

## Delivery recovery and operations

```text
/sdc status
/sdc retry delivery_id:12
/sdc retry delivery_id:12 channel:#replacement-channel
```

Commands save changes and queue messages; successful confirmation means the data is saved,
not that Discord has already accepted every message. `/sdc status` checks channel access and
lists failed, retrying, and ambiguous deliveries. Failures also appear in terminal logs.

Message IDs and delivery versions allow normal retries/revisions to reuse existing messages.
Deleted messages are replaced when publishing again. Definite transient failures retry with
backoff, up to five attempts. Permission failures need repair before retrying.

A timeout while creating a message, or a process exit during delivery, is **ambiguous**:
Discord may have accepted it. Such sends are not automatically repeated. Check the channel
before `/sdc retry`; an explicit retry can duplicate a message whose ID was never recorded.
This is not an exactly-once delivery guarantee. Completed sends are not repeated on restart.

If a destination channel was deleted, select a replacement in `/sdc retry`. Board content
requires another private channel accessible to the board. Also update `/sdc setup` or
`/project edit` for future messages/rounds. Existing rounds retain their channel snapshots;
retry any further failed sends from that round to the replacement as needed.

Back up the database with the bot stopped:

```sh
# Stop the bot with Ctrl+C before copying. Use your configured DATABASE_PATH.
mkdir -p backups
cp data/sdc.sqlite3 backups/sdc.sqlite3
```

Keep backups private because they contain team responses and support notes. Restore the
SQLite file while the bot is stopped, then restart. Leave the migrations bundled with the
application. Do not copy only the main SQLite file while the process is running in WAL mode.

## Tests and private-server acceptance

```sh
python -m pytest -q
ruff check sdc_bot tests
ruff format --check sdc_bot tests
```

Tests require no Discord credentials. They cover authorization, concurrency, late and closed
rounds, support lifecycle, scheduling/DST, SQLite restarts, delivery failures, persistent
buttons, actual Discord method signatures, long responses, and a two-project pilot simulation.

For the live acceptance test:

1. Install in a private test server, configure a board channel, and register Alpha/Beta with
   separate roles/channels. Use a normal team account to verify permissions, not an admin.
2. Open a round with a future deadline. Submit an Alpha update with a blocker using the prompt;
   leave Beta missing. Confirm Alpha's channel update and its board support alert appear.
3. Acknowledge and resolve that ticket as a board member. Confirm Alpha sees both changes.
4. Revise Alpha's update and verify its message is edited and no second support ticket appears.
5. Use `/round remind` and verify only Beta is reminded.
6. Restart the process. Use the original prompt/support controls and confirm they still work;
   already completed messages should not be reposted.
7. Close the round. Confirm the board digest shows 1/2 submissions, Beta missing, Alpha's
   reported blocker/status, and no unresolved support after resolution. Confirm Alpha's old
   form can no longer submit.
8. Temporarily remove Send Messages permission, request help, and inspect `/sdc status`.
   Restore permission, retry the failed delivery, and confirm recovery.

The automated simulation passes locally; a real Discord smoke test must be run with your
bot token and private server configuration.

## Structure and future dashboard

- `models.py`, `services.py`: permission-checked workflows and domain data, without Discord imports.
- `repository.py`, `migrations/`: SQLite persistence and serial transactions.
- `scheduler.py`, `delivery.py`: timezone scheduling and durable message delivery.
- `discord_app.py`, `discord_transport.py`: Discord commands, forms, buttons, and HTTP calls.

A later dashboard can reuse the service layer behind authenticated HTTP endpoints. Member
rosters will come from Discord roles, and GitHub integration can be added independently.
There is no web server, website authentication, or GitHub token requirement in this release.

During development, run `python -m sdc_bot` from the project directory to use your current
source. Reinstall the package after changes if you use the installed `sdc-bot` shortcut.
