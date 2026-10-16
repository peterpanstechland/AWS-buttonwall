"""Unattended kiosk recovery must never alter a live timed game."""

import io
import unittest
from unittest.mock import Mock, patch

from reference.awg1 import COUNTDOWN_EVENT, TIMER_EVENT, Frame
from wall_backend import server
from wall_backend.engine import Engine
from wall_backend.store import Store


class SelfServiceTests(unittest.TestCase):
    def setUp(self):
        self.now = 5_000_000
        self.engine = Engine(Store(), clock_us=lambda: self.now)
        self.engine.tick()
        self.engine.cfg["pre_countdown_ms"] = 0

    def tearDown(self):
        self.engine.store.conn.close()

    def advance(self, milliseconds):
        self.now += milliseconds * 1000
        self.engine.tick()

    def start(self, mode):
        self.engine._gesture("CLICK")
        self.engine.select_mode(mode)
        self.engine.start("M01_VOICE")

    def test_polling_does_not_keep_abandoned_menu_alive(self):
        self.engine._gesture("CLICK")
        for seconds in range(1, 90):
            self.advance(1000)
            self.assertEqual(self.engine.snapshot()["idle_return_remaining_ms"], (90 - seconds) * 1000)
        self.advance(1000)
        self.assertEqual(self.engine.state, "IDLE")
        self.assertIsNone(self.engine.snapshot()["idle_return_remaining_ms"])

    def test_real_navigation_refreshes_menu_timeout(self):
        self.engine._gesture("CLICK")
        self.advance(89_000)
        self.engine._gesture("DOUBLE")
        self.assertEqual(self.engine.state, "MISSION_SELECT")
        self.assertEqual(self.engine.snapshot()["idle_return_remaining_ms"], 90_000)
        self.advance(89_000)
        self.assertEqual(self.engine.state, "MISSION_SELECT")
        self.advance(1000)
        self.assertEqual(self.engine.state, "IDLE")

    def test_free_input_and_review_refresh_timeout_then_clear_next_session(self):
        self.start("FREE")
        self.advance(119_000)
        self.engine.sim_click(3)
        self.assertEqual(self.engine.snapshot()["idle_return_remaining_ms"], 120_000)
        self.advance(1000)
        self.assertEqual(self.engine.state, "RESULT")
        self.assertEqual(self.engine.notice, "FREE_TIME_UP")
        self.assertEqual(self.engine.solutions, 0)
        self.advance(30_000)
        self.assertEqual(self.engine.state, "IDLE")
        self.assertFalse(self.engine.selected)
        self.assertFalse(self.engine.candidates)
        self.assertIsNone(self.engine.session_id)
        self.assertFalse(self.engine.mcu.scoring_open)

    def test_guided_pause_returns_home_without_changing_step_rules(self):
        self.start("GUIDED")
        self.engine._gesture("CLICK")
        remaining = self.engine.snapshot()["step_remaining_ms"]
        self.advance(119_000)
        self.assertEqual(self.engine.snapshot()["step_remaining_ms"], remaining)
        self.assertTrue(self.engine.paused)
        self.advance(1000)
        self.assertEqual(self.engine.state, "IDLE")
        self.assertFalse(self.engine.paused)

    def test_result_gets_full_reading_time_after_timeout(self):
        self.start("GUIDED")
        self.advance(10_020)
        self.assertEqual(self.engine.state, "RESULT")
        self.assertEqual(self.engine.snapshot()["idle_return_remaining_ms"], 30_000)
        row_count = self.engine.store.conn.execute("SELECT count(*) FROM sessions").fetchone()[0]
        self.advance(29_999)
        self.assertEqual(self.engine.state, "RESULT")
        self.advance(1)
        self.assertEqual(self.engine.state, "IDLE")
        self.assertEqual(self.engine.store.conn.execute("SELECT count(*) FROM sessions").fetchone()[0], row_count)

    def test_live_rush_states_have_no_idle_exit_and_home_cannot_bypass_forfeit(self):
        self.engine.mcu = None
        for mode in ("RUSH60_RANKED", "RUSH60_PRACTICE"):
            for state in ("PREPARE", "COUNTDOWN", "ACTIVE", "SETTLING"):
                with self.subTest(mode=mode, state=state):
                    self.engine.mode = mode
                    self.engine.state = state
                    self.engine.session_id = "in-progress"
                    self.advance(600_000)
                    self.assertEqual(self.engine.state, state)
                    self.assertIsNone(self.engine.snapshot()["idle_return_remaining_ms"])
                    self.assertFalse(self.engine.home())
                    self.assertEqual(self.engine.session_id, "in-progress")

    def test_confirmed_rush_forfeit_then_home_is_allowed(self):
        self.start("RUSH60_RANKED")
        self.engine._gesture("HOLD")
        self.assertFalse(self.engine.home())
        self.engine._gesture("DOUBLE")
        self.assertEqual(self.engine.state, "INTERRUPTED")
        self.assertTrue(self.engine.home())
        self.assertEqual(self.engine.state, "IDLE")
        self.assertEqual(self.engine.leaderboard(), [])

    def test_home_during_guided_countdown_cancels_stale_timer(self):
        self.engine.cfg["pre_countdown_ms"] = 3000
        self.start("GUIDED")
        self.engine.tick()
        old_session = self.engine.session_id
        self.assertEqual(self.engine.state, "COUNTDOWN")
        self.assertTrue(self.engine.home())
        self.advance(5000)
        self.assertEqual(self.engine.state, "IDLE")
        self.engine.on_frame(Frame(COUNTDOWN_EVENT, {"session_id": old_session, "event": "1"}, 1, False, False))
        self.engine.on_frame(Frame(TIMER_EVENT, {"session_id": old_session, "event": "GO", "t0_us": self.now}, 2, False, False))
        self.assertEqual(self.engine.state, "IDLE")
        self.start("FREE")
        self.advance(10_000)
        self.assertEqual(self.engine.state, "ACTIVE")
        self.assertIsNone(self.engine.failure)

    def test_inactivity_can_be_disabled_per_state(self):
        self.engine.cfg["inactivity"]["menu_ms"] = 0
        self.engine._gesture("CLICK")
        self.advance(600_000)
        self.assertEqual(self.engine.state, "MODE_LOBBY")
        self.assertIsNone(self.engine.snapshot()["idle_return_remaining_ms"])

    def test_home_api_returns_snapshot_or_conflict(self):
        handler = object.__new__(server.Handler)
        handler.path = "/api/game/home"
        handler.headers = {"Content-Length": "2"}
        handler._json = Mock()
        with patch.object(server, "ENGINE", self.engine), patch.object(server, "broadcast"):
            self.engine._gesture("CLICK")
            handler.rfile = io.BytesIO(b"{}")
            handler._post()
            self.assertEqual(handler._json.call_args.args[0]["state"], "IDLE")
            self.start("RUSH60_RANKED")
            handler.rfile = io.BytesIO(b"{}")
            handler._post()
            self.assertEqual(handler._json.call_args.args[1], 409)
            self.assertEqual(handler._json.call_args.args[0]["error"], "RUSH_IN_PROGRESS")
            self.assertEqual(self.engine.state, "ACTIVE")


if __name__ == "__main__":
    unittest.main()
