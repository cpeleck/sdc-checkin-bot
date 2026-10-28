CREATE TABLE settings (
    guild_id INTEGER PRIMARY KEY,
    board_role_id INTEGER NOT NULL,
    board_channel_id INTEGER NOT NULL,
    timezone TEXT NOT NULL,
    schedule_json TEXT,
    schedule_updated_at TEXT
);
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL REFERENCES settings(guild_id),
    name TEXT NOT NULL COLLATE NOCASE,
    channel_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    contact_id INTEGER,
    milestone TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE(guild_id, name)
);
CREATE TABLE rounds (
    id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL REFERENCES settings(guild_id),
    label TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    due_at TEXT NOT NULL,
    closed_at TEXT,
    source TEXT NOT NULL CHECK(source IN ('manual', 'schedule')),
    schedule_key TEXT,
    summary TEXT,
    UNIQUE(guild_id, schedule_key)
);
CREATE UNIQUE INDEX one_open_round ON rounds(guild_id) WHERE closed_at IS NULL;
CREATE TABLE round_projects (
    round_id INTEGER NOT NULL REFERENCES rounds(id),
    project_id INTEGER NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    channel_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    contact_id INTEGER,
    milestone TEXT NOT NULL,
    PRIMARY KEY(round_id, project_id)
);
CREATE TABLE checkins (
    id INTEGER PRIMARY KEY,
    round_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('On track', 'At risk', 'Blocked')),
    progress TEXT NOT NULL,
    next_steps TEXT NOT NULL,
    blockers TEXT NOT NULL,
    assistance TEXT NOT NULL,
    author_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    late INTEGER NOT NULL,
    version INTEGER NOT NULL,
    UNIQUE(round_id, project_id),
    FOREIGN KEY(round_id, project_id) REFERENCES round_projects(round_id, project_id)
);
CREATE TABLE checkin_revisions (
    id INTEGER PRIMARY KEY,
    checkin_id INTEGER NOT NULL REFERENCES checkins(id),
    version INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    UNIQUE(checkin_id, version)
);
CREATE TABLE support_tickets (
    id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL REFERENCES settings(guild_id),
    project_id INTEGER NOT NULL REFERENCES projects(id),
    checkin_id INTEGER UNIQUE REFERENCES checkins(id),
    description TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('open', 'acknowledged', 'resolved')),
    assignee_id INTEGER,
    reporter_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE TABLE support_notes (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES support_tickets(id),
    author_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE deliveries (
    id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL REFERENCES settings(guild_id),
    delivery_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK(state IN ('pending', 'sending', 'sent', 'retry', 'failed', 'ambiguous', 'skipped')),
    version INTEGER NOT NULL DEFAULT 1,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    message_ids TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX delivery_queue ON deliveries(state, next_attempt_at);
CREATE INDEX tickets_by_project ON support_tickets(guild_id, project_id, state);
