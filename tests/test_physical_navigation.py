"""Physical wall navigation, persisted preferences, and unapplied LED plans."""

import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from wall_backend import server
from wall_backend.engine import Engine
from wall_backend.store import Store


class PhysicalNavigationTests(unittest.TestCase):
    def setUp(self):
        self.now = 5_000_000
        self.store = Store()
        self.engine = Engine(self.store, clock_us=lambda: self.now)
        self.engine.cfg["pre_countdown_ms"] = 0
        self.engine.tick()
        self.by_slot = {button["slot"]: button for button in self.engine.services}

    def tearDown(self):
        self.store.conn.close()

    def advance(self, milliseconds=100):
        self.now += milliseconds * 1000
        self.engine.tick()

    def hit(self, slot):
        self.engine.sim_click(self.by_slot[slot]["id"])
        self.advance()

    def gesture(self, kind="CLICK"):
        self.engine._gesture(kind)
        self.advance()

    def open_settings(self):
        self.hit("D4")
        self.assertEqual(self.engine.state, "SETTINGS")

    def test_modes_only_select_and_kiro_confirms(self):
        self.gesture()
        for slot, mode in (("A2", "RUSH60_RANKED"), ("B1", "FREE"), ("A1", "GUIDED")):
            self.hit(slot)
            self.assertEqual(self.engine.state, "MODE_LOBBY")
            self.assertEqual(self.engine.mode, mode)
            self.assertIsNone(self.engine.session_id)
            selected = [c["slot"] for c in self.engine.snapshot()["navigation"]["cells"] if c["selected"]]
            self.assertEqual(selected, [slot])
        self.gesture()
        self.assertEqual(self.engine.state, "MISSION_SELECT")
        self.assertIsNone(self.engine.session_id)
        self.hit("C3")
        self.assertEqual(self.engine.state, "MODE_LOBBY")
        self.hit("A2")
        self.gesture("DOUBLE")
        self.assertEqual(self.engine.state, "ACTIVE")
        self.assertEqual(self.engine.mode, "RUSH60_RANKED")

    def test_eight_scenarios_follow_the_audience_grid_order(self):
        self.gesture()
        self.gesture()
        for slot, mission_id in zip(("A1", "A2", "B1", "B2", "A3", "A4", "B3", "B4"), self.engine.cfg["pack"]["mission_ids"]):
            self.hit(slot)
            self.assertEqual(self.engine.state, "MISSION_SELECT")
            self.assertEqual(self.engine.snapshot()["menu_mission_id"], mission_id)
            selected = [c for c in self.engine.snapshot()["navigation"]["cells"] if c["selected"]]
            self.assertEqual(selected[0]["slot"], slot)
            self.assertEqual(selected[0]["action"], "mission:" + mission_id)
        self.gesture()
        self.assertEqual(self.engine.state, "ACTIVE")
        self.assertEqual(self.engine.mission_id, "M08_ML")

    def test_settings_enter_and_return_without_losing_navigation_selection(self):
        self.gesture("HOLD")
        self.assertEqual(self.engine.state, "SETTINGS")
        self.gesture("HOLD")
        self.assertEqual(self.engine.state, "IDLE")
        self.gesture()
        self.hit("B1")
        self.open_settings()
        self.hit("C3")
        self.assertEqual(self.engine.state, "MODE_LOBBY")
        self.assertEqual(self.engine.mode, "FREE")
        self.hit("A1")
        self.gesture()
        self.hit("B3")
        self.open_settings()
        self.gesture()
        self.assertEqual(self.engine.state, "MISSION_SELECT")
        self.assertEqual(self.engine.snapshot()["menu_mission_id"], "M07_EVENT_DRIVEN")
        self.open_settings()
        self.hit("D4")
        self.assertEqual(self.engine.state, "IDLE")

    def test_every_settings_key_and_replay_contract(self):
        self.open_settings()
        self.assertEqual(self.engine.ui_settings, {"language": "zh", "voice_enabled": True, "volume": 80,
                                                 "reduced_motion": False, "revision": 0, "replay_seq": 0})
        self.hit("A2")
        self.assertEqual(self.engine.ui_settings["language"], "en")
        self.hit("A1")
        self.assertEqual(self.engine.ui_settings["language"], "zh")
        self.hit("B1")
        self.assertFalse(self.engine.ui_settings["voice_enabled"])
        revision = self.engine.ui_settings["revision"]
        self.hit("B2")
        self.assertTrue(self.engine.ui_settings["voice_enabled"])
        self.assertEqual(self.engine.ui_settings["revision"], revision + 1)
        self.assertEqual(self.engine.ui_settings["replay_seq"], 1)
        self.hit("B3")
        self.assertTrue(self.engine.ui_settings["reduced_motion"])
        for _ in range(8):
            self.hit("A3")
        self.assertEqual(self.engine.ui_settings["volume"], 0)
        for _ in range(8):
            self.hit("A4")
        self.assertEqual(self.engine.ui_settings["volume"], 100)
        self.assertEqual(self.engine.ui_settings, self.store.ui_settings())

    def test_gameplay_keys_never_become_navigation_shortcuts(self):
        self.gesture()
        self.hit("B1")
        self.gesture()
        for slot in ("A1", "A2", "B1", "C3", "D4"):
            self.hit(slot)
            self.assertEqual(self.engine.state, "ACTIVE")
            self.assertEqual(self.engine.mode, "FREE")
            self.assertEqual(self.engine.selected[self.by_slot[slot]["key"]], 1)
        self.assertFalse(self.engine.open_settings())
        self.assertTrue(all(c["action"] == "service" for c in self.engine.navigation()["cells"]))
        self.engine.home()
        self.gesture()
        self.gesture()
        self.hit("A1")  # Select voice explicitly; default guided selection is random.
        self.gesture()
        self.hit("D4")  # Cognito is an incorrect answer for the voice workflow.
        self.assertEqual(self.engine.state, "RESULT")
        self.assertEqual(self.engine.failure["reason"], "WRONG_SERVICE")

    def test_result_settings_preserve_final_score_and_return_to_result(self):
        self.gesture()
        self.gesture()
        self.gesture()
        self.hit("D2")
        session_id = self.engine.session_id
        result = self.engine.snapshot()
        self.open_settings()
        self.hit("A2")
        self.gesture()
        self.assertEqual(self.engine.state, "RESULT")
        self.assertEqual(self.engine.session_id, session_id)
        self.assertEqual(self.engine.score(), result["score"])
        self.assertEqual(self.engine.failure, result["failure"])
        self.assertEqual(self.engine.snapshot()["idle_return_remaining_ms"], 29_900)
        self.hit("C3")
        self.assertEqual(self.engine.state, "IDLE")
        self.assertEqual(self.store.conn.execute("SELECT count(*) FROM sessions").fetchone()[0], 1)

    def test_stale_or_wrong_context_hits_cannot_open_settings(self):
        self.gesture()
        base = {"boot_id": self.engine.boot_id, "press_id": 900, "button_id": 16,
                "service_key": "COGNITO", "raw_press_t_us": self.now, "confirmed_t_us": self.now,
                "session_id": None, "round_id": None, "step_epoch": 0}
        for number, change in enumerate((
            {"raw_press_t_us": self.engine.navigation_since_us - 1},
            {"session_id": "previous-session"}, {"round_id": "previous-round"},
            {"boot_id": "previous-boot"}, {"service_key": "EC2"},
        )):
            self.engine._hit({**base, **change, "press_id": 900 + number})
            self.assertEqual(self.engine.state, "MODE_LOBBY")
        self.hit("D4")
        self.assertEqual(self.engine.state, "SETTINGS")

    def test_late_gameplay_hit_cannot_become_result_navigation(self):
        self.gesture()
        self.gesture()
        self.gesture()
        old = {"boot_id": self.engine.boot_id, "press_id": 901, "button_id": 16,
               "service_key": "COGNITO", "raw_press_t_us": self.now, "confirmed_t_us": self.now,
               "session_id": self.engine.session_id, "round_id": self.engine.round_id, "step_epoch": self.engine.epoch}
        self.advance()
        self.hit("D2")
        self.engine._hit(old)
        self.assertEqual(self.engine.state, "RESULT")
        self.assertEqual(self.store.conn.execute("SELECT disposition FROM events WHERE press_id = 901").fetchone()[0], "STALE_NAVIGATION")

    def test_duplicate_settings_input_is_applied_once(self):
        self.open_settings()
        payload = {"boot_id": self.engine.boot_id, "press_id": 910, "button_id": 5,
                   "service_key": "API_GATEWAY", "raw_press_t_us": self.now, "confirmed_t_us": self.now,
                   "session_id": None, "round_id": None, "step_epoch": 0}
        self.engine._hit(payload)
        self.engine._hit(payload)
        self.assertFalse(self.engine.ui_settings["voice_enabled"])
        self.assertEqual(self.engine.ui_settings["revision"], 1)

    def test_settings_timeout_tracks_real_inputs_not_polling(self):
        self.open_settings()
        self.advance(89_000)
        self.hit("A3")
        self.assertEqual(self.engine.snapshot()["idle_return_remaining_ms"], 89_900)
        self.advance(89_899)
        self.assertEqual(self.engine.state, "SETTINGS")
        self.advance(1)
        self.assertEqual(self.engine.state, "IDLE")
        self.assertEqual(self.engine.ui_settings["volume"], 60)

    def test_light_plan_is_complete_consistent_and_explicitly_unapplied(self):
        self.gesture()
        snap = self.engine.snapshot()
        plan = snap["light_plan"]
        self.assertTrue(plan["simulated"])
        self.assertFalse(plan["hardware_applied"])
        self.assertEqual(plan["kiro"], {"rgb": False, "lamp": "constant"})
        self.assertEqual({c["button_id"] for c in plan["cells"]}, set(range(1, 17)))
        nav = {c["button_id"]: c for c in snap["navigation"]["cells"]}
        for cell in plan["cells"]:
            if cell["button_id"] in nav:
                self.assertEqual(cell["color"], nav[cell["button_id"]]["color"])
                self.assertEqual(cell["effect"], nav[cell["button_id"]]["effect"])
            else:
                self.assertEqual(cell["effect"], "off")
        self.assertEqual(nav[1]["effect"], "pulse")
        self.assertEqual(nav[2]["effect"], "breathe")
        self.assertEqual(nav[16]["effect"], "steady")

    def test_strict_preferences_reject_invalid_values_and_control_fields(self):
        self.open_settings()
        before = dict(self.engine.ui_settings)
        for changes in ({}, {"language": "fr"}, {"language": []}, {"voice_enabled": 1},
                        {"volume": True}, {"volume": -1}, {"volume": 101}, {"reduced_motion": "false"},
                        {"revision": 99}, {"replay_seq": 8}, {"unknown": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.engine.update_ui_settings(changes)
        self.assertEqual(self.engine.ui_settings, before)
        self.assertEqual(self.store.ui_settings(), before)

    def test_read_only_database_never_reports_a_saved_change(self):
        self.open_settings()
        before = dict(self.engine.ui_settings)
        self.store.conn.execute("PRAGMA query_only = ON")
        with self.assertRaises(sqlite3.OperationalError):
            self.engine.update_ui_settings({"language": "en"})
        self.assertEqual(self.engine.ui_settings, before)
        self.assertEqual(self.store.ui_settings(), before)
        self.assertEqual(self.engine.snapshot()["settings_error"], "SETTINGS_SAVE_FAILED")

    def test_preferences_survive_a_new_store_and_engine(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "settings.db"
            first = Store(database)
            first.save_ui_settings({"language": "en", "volume": 40, "voice_enabled": False, "reduced_motion": True})
            first.conn.close()
            second = Store(database)
            try:
                engine = Engine(second)
                self.assertEqual(engine.ui_settings, {"language": "en", "volume": 40, "voice_enabled": False,
                                                      "reduced_motion": True, "revision": 1, "replay_seq": 0})
                self.assertEqual(second.conn.execute("SELECT count(*) FROM sessions").fetchone()[0], 0)
            finally:
                second.conn.close()

    def test_settings_api_is_strict_state_gated_and_reports_storage_failure(self):
        handler = object.__new__(server.Handler)
        handler.path = "/api/ui/settings"
        handler._json = Mock()
        def post(body):
            raw = json.dumps(body).encode()
            handler.headers = {"Content-Length": str(len(raw))}
            handler.rfile = io.BytesIO(raw)
            handler._post()
        with patch.object(server, "ENGINE", self.engine), patch.object(server, "broadcast"):
            post({"volume": 20})
            self.assertEqual(handler._json.call_args.args[1], 409)
            self.open_settings()
            post(["volume", 20])
            self.assertEqual(handler._json.call_args.args[1], 400)
            post({"volume": "20"})
            self.assertEqual(handler._json.call_args.args[1], 400)
            post({"volume": 20})
            self.assertEqual(handler._json.call_args.args[0]["ui_settings"]["volume"], 20)
            self.store.conn.execute("PRAGMA query_only = ON")
            post({"volume": 40})
            self.assertEqual(handler._json.call_args.args[1], 503)
            self.assertEqual(self.engine.ui_settings["volume"], 20)


if __name__ == "__main__":
    unittest.main()
