# SDC Check-in Bot Board Manual

## Table of contents

- [Welcome, Board Members](#welcome-board-members)
- [Permissions at a Glance](#permissions-at-a-glance)
- [Board Command Reference](#board-command-reference)
  - [Set up and maintain the bot](#set-up-and-maintain-the-bot)
  - [Register and update projects](#register-and-update-projects)
  - [Run a check-in round](#run-a-check-in-round)
  - [Follow up on support](#follow-up-on-support)
  - [Share summaries and kudos](#share-summaries-and-kudos)
  - [Schedule rounds and holidays](#schedule-rounds-and-holidays)
- [Managing the Bot Day to Day](#managing-the-bot-day-to-day)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Glossary](#glossary)
- [Open Questions](#open-questions)

## Welcome, Board Members

You can open and close check-in rounds, follow up on support requests, and review how projects are doing. The board’s private channel is your workspace for these actions. In this guide, it’s called **#sdc-board**. The server manager also operates the bot and handles permission or delivery problems.

Use the [Member Manual](member-manual.md) for the shared commands and the basics of using Discord. When you write a support note or give kudos, assume everyone who can see the team channel will see your text.

## Permissions at a Glance

- **Everyone** commands work in the club server. For check-ins and support, open the team channel first. Project lists work anywhere in the server that Discord allows you to use the app.
- **Board** slash commands require the configured Board role and must be run directly in the configured private board channel. The **🎉 Kudos** button works for the Board role directly on a team update. For initial setup or a board-channel move, the server manager runs `/sdc setup` in the private channel they select. Setup requires **Manage Server**. The server manager needs the Board role for the other board commands.
- Discord controls channel visibility. Give the Board role and the bot access to the private board channel. Server owners and Discord administrators may also have access through their server permissions. The bot still checks the Board role for board actions.
- Direct replies are private. A reply that says a message was **queued** confirms that the bot saved the action and will try to post the message.

| Slash command | Who can use it | What it does |
|---|---|---|
| `/project list` | Everyone | Finds registered projects, channels, contacts, and milestones. |
| `/checkin submit` | Everyone in the team channel for the open round | Opens a form to submit or edit the team update. |
| `/checkin history` | Everyone in a registered team channel | Shows the team’s recent updates. |
| `/checkin changes` | Everyone in a registered team channel | Compares two saved versions of an update. |
| `/support request` | Everyone in a registered team channel | Opens a help request for that team. |
| `/support list` | Everyone in a registered team channel | Lists that team’s support requests. |
| `/sdc setup` | Board setup by the server manager | Sets the Board role, board channel, and timezone. |
| `/sdc status` | Board | Checks channel access, scheduling, and delivery failures. |
| `/sdc retry` | Board | Retries a failed or uncertain post. |
| `/project add` | Board | Links a project to a team channel. |
| `/project edit` | Board | Changes a project’s channel, name, contact, milestone, or active status. |
| `/project archive` | Board | Excludes a project from future rounds and keeps its history. |
| `/round open` | Board | Opens a manual round and queues team prompts. |
| `/round close` | Board | Freezes submissions and queues the final summary. |
| `/round remind` | Board | Queues reminders for teams with no submission. |
| `/round status` | Board | Shows the board overview, including participation for an open round. |
| `/support acknowledge` | Board | Acknowledges a request and assigns it to you. |
| `/support assign` | Board | Assigns a request to a board contact. |
| `/support resolve` | Board | Closes a request and records what happened. |
| `/support nudges` | Board | Sets or disables reminders for requests awaiting follow-up. |
| `/summary preview` | Board | Gives you a private copy of a round summary. |
| `/summary publish` | Board | Posts or updates a round summary in the board channel. |
| `/schedule configure` | Board | Turns on weekly round openings and closings. |
| `/schedule disable` | Board | Stops future automatic openings. |
| `/schedule skip` | Board | Skips a week’s automatic round. |
| `/schedule unskip` | Board | Restores a skipped week to the schedule. |
| `/schedule skips` | Board | Lists current and upcoming skipped weeks. |
| `/board overview` | Board | Shows missing submissions, unresolved requests, and projects without contacts. |
| `/board support` | Board | Lists all support requests across teams. |
| `/board kudos` | Board | Posts recognition for an update in the team channel. |

| Button, dropdown, or form | Who can use it | What it does |
|---|---|---|
| **Submit or edit update** | Everyone in the team channel for the open round | Opens a private status dropdown on a round prompt. |
| **Choose your project’s status** | Everyone in the team channel for the open round | Opens the check-in form with the chosen status. |
| **Project check-in** | The person who opened it in the team channel | Saves a revision of the team update. |
| **Acknowledge** | Board | Acknowledges and takes ownership of a request from a board card or nudge. |
| **Resolve** | Board | Opens the resolution form from a board card or nudge. |
| **Resolve support #…** | Board | Saves a required resolution note and closes the request. |
| **🎉 Kudos** | Board in the update’s team channel | Opens the kudos form from a team update. |
| **Give kudos** | Board in the update’s team channel | Posts kudos with an optional note in the team channel. |

## Board Command Reference

Run the following slash commands in **#sdc-board**. When an example uses `project:Team 7`, start typing **Team 7** in Discord’s project field and choose the matching suggestion. You can also enter the project’s number. For a round, ticket, or delivery number, enter the digits without the `#`.

### Set up and maintain the bot

#### `/sdc setup`

The server manager uses this for the first setup or when the board channel, role, or timezone changes.

1. Create a private text channel, such as **#sdc-board**. Deny **View Channel** for **@everyone** and allow it for the Board role and the bot. Check that the bot can send messages, read history, and attach files there.
2. Open that channel. Select `/sdc setup`, fill in the options, and send it.
3. Give the server manager the Board role if they also need to run board commands. Run `/sdc status` to check access and scheduling.

- `board_role` is required. Select the existing role that grants board access.
- `board_channel` is required. Select the private channel you’re currently in.
- `timezone` is optional. Use a timezone such as `America/Chicago` or `UTC`. The default is `America/Chicago`.

**Example**  
`/sdc setup board_role:@SDC-Board board_channel:#sdc-board timezone:America/Chicago`

**Private reply**

> Setup saved. Register projects with /project add. Use /sdc status to check scheduling and channel access.

**Member impact and warning.** Setup doesn’t post to team channels. A different Board role changes who can use board commands. A different board channel becomes the destination for future board posts. Before moving, check the new channel’s access and review who can still read old posts in the original channel. Changing the timezone affects future scheduled times. Open rounds keep their saved deadlines.

**Common mistake.** Run setup inside the selected private channel with **Manage Server**. The Board role alone gives access to other board commands.

[SCREENSHOT: The board channel’s View Channel settings and the three fields in sdc setup]

#### `/sdc status`

Check the schedule, channel permissions, and messages the bot had trouble posting.

1. Send `/sdc status`.
2. Review the timezone, schedule, and support-nudge settings.
3. If the bot reports a channel or delivery problem, copy its exact text and delivery number for the server manager.

There are no options.

**Example**  
`/sdc status`

**Example private reply excerpt**

```text
Timezone: America/Chicago
Schedule: Disabled (manual pilot)
Stale-ticket nudges: off
The local process must stay running for delivery.
No failed or uncertain deliveries.
```

**Member impact.** This command only reports what the bot found.

**Common mistake.** “No failed or uncertain deliveries.” can appear alongside a channel permission problem. Read the channel lines as well.

#### `/sdc retry`

Retry a message after fixing a delivery problem.

1. Run `/sdc status` and find the failed, retrying, or uncertain delivery.
2. Fix the channel problem. If the delivery is uncertain, check Discord for the message before retrying.
3. Send `/sdc retry` with the delivery number. Select a replacement channel only when the destination needs to change.
4. Check the destination and rerun `/sdc status`.

- `delivery_id` is required. Use the number shown in `/sdc status`.
- `channel` is optional. Leave it blank to retry in the saved destination. Board posts can go only to the configured board channel. For a failed round prompt, register the replacement as the project’s team channel before redirecting the prompt.

**Example**  
`/sdc retry delivery_id:12`

**Private reply**

> Delivery queued for retry. Check /sdc status for the result.

**Member impact and warning.** Retrying an uncertain send can create a duplicate. A message redirected to a team channel becomes visible to everyone with access there. Check both the type of message and the channel before sending. Retrying a prompt in a replacement team channel also moves where the team checks in for that round.

**Common mistake.** The confirmation means the retry is queued. It can still fail if the bot lacks permission.

### Register and update projects

#### `/project add`

Link a project to its own Discord text channel.

1. Create or find the team’s text channel. Give members and the bot access.
2. Send `/project add` with the project’s name and channel. Add a board contact or a milestone if you have one.
3. Run `/project list` to confirm the link.

- `name` is required. Use 1 to 80 characters on one line.
- `channel` is required. Select the team’s text channel. Each project needs its own channel, separate from the board channel.
- `contact` is optional. Choose a person with the Board role to receive that team’s support alerts.
- `milestone` is optional. Enter the current goal in up to 1,000 characters.

**Example**  
`/project add name:Team 7 channel:#team-7 contact:@Maya milestone:Test the sign-in flow`

**Example private reply**

> Registered project #7: Team 7.

**Member impact.** The project appears in the project list and joins the next round while active. Its support and history commands use the channel you selected.

**Common mistake.** Register the team once. Use `/project edit` to change an existing project.

#### `/project edit`

Update an existing project’s details or bring an archived team back into future rounds.

1. Select `/project edit` and choose the project.
2. Fill in the fields you want to change.
3. Send the command and confirm the change with `/project list`.

- `project` is required. Select the registered project.
- `name` is optional. Use a name of 1 to 80 characters on one line.
- `channel` is optional. Select a replacement team text channel.
- `contact` is optional. Select a person with the Board role.
- `clear_contact` is optional. Choose `True` to remove the default contact.
- `milestone` is optional. Enter up to 1,000 characters. Enter `-` to clear it.
- `active` is optional. Choose `True` to include the project in future rounds or `False` to archive it.

**Example**  
`/project edit project:Team 7 milestone:Recruit three usability testers`

**Private reply**

> Project updated. Channel/name/milestone changes apply to future rounds; the current round retains its registered project snapshot.

**Member impact and warning.** A channel change moves the team’s support and history commands to the new registered channel. The open round’s prompt and check-in workflow keep their round channel unless a failed prompt is redirected. New requests use the new default contact. Existing requests keep their assigned person. Tell the team where to work if you move channels.

**Common mistake.** Choose either a new contact or `clear_contact:True` for a given edit.

#### `/project archive`

Remove a finished or inactive team from future rounds while keeping its records.

1. Select `/project archive` and choose the project.
2. Double-check the name and send the command.
3. Use `/project list include_archived:True` to confirm the status.

- `project` is required. Select the project to archive.

**Example**  
`/project archive project:Team 7`

**Private reply**

> Archived. Existing rounds and history are retained. Use /project edit active:True to reactivate.

**Member impact and warning.** The team stops receiving future round prompts. It can still participate in a round it was already part of, and members can still read its history.

**Common mistake.** Archiving takes effect for future rounds. To reactivate the team, send `/project edit project:Team 7 active:True`.

### Run a check-in round

#### `/round open`

Start a manual round when your teams are ready to submit.

1. Make sure at least one project is active and check `/round status` for an existing round.
2. Select `/round open` and enter a label and future deadline.
3. Send it and note the round number. Confirm that a prompt arrives in a team channel.

- `label` is required. Use 1 to 100 characters, such as `Week 4`.
- `due_at` is required. Enter a date and time as `YYYY-MM-DD HH:MM` in the bot’s configured timezone. You can include an explicit offset, as in `2026-11-20T17:00:00-06:00`.

**Example**  
`/round open label:Week 4 due_at:2026-11-20 17:00`

**Example private reply with America/Chicago configured**

> Opened round #4. Prompts are queued; deadline 2026-11-20T23:00:00+00:00. Close manually with /round close.

**Member impact and warning.** Each active team gets a prompt in its channel. An eligible round can send one automatic reminder around 24 hours before the deadline. A manual round stays editable past its deadline until you close it.

**Common mistake.** Use a future deadline and check the configured timezone with `/sdc status`. Discord shows the time in the team prompt in each reader’s local time.

[SCREENSHOT: The private round-open confirmation and the resulting prompt in a team channel]

#### `/round close`

End submissions and record the final summary.

1. Use `/round status` to check which teams have submitted.
2. Confirm the intended round and whether teams have had enough time.
3. Send `/round close` and look for the summary in the board channel.

There are no options.

**Example**  
`/round close`

**Example private reply**

> Round #4 closed. The frozen summary is queued for the board channel.

**Member impact and warning.** Closing immediately stops submissions and edits for that round. The summary records what was true at closing. There is no reopen command.

**Common mistake.** `/round close` always closes the one currently open round. It takes no round number.

#### `/round remind`

Send a reminder to teams that still owe an update.

1. Run `/round status` and review missing submissions.
2. Send `/round remind` while the round is open.
3. Check the reply for how many reminders were queued.

There are no options.

**Example**  
`/round remind`

**Example private reply**

> Queued reminders for 2 missing project(s).

**Member impact and warning.** Missing teams get a message in their channels. The bot can send another reminder each time you use the command, including after the deadline of an open manual round. Check recent posts before repeating it.

**Common mistake.** A team that submits before the queued reminder goes out can be skipped, so the number of posts may be smaller than the queue count.

#### `/round status`

Check participation and follow-up for the current round.

1. Send `/round status`.
2. Read the summary section for the round number, missing projects, and teams needing attention.

There are no options.

**Example**  
`/round status`

**Example private reply excerpt**

```text
SDC board overview
Unassigned project contacts: None
Open support requests: 0
SDC weekly summary — Week 4
Round #4 · Deadline: 2026-11-20T23:00:00+00:00
Submissions: 16/18 · Late: 0
```

**Member impact.** This command displays a private overview.

**Common mistake.** “No open round.” describes the current state. To see a past summary, use `/summary preview` with its round number.

#### `/board overview`

Check unresolved support, missing board contacts, and the open round in one place.

1. Send `/board overview`.
2. Review unassigned project contacts and open requests. If a round is open, scroll to its summary.

There are no options.

**Example**  
`/board overview`

**Example private reply excerpt**

```text
SDC board overview
Unassigned project contacts: Team 9
Open support requests: 1
- #12 · project #7 · open · Could someone review our sign-in flow before Friday’s demo?
No open round.
```

**Member impact.** This command displays a private overview.

**Common mistake.** An acknowledged request remains in the open request count until it is resolved.

### Follow up on support

#### `/board support`

Find a ticket number or review support requests across all projects.

1. Send `/board support`.
2. Find the request by its number, project number, or description. Use the request number when following up.

There are no options.

**Example**  
`/board support`

**Example private reply excerpt**

```text
#12 · project #7 · open · @Maya
Could someone review our sign-in flow before Friday’s demo?
```

**Member impact.** This command only shows you the list.

**Common mistake.** This list includes resolved requests. For unresolved requests and a participation summary, use `/board overview`.

#### `/support acknowledge` and the **Acknowledge** button

Let the team know you’re taking ownership of its request.

1. Open the board support card and confirm the ticket number and current contact.
2. Click **Acknowledge** for a quick handoff, or send `/support acknowledge` to include a note.
3. Check the confirmation and the updated card.

- `ticket` is required for the command. Enter the support request number.
- `note` is optional for the command. Enter up to 1,500 characters. The button takes no options.

**Command example**  
`/support acknowledge ticket:12 note:I can review the sign-in flow Thursday.`

**Private reply**

> Acknowledged and assigned to you. Updates are queued for the team and board.

**Button example**  
Click **Acknowledge** on **Support #12**.

> Acknowledged and assigned to you. The team will see the update.

**Member impact and warning.** Both cards show you as the contact and display the follow-up. Acknowledging can take ownership from the person currently assigned. Check with them first if they’re already handling it.

**Common mistake.** Acknowledging a request marks it as acknowledged. Use the resolution action when the work is finished.

#### `/support assign`

Give a request to another board member who can help.

1. Confirm who will take the request.
2. Select `/support assign` and enter the ticket and new contact. Add a short handoff note if useful.
3. Send it and check the card for the new contact.

- `ticket` is required. Enter the support request number.
- `contact` is required. Choose a person who has the configured Board role.
- `note` is optional. Enter up to 1,500 characters.

**Example**  
`/support assign ticket:12 contact:@Maya note:Maya can review the sign-in flow on Thursday.`

**Private reply**

> Assignment saved. Team and board updates are queued.

**Member impact and warning.** The team sees the new contact and your note. Include handoff details the team can read.

**Common mistake.** Assigning changes the contact. The request keeps its existing status.

#### `/support resolve` and the **Resolve** button

Close a request after recording the result and any resources the team needs.

1. Find the correct ticket and confirm the outcome.
2. Use `/support resolve`, or click **Resolve** on the board card to open **Resolve support #…**.
3. Enter a resolution note or resource link and send the command or submit the form.

- `ticket` is required for the command. The button already knows the ticket number.
- `note` is required for the command. The equivalent form field is **Resolution / resource links**. Enter up to 1,500 characters.

**Command example**  
`/support resolve ticket:12 note:Reviewed the sign-in flow. The team will add clearer error messages.`

**Button example**  
Click **Resolve** on **Support #12**, enter the same note, and submit the form.

**Private reply for either action**

> Resolved. The team and board messages will be updated.

**Member impact and warning.** The team sees the outcome and links you include. Resolution closes the ticket permanently. Ask the team to open a new request if more help is needed later.

**Common mistake.** Include the outcome even when you already discussed it in chat. A blank resolution note is rejected.

[SCREENSHOT: A board support card with Acknowledge and Resolve, followed by the resolution form]

#### `/support nudges`

Ask the bot to follow up in the board channel when requests sit idle.

1. Choose the number of days a request can wait between follow-ups.
2. Select `/support nudges`, enter that number, and send it.
3. Check the setting in `/sdc status`.

- `days` is required. Enter 1 to 60 days. Enter `0` to turn nudges off.

**Example**  
`/support nudges days:3`

**Private reply**

> Stale requests will be re-pinged after 3 day(s) without board follow-up.

For `/support nudges days:0`, the reply is “Stale-request nudges are off.”

**Member impact and warning.** The nudge goes to the board channel and can mention the assigned person or the Board role. Its entry also appears in the team card’s follow-up history. When you enable nudges, older unresolved requests may already be due.

**Common mistake.** The wait is measured from the latest board follow-up or nudge. A team editing its check-in does not reset the wait.

### Share summaries and kudos

#### `/summary preview`

Read a round summary privately before sharing it with the board.

1. Find the round number in `/round status`, a close confirmation, or a previous summary.
2. Select `/summary preview`, enter the number, and send it.
3. Open the attached Markdown file in the reply.

- `round_id` is required. Enter the round number.

**Example**  
`/summary preview round_id:4`

**Private reply**

> Details attached.

The reply includes `sdc-round-4-preview.md`. The summary shows submissions, late updates, missing projects, projects needing attention, and outstanding support. It can also show recent trends and kudos.

**Member impact.** The preview goes only to you.

**Common mistake.** A preview of an open round changes as teams submit. A closed round shows the saved summary from closing time.

#### `/summary publish`

Post a round summary in the board channel or refresh the posted copy.

1. Preview the round and confirm the number.
2. Send `/summary publish` for that round.
3. Check the board channel for the summary and its Markdown attachment.

- `round_id` is required. Enter the round number.

**Example**  
`/summary publish round_id:4`

**Private reply**

> Summary queued. Existing summary messages will be updated where possible.

**Member impact and warning.** The summary posts to the board channel and includes the teams’ full updates and outstanding request details. Review who can access the channel before sharing any copy elsewhere. Publishing an open round captures its current state. Closing it later queues the final version.

**Common mistake.** Publishing does not close the round. Use the separate close action when submissions should end.

#### `/board kudos` and the **🎉 Kudos** button

Recognize a team’s work on a saved update.

1. Find the update in its team channel and click **🎉 Kudos**.
2. In the **Give kudos** form, add an optional note of up to 300 characters.
3. Submit the form. The bot will post kudos in the team channel.

For example, click **🎉 Kudos** on Team 7’s Week 4 update and enter “Great work testing the sign-in flow.”

To give kudos from the board channel, select `/board kudos` and choose the project. Enter a round number for an older update, add an optional note, and send it.

- `project` is required. Select the team you want to recognize.
- `round_id` is optional. Enter the round number to select a specific update.
- `note` is optional. Use up to 300 characters.

**Command example**  
`/board kudos project:Team 7 round_id:4 note:Great work testing the sign-in flow.`

**Private reply for either action**

> Kudos queued. It will appear in the project channel.

**Member impact and warning.** Your name and note appear in the team channel. Each board member can give kudos once per update, including when the team has saved several revisions.

**Common mistake.** The button recognizes the update on that card. Check the round label before clicking. Both ways share the same one-per-update limit.

[SCREENSHOT: The 🎉 Kudos button on a team update and its optional note field]

### Schedule rounds and holidays

A new setup starts with manual rounds and support nudges off. This guide uses the manual workflow as the starting point. Scheduling and nudges can be enabled independently.

#### `/schedule configure`

Set a recurring round when the board has agreed on a weekly schedule.

1. Check the bot’s timezone with `/sdc status`.
2. Select `/schedule configure` and enter opening and closing days and times.
3. Send it and use `/sdc status` to check the next opening.

- `open_day` and `close_day` are required. Use `0` for Monday, `1` for Tuesday, `2` for Wednesday, `3` for Thursday, `4` for Friday, `5` for Saturday, and `6` for Sunday.
- `open_time` and `close_time` are required. Use 24-hour `HH:MM` times at or after `03:00` in the configured timezone. The opening and closing must differ. A round can end the following week.

**Example**  
`/schedule configure open_day:0 open_time:09:00 close_day:4 close_time:17:00`

**Private reply**

> Weekly scheduling enabled in the server's configured timezone. The first round opens at the next scheduled opening; no historical rounds are created.

**Member impact and warning.** Teams get recurring prompts, and submissions close automatically at the scheduled deadline. A manual round already open takes priority. The schedule can open a round only while that week’s window is still active.

**Common mistake.** Setting the schedule after this week’s opening time starts the new schedule at the next opening. Use a manual round if you need to start immediately.

#### `/schedule disable`

Stop future automatic rounds.

1. Send `/schedule disable`.
2. Use `/sdc status` to confirm future scheduling is disabled.
3. Check `/round status` if a round is already open.

There are no options.

**Example**  
`/schedule disable`

**Private reply**

> Future weekly openings disabled. Existing automated rounds will still close at their deadline; manual rounds close with /round close.

**Member impact.** Future automatic prompts stop. A team with an open automated round can submit until the existing round closes at its deadline.

**Common mistake.** Disabling the schedule affects future openings. Close a current round explicitly if it needs to end now.

#### `/schedule skip`

Skip a planned weekly round for a holiday or break.

1. Find a date in the Monday–Sunday week you want to skip.
2. Select `/schedule skip`, enter the date, and add an optional reason.
3. Confirm the Monday shown in the reply and check `/schedule skips`.

- `date` is required. Use `YYYY-MM-DD`. Any date in the target week works.
- `reason` is optional. Use up to 200 characters.

**Example**  
`/schedule skip date:2026-11-26 reason:Thanksgiving break`

**Private reply**

> The week of Monday 2026-11-23 is marked to skip. The bot skips an eligible automatic opening and can post a notice in project channels. Manual rounds still work.

**Member impact and warning.** When the enabled schedule reaches a skipped opening, the bot can post a notice in active team channels. The reason is visible in that notice. A round already opened for the week keeps running.

**Common mistake.** The date selects a whole week. Use `/schedule unskip` first if you want to replace a skip reason.

#### `/schedule unskip`

Remove a previously recorded skip.

1. Run `/schedule skips` to confirm the week.
2. Select `/schedule unskip` and enter a date in that week.
3. Confirm the Monday in the reply. Check `/round status` if the opening time has already passed.

- `date` is required. Use `YYYY-MM-DD`. Any date in the skipped week works.

**Example**  
`/schedule unskip date:2026-11-26`

**Private reply**

> The week of Monday 2026-11-23 is back on the schedule. An eligible round can open automatically if its scheduled window is still active.

**Member impact and warning.** This can trigger a round prompt within the current scheduled window. The schedule must be enabled, an active project must exist, and no other round can be open. A round that already ran in that window will not open again. If teams already saw a skip notice, tell them the plan changed.

**Common mistake.** Restoring a week after its scheduled window ends cannot create that past round.

#### `/schedule skips`

Review which weeks are marked to skip.

1. Send `/schedule skips`.
2. Check the Mondays and reasons in the private reply.

There are no options.

**Example**  
`/schedule skips`

**Example private reply**

```text
Week of 2026-11-23: Thanksgiving break
```

**Member impact.** The list goes only to you.

**Common mistake.** Each displayed date is a Monday, even if a different date in that week was entered.

## Managing the Bot Day to Day

### Start a manual round

1. Open the board channel and check `/sdc status` for channel problems.
2. Use `/project list` to check active teams and contacts.
3. Open the round with a future deadline. Check a team channel for the prompt.

### Review support and participation

1. Open `/board overview` and identify missing submissions and unresolved requests.
2. Send a reminder if needed. Check the board support cards for requests that need an owner.
3. Acknowledge or assign requests. Close them with a clear note after following up.

### Finish the round

1. Check participation and preview the summary if you want to review it before closing.
2. Close the round and confirm the summary arrived in the board channel.
3. If a message is missing, check delivery status before retrying.

### Prepare for a break

1. Check whether scheduling is enabled and list skipped weeks.
2. Record any new holiday skips. Write reasons that are suitable for team channels.
3. If plans change, unskip the week and check whether a round opened.

## Troubleshooting

| What you see | What to check first |
|---|---|
| “This action requires the configured board role.” | Open your profile in the club server and check for the Board role. Ask the server manager to verify the configured role and your assignment. |
| “Use this action in the configured board channel.” | Open the configured board text channel and send the command there. Use the channel’s main message box. |
| “Setup requires Manage Server permission.” | Ask the server manager to run setup in the selected private channel. |
| “Run setup from the private channel you selected for the board.” | Open the exact channel you selected in the command and run it there. |
| “Choose a private board channel: deny View Channel for @everyone.” | Ask the server manager to deny **View Channel** for **@everyone** in the board channel and grant access to the Board role and bot. |
| “Grant the configured board role View Channel in the board channel.” | Verify that the configured role still exists and can see the channel. |
| “Allow View Channel in the board channel only for the board role and the bot.” | Review the channel’s explicit role and member permissions with the server manager. Remove other grants to view it. |
| “That channel is already in use by another project.” | Select a different channel. The current round can still use a channel after a project moves, so check whether the round is open. |
| “A round is already open. Close it before opening another.” | Check `/round status` to identify the open round. Close it when teams are ready. |
| “The deadline must be in the future.” | Check the date, time, and configured timezone. |
| “Use recurring times at or after 03:00 to avoid DST transitions.” | Use 24-hour times at or after 03:00 for both opening and closing. |
| “Choose a person with the configured board role as the contact.” | Pick a person who holds the Board role. |
| “Include a resolution note or resource link.” | Describe the outcome or add a link the team can use. |
| “This request is already resolved. Create a new request for new help.” | Check the ticket number. For a new issue, ask the team to open a new request. |
| “You already gave kudos to this update.” | Check the selected project and round. Kudos are limited to one per person per update. |
| “Only board members can give kudos.” | Ask the server manager to verify your Board role if the team update button rejects your click. |
| “Retry this delivery in the configured board channel.” | Use the current private board channel as the destination. If the board channel moved, have the server manager configure the new one first. |
| “Channel access denied. Restore the bot's channel permissions and /sdc retry.” | Ask the server manager to restore the bot’s channel permissions. Then check the original channel and retry the affected delivery. |
| “Send interrupted. Check Discord before /sdc retry.” | Look for the original message first. Discord may have accepted the post. Retry only after checking. |
| “The action failed. Ask the bot operator to check the application logs.” | Give the server manager the exact command, channel, time, and error. They also operate the bot. |

If a board command is missing from the menu, open the configured board channel and confirm Discord allows the app there. Ask the server manager to check the bot installation and app permissions if it stays missing.

## FAQ

1. **Do I need Manage Server for board work?** You need the configured Board role and access to the board channel. The server manager uses Manage Server for setup.
2. **Can I submit for a team?** Yes. Open the team channel for the round and use the shared member workflow. Your name appears as the editor.
3. **What if a team member submits in the wrong channel?** Ask them to open the correct team channel and submit there. Anyone using the other channel works on that channel’s shared update, so coordinate with that team before revising it.
4. **Can I reopen a closed round?** The bot freezes it at closing. If more submissions are needed, you can open a new round.
5. **Do we need to enable scheduling to get automatic check-in reminders?** A manual round can also get the 24-hour reminder if it opened early enough. The bot reminds teams that are still missing a submission.
6. **Do private confirmations mean the team saw the message?** A queued confirmation means the action is saved. Check the team channel and `/sdc status` for posting problems.
7. **Does changing a project contact transfer its open requests?** Existing requests keep their current owner. Use `/support assign` for each request you want to transfer.
8. **Will a later support resolution change the closed summary?** Closed summaries preserve the state at closing. The support card still shows the later resolution.
9. **Who handles permissions, missing roles, and a bot that is offline?** Contact the server manager. They manage roles and channels and operate the bot.

## Glossary

| Term | Meaning |
|---|---|
| Board channel | The private text channel where the bot accepts board commands and posts board information. |
| Board role | The configured Discord role the bot checks for board actions. |
| Manage Server | The Discord permission the server manager needs to configure the bot. |
| Contact | A board member who receives support alerts for a project. A particular request can be assigned to someone else. |
| Digest | The summary of participation, updates, and unresolved support for a round. |
| Frozen summary | The record saved when a round closes. |
| Delivery | One message or set of message parts the bot tries to post or update. |
| Uncertain delivery | A send the bot couldn’t confirm. Check Discord before retrying it. |
| Nudge | A board-channel reminder that a support request needs follow-up. |

## Open Questions

- What are the actual names of the club’s Board role and private board channel? The examples use **@SDC-Board** and **#sdc-board**.
- Which team channels and project names should appear in screenshots? The examples use **Team 7** and **#team-7**.
- What is the preferred way for members to reach the server manager in Discord? Both manuals refer to the server manager by role.
- Do the live role and channel settings match this workflow? Verify them on Discord when the board channel is ready.
