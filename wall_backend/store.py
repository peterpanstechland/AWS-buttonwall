"""SQLite sessions. A ranked row is inserted once, inside the finalize transaction."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from reference.catalog import ROOT, load_game_config
from reference.scoring import rank_key

SCHEMA = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
MIGRATE_V2 = (ROOT / "db" / "migrate_v2.sql").read_text(encoding="utf-8")


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(sessions)")}
        if "event_id" not in columns:
            self.conn.executescript(MIGRATE_V2)
        self.conn.commit()
        self._alias = 41

    def next_alias(self) -> int:
        self._alias += 1
        return self._alias

    def persist_event(self, payload: dict, disposition: str, node_id: str | None = None):
        self.conn.execute(
            """
            INSERT OR IGNORE INTO events (
                event_id, boot_id, press_id, session_id, round_id, step_epoch,
                button_id, service_key, raw_t_us, confirmed_t_us, disposition, graph_node_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{payload.get('boot_id')}/{payload.get('press_id')}",
                payload.get("boot_id"),
                payload.get("press_id"),
                payload.get("session_id"),
                payload.get("round_id"),
                payload.get("step_epoch"),
                payload.get("button_id"),
                payload.get("service_key"),
                payload.get("raw_press_t_us"),
                payload.get("confirmed_t_us"),
                disposition,
                node_id,
            ),
        )
        self.conn.commit()

    def mark_event(self, identity: tuple, disposition: str, node_id: str | None = None):
        self.conn.execute(
            "UPDATE events SET disposition = ?, graph_node_id = COALESCE(?, graph_node_id) WHERE boot_id = ? AND press_id = ?",
            (disposition, node_id, identity[0], identity[1]),
        )
        self.conn.commit()

    def finish_session(self, row: dict, ranked: bool):
        config = load_game_config()
        zone = ZoneInfo(config["event_timezone"])
        day = datetime.now(zone).date().isoformat()
        try:
            self.conn.execute("BEGIN")
            self.conn.execute(
                """
                INSERT INTO sessions (
                    session_id, mode, state, pack_id, pack_hash, ruleset_version, scoring_version,
                    participant_class, boot_id, alias, solutions_completed, score, invalid_hits,
                    last_completed_t_ms, created_at, finalized_at, event_id, day_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    state = excluded.state,
                    solutions_completed = excluded.solutions_completed,
                    score = excluded.score,
                    invalid_hits = excluded.invalid_hits,
                    last_completed_t_ms = excluded.last_completed_t_ms,
                    finalized_at = excluded.finalized_at
                """,
                (
                    row["session_id"],
                    row["mode"],
                    row["state"],
                    row["pack_id"],
                    row["pack_hash"],
                    row["ruleset_version"],
                    row["scoring_version"],
                    row["participant_class"],
                    row["boot_id"],
                    row["alias"],
                    row["solutions_completed"],
                    row["score"],
                    row["invalid_hits"],
                    row["last_completed_t_ms"],
                    day,
                    day,
                    "default",
                    day,
                ),
            )
            if ranked:
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO leaderboard (
                        session_id, pack_id, pack_hash, ruleset_version, scoring_version, participant_class,
                        alias, solutions_completed, score, invalid_hits, last_completed_t_ms, trajectory_json,
                        created_at, event_day
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["session_id"],
                        row["pack_id"],
                        row["pack_hash"],
                        row["ruleset_version"],
                        row["scoring_version"],
                        row["participant_class"],
                        row["alias"],
                        row["solutions_completed"],
                        row["score"],
                        row["invalid_hits"],
                        row["last_completed_t_ms"],
                        json.dumps(row["trajectory"]),
                        day,
                        day,
                    ),
                )
            if row.get("failure"):
                self.conn.execute(
                    "INSERT INTO audit (at, action, detail) VALUES (datetime('now'), 'workflow_collapsed', ?)",
                    (json.dumps({"session_id": row["session_id"], **row["failure"]}),),
                )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def leaderboard(self, pack_id: str, pack_hash: str) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT alias, solutions_completed, score, invalid_hits, last_completed_t_ms, trajectory_json
            FROM leaderboard
            WHERE pack_id = ? AND pack_hash = ?
            """,
            (pack_id, pack_hash),
        ).fetchall()
        ranked = sorted((dict(row) for row in rows), key=rank_key)
        for index, row in enumerate(ranked, start=1):
            row["place"] = index
            row["trajectory"] = json.loads(row.pop("trajectory_json"))
        return ranked[:10]

    def top_ghost(self, pack_id: str, pack_hash: str):
        rows = self.leaderboard(pack_id, pack_hash)
        if not rows:
            return None
        best = rows[0]
        return {
            "alias": best["alias"],
            "solutions_completed": best["solutions_completed"],
            "milestones": best["trajectory"],
        }

    def clear_leaderboard(self):
        self.conn.execute("DELETE FROM leaderboard")
        self.conn.execute("INSERT INTO audit (at, action, detail) VALUES (datetime('now'), 'clear', 'leaderboard')")
        self.conn.commit()
