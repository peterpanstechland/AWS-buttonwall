-- Migration v2. The V1.2 schema has no event_id. Apply only when that column is absent.
ALTER TABLE sessions ADD COLUMN event_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE sessions ADD COLUMN day_key TEXT;
CREATE INDEX IF NOT EXISTS idx_event_rank ON sessions(
    event_id, day_key, mode, state, pack_id, pack_hash, ruleset_version, scoring_version, participant_class
);
