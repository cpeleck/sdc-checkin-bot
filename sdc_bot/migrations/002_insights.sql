-- Stale support nudges: NULL disables them.
ALTER TABLE settings ADD COLUMN nudge_days INTEGER;

CREATE TABLE kudos (
    id INTEGER PRIMARY KEY,
    checkin_id INTEGER NOT NULL REFERENCES checkins(id),
    author_id INTEGER NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(checkin_id, author_id)
);

-- A skipped week is stored as the local Monday of that week.
CREATE TABLE schedule_skips (
    guild_id INTEGER NOT NULL REFERENCES settings(guild_id),
    week_start TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(guild_id, week_start)
);
