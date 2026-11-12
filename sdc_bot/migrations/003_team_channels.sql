ALTER TABLE round_projects DROP COLUMN role_id;
ALTER TABLE projects DROP COLUMN role_id;

-- Preserve existing prompts and reminders that are still queued or need retrying.
UPDATE deliveries
SET payload_json = json_remove(
    json_set(payload_json, '$.text', replace(
        substr(json_extract(payload_json, '$.text'), instr(json_extract(payload_json, '$.text'), '> ') + 2),
        'Any teammate with the project role can edit.',
        'Anyone with access to this channel can edit.'
    )),
    '$.role_ids'
)
WHERE kind IN ('prompt', 'reminder')
  AND json_extract(payload_json, '$.text') LIKE '<@&%> %';
