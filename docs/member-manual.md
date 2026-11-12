# SDC Check-in Bot Member Manual

## Table of contents

- [Welcome](#welcome)
- [Before You Start](#before-you-start)
- [Command Reference](#command-reference)
- [Things the Bot Does Automatically](#things-the-bot-does-automatically)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Glossary](#glossary)

## Welcome

The SDC Check-in Bot is an automated helper in the club’s Discord server. It collects a weekly update from each project and gives you a way to ask for help between updates. Your team can read past updates and see what changed.

Your team uses its own text channel, such as **#team-7**. Open your team’s channel when you want to work with its check-ins or support requests. Team channels are open to club members, so anyone who can use the bot there can submit or edit the channel’s shared update. Check the channel name before you send anything.

## Before You Start

A **server** is the club’s space in Discord. A **channel** is a conversation within that space. Text channels usually appear in the server’s channel list with a **#**. Click your team’s channel to open it. The bot uses the channel you’re in to tell which project you mean.

A **slash command** is an action you select from Discord’s command menu. Type `/` in the message box to open the menu. Start typing the command’s name, then click the matching command for the SDC bot or use the arrow keys and press **Enter** to select it. Fill in the required options Discord shows. Click an optional field if you want to use it. Press **Enter** again when you’re ready to send. On mobile, tap the send arrow.

The command examples show the finished input. Select the command from the menu first, then enter each value in its Discord field. If a value contains spaces, keep it in one field.

Bot replies that say **Only you can see this** are private. A check-in form opens just for you. When you submit it, your answers go to the team channel and the board. Support requests and follow-up notes are visible in the team channel. Use the bot for project information you’re comfortable sharing there.

Some commands are reserved for board members. To check your role, open your profile from the club server and look under **Roles** for the club’s Board role. Ask the server manager if you think it’s missing or if you’re unsure what it’s called.

### Your first command

1. Open a text channel in the club server.
2. Type `/project list` and select **project list** for the SDC bot.
3. Leave the optional fields blank and press **Enter**. Only you see the project list.
4. Find your team and click its channel link, such as **#team-7**.

[SCREENSHOT: The Discord slash menu with project list selected, followed by the private reply with a team channel link]

## Command Reference

### `/project list`

Find your team’s channel, milestone, and board contact.

1. Open any text channel in the club server where Discord lets you use the bot.
2. Select `/project list` and choose whether to include archived projects.
3. Send the command. In the private reply, click the channel for your team.

- `include_archived` is optional. Leave it blank for active projects only. Choose `True` to include archived projects.

**Example**  
`/project list`

**Example reply excerpt**

```text
#7 · Team 7 · Active · #team-7 · contact: @Maya
Milestone: Test the sign-in flow
```

**Common mistake.** If your former project is missing, try `/project list include_archived:True`. If you see “No projects to show.”, ask the server manager whether the teams have been registered.

### `/checkin submit`

Share one update for your team or revise the one a teammate already saved.

1. Open the team channel where the current round’s prompt appeared. Check that you have the right team.
2. Select `/checkin submit` and choose a status.
3. Send the command to open the **Project check-in** form.
4. Fill in your progress and next steps. Add blockers or a request for assistance if needed. If a teammate already submitted, the form shows the saved text. Review it before you change it.
5. Click **Submit** and look for a private confirmation. Your team’s update will appear in the team channel.

- `status` is required. Choose **On track** when your team is on course, **At risk** when a problem might delay progress, or **Blocked** when you can’t move forward until a problem is resolved.
- **Progress since the previous update** is required. Say what your team did. “No progress this week” is fine.
- **Next steps and current milestone** is required. Say what your team plans to do next.
- **Blockers** is optional. Describe anything stopping progress.
- **Assistance requested** is optional. Say what help your team needs.
- Each form field can contain up to 1,500 characters.

**Example**  
In **#team-7**, send `/checkin submit status:On track`. In the form, enter “Built the sign-in screen” for progress and “Run three usability tests” for next steps. Leave the two optional fields blank.

**Example private reply**

> Saved revision 1. Your update is queued for your project channel and the board summary.

A later save might say “Saved revision 2 (late).” The bot marks the latest version late if you save it after the deadline. If the round is still open, you can submit or edit after the deadline.

**Common mistakes.** Pick the status for your team as a whole. Leave blockers and assistance blank when you have none. Even an **On track** update can create a support request if either of those fields has text. If a teammate saves a newer version before you submit, reopen the form and review their changes.

#### Submit or edit update button

1. Find the current round’s prompt in your team channel and click **Submit or edit update**.
2. In the private reply, open **Choose your project’s status** and select **On track**, **At risk**, or **Blocked**.
3. Fill in and submit the same form described above.

For example, clicking the button in **#team-7** shows this private reply.

> Your answers will be shared in this project channel and with the SDC board. Choose a status to open the form.

Choose **On track**, fill out the form, and submit. A first update saved on time gets the same “Saved revision 1.” confirmation shown above.

**Common mistake.** If the dropdown stops responding after five minutes, click the prompt button again. The check-in form expires after 15 minutes. Copy any unsaved text you still have before reopening it.

[SCREENSHOT: The team’s weekly prompt, the private status dropdown, and the four fields in the Project check-in form]

### `/checkin history`

Look back at your team’s recent updates, starting with the newest round.

1. Open your team’s registered channel.
2. Select `/checkin history`. Set the options if you want a different number of rounds or the complete text.
3. Send the command and read the private reply. If it includes an attachment, open it for the full results.

- `rounds` is optional. Choose 1 to 26 rounds. The default is 6.
- `full` is optional. Choose `True` for the full saved text. The default shows shorter entries.

**Example**  
`/checkin history rounds:2`

**Example reply excerpt**

```text
Team 7 — check-in history (last 2 rounds)

Week 4 · open · On track · rev 1 · @Sam
Progress: Built the sign-in screen
Next steps: Run three usability tests

Week 3 · — no update submitted —
```

**Common mistake.** A round marked **open** can still receive an update. A line that says “no update submitted” in an open round describes what’s saved so far.

### `/checkin changes`

Compare a saved version of your team’s update with the version immediately before it.

1. Open your team’s registered channel.
2. Select `/checkin changes`. Leave both options blank to see changes in the latest version of the most recent update your team submitted.
3. Send the command. In the private reply, look for lines beginning with `+` for additions and `-` for removals.

- `revision` is optional. Enter the version number you want to inspect. If you leave it blank, the bot uses the latest version of the selected update.
- `round_id` is optional. Enter the round number if you want to look at a particular round. Use the number, such as `4`, without the `#`. Ask the server manager for the number if you only know the round label.

**Example**  
`/checkin changes revision:2 round_id:4`

**Example reply excerpt**

```diff
Team 7 — Week 4 · revision 2
Status: At risk → On track
Progress:
- Drafted the sign-in screen
+ Built the sign-in screen
Next steps: unchanged
```

**Common mistake.** Revision 1 is the first submission. The bot shows that version and says “First submission, so there is nothing earlier to compare.”

### `/support request`

Ask for project help whenever you need it, even between rounds.

1. Open your team’s registered channel.
2. Select `/support request` and explain what the team needs.
3. Send the command. Save the request number from the private confirmation if you want to refer to it later.
4. Look for the support card in your team channel and check it for follow-up.

- `description` is required. Use 1 to 2,000 characters. Include what you’ve tried and what help would move the project forward.

**Example**  
`/support request description:Could someone review our sign-in flow before Friday’s demo?`

**Example private reply**

> Support request #12 opened. Team and board alerts are queued.

**Common mistake.** Each time you send the command, it opens a new request. If the confirmation says it was queued but the card hasn’t appeared, check `/support list` before sending it again.

### `/support list`

See your project’s requests and check whether someone has taken ownership or resolved them.

1. Open your team’s registered channel.
2. Select `/support list` and send it.
3. Read the private list. Find the support card in the channel for any follow-up notes.

There are no options.

**Example**  
`/support list`

**Example private reply**

```text
#12 · project #7 · acknowledged · @Maya
Could someone review our sign-in flow before Friday’s demo?
```

**Common mistake.** The reply is a list of request descriptions and statuses. Open the support card in the channel to read the follow-up history.

[SCREENSHOT: A team support card with its request number, contact, and follow-up history]

## Things the Bot Does Automatically

- **Round prompts.** When a round opens, the bot posts a deadline and a **Submit or edit update** button in each participating channel. One teammate can submit for the whole team.
- **Deadline reminders.** The bot can remind teams that still need to submit around 24 hours before the deadline. A round opened with less than 24 hours to go skips the automatic reminder.
- **Update cards.** The bot posts your saved answers and who last edited them. When the team revises an update, the card usually updates in place and shows which fields changed. A change in status also alerts the board.
- **Support cards.** An **At risk** or **Blocked** check-in, a blocker, or a request for assistance creates a support request. Later edits update the linked request. If you need new help after it has been resolved, send a new request. Follow-up and resolution notes appear on the card in your team channel.
- **Skipped-week notices and kudos.** When an automatic round is skipped, you may see a note in your team channel. You may also see a kudos message for an update. The history reply includes the kudos count when there is one.

## Troubleshooting

| What you see | What to do |
|---|---|
| The command doesn’t appear. | Open the club server and type `/` in a text channel. Select the SDC bot’s result. If the command is still missing, ask the server manager to check the bot and the channel’s **Use Application Commands** permission. |
| The bot doesn’t respond, or Discord says the interaction failed. | For a button, reopen the current prompt and try again. For an update or support request, check history or the support list before resending. Tell the server manager which command or button you used and in which channel if the problem continues. |
| “Use this command in a registered team channel.” | Open your team’s channel from `/project list`. Run the command directly in that channel. A thread under the channel has its own message box. |
| “Use the team channel for this round's check-in.” | Find the current round’s prompt and use that channel. If your team recently moved, ask the server manager which channel the open round uses. |
| “This project is not in this check-in round.” | Ask the server manager whether the project is active and when it can join a round. |
| “More than one project uses this channel. Use your team's prompt.” | Find the current round’s prompt for your team and use its button. Let the server manager know the channel is shared by more than one registered project. |
| “More than one project uses this channel. Ask the server manager for help.” | Ask the server manager to check which project uses the channel. |
| “No matching round. Ask the board if a check-in round is open.” | Ask whether a round has opened. If you clicked an older prompt, look for the current one. |
| “This round is closed; its submissions are frozen.” | That prompt or form belongs to a closed round. Wait for the next round or ask the server manager what to do with your update. |
| “A teammate edited this update. Reopen the form to load their version.” | Reopen the form, read the newer text, and combine your changes with it. |
| “Reopen the form using your own account.” | Run the command or click the original prompt yourself to get a fresh form. |
| “Progress and next steps are required; 'No progress' is acceptable.” | Fill in both required fields. You can write “No progress this week” in the progress field. |
| “Describe the assistance needed in 1–2,000 characters.” | Fill in the description or shorten it. |
| “This project has not submitted any updates yet.” or “This project has no update in that round.” | Try `/checkin history` to see which rounds have an update, then rerun `/checkin changes`. |
| “The bot has not been set up yet. Ask the server manager for help.” or “The action failed. Ask the bot operator to check the application logs.” | Send the exact error and the channel name to the server manager. They also operate the bot. |

If a reply says **queued**, the bot saved your action and will try to post the message. If the post stays missing, tell the server manager the project channel and the saved revision or support request number.

## FAQ

1. **Do I need a team role?** Open the text channel for the team you joined. The channel tells the bot which project you mean.
2. **Can people from other teams read our update?** Anyone who can see your team channel can read what the bot posts there. The board also receives your update.
3. **Does every teammate need to submit?** One person submits on behalf of the project. Coordinate in your team channel so you don’t edit at the same time.
4. **Can someone else fix a typo?** Yes. They can reopen the form in the team channel and save a new revision.
5. **Can I submit after the deadline?** Yes, while the round is open. The latest revision is marked late if you save it after the deadline.
6. **Do I need to wait for the next check-in to ask for help?** You can use `/support request` at any time in your team channel.
7. **What does acknowledged mean on a support request?** Someone took ownership. When the request is resolved, look at the support card for the outcome.
8. **Why does the bot ask me to pick a status again when I edit?** Each form starts with your status choice. Pick the current status for the team, then check the text already in the form.
9. **Who can help if my role is missing or the bot seems broken?** Ask the server manager. Include the channel, the time, and what Discord or the bot showed you.

## Glossary

| Term | Meaning |
|---|---|
| Bot | An automated account that responds to commands and posts messages. |
| Server | The club’s shared space in Discord. |
| Channel | A named conversation in a server. A text channel usually starts with **#**. |
| Slash command | A bot action you select after typing `/`. |
| Option | A field you fill in when sending a command. Required options need a value. |
| Private reply | A bot reply only you can see in the channel where you used the command. |
| Role | A Discord label that can grant access or permissions. |
| Check-in round | A period when projects can submit a shared update. |
| Revision | A saved version of a check-in. Revision 1 is the first save. |
| Milestone | An upcoming project goal. |
| Blocker | A problem that prevents progress. |
| Support request | A numbered request for help, also called a ticket. |
