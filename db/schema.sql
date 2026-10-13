CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    state TEXT NOT NULL,
    pack_id TEXT,
    pack_hash TEXT,
    ruleset_version TEXT NOT NULL,
    scoring_version TEXT NOT NULL,
    participant_class TEXT NOT NULL,
    boot_id TEXT,
    alias TEXT,
    solutions_completed INTEGER NOT NULL DEFAULT 0,
    score INTEGER NOT NULL DEFAULT 0,
    invalid_hits INTEGER NOT NULL DEFAULT 0,
    last_completed_t_ms INTEGER,
    created_at TEXT NOT NULL,
    finalized_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    boot_id TEXT NOT NULL,
    press_id INTEGER NOT NULL,
    session_id TEXT,
    round_id TEXT,
    step_epoch INTEGER,
    button_id INTEGER,
    service_key TEXT,
    raw_t_us INTEGER,
    confirmed_t_us INTEGER,
    disposition TEXT,
    graph_node_id TEXT,
    UNIQUE (boot_id, press_id)
);

CREATE TABLE IF NOT EXISTS leaderboard (
    session_id TEXT PRIMARY KEY,
    pack_id TEXT NOT NULL,
    pack_hash TEXT NOT NULL,
    ruleset_version TEXT NOT NULL,
    scoring_version TEXT NOT NULL,
    participant_class TEXT NOT NULL,
    alias TEXT NOT NULL,
    solutions_completed INTEGER NOT NULL,
    score INTEGER NOT NULL,
    invalid_hits INTEGER NOT NULL,
    last_completed_t_ms INTEGER,
    trajectory_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    event_day TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL
);
