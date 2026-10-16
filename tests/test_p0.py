import struct
import unittest
from collections import Counter

from reference.awg1 import ACK, BUTTON_HIT, HELLO, Parser, encode_frame
from reference.catalog import load_game_config, load_missions, pack_hash, validate_content
from reference.rules import analyze_selection, required_done, take_role
from reference.scoring import combo_bonus, display_score, rank_key
from wall_backend.engine import Engine
from wall_backend.mcu import VirtualMcu
from wall_backend.store import Store


class Clock:
    def __init__(self):
        self.t = 5_000_000

    def __call__(self):
        return self.t


class ProtocolTests(unittest.TestCase):
    def test_round_trip_and_split_and_sticky(self):
        frame = encode_frame(HELLO, {"proto_minor": 2, "name": "墙"}, 7, ack_required=True)
        parser = Parser()
        self.assertEqual(parser.feed(frame[:3]), [])
        self.assertEqual(parser.feed(frame[3:10]), [])
        got = parser.feed(frame[10:])
        self.assertEqual(got[0][0].payload["name"], "墙")
        other = encode_frame(ACK, {"ack_seq": 1, "status": "OK"}, 8)
        sticky = parser.feed(frame + other)
        self.assertEqual([item[0].msg_type for item in sticky], [HELLO, ACK])

    def test_bad_crc_then_recover(self):
        good = bytearray(encode_frame(HELLO, {"ok": True}, 1))
        good[-1] ^= 0xFF
        nxt = encode_frame(ACK, {"ack_seq": 1, "status": "OK"}, 2)
        parsed = Parser().feed(bytes(good) + nxt)
        self.assertEqual(parsed[0], (None, "BAD_CRC"))
        self.assertEqual(parsed[1][0].msg_type, ACK)

    def test_oversize_and_bad_utf8(self):
        body = b"{" + b"a" * 2048
        head = struct.pack("<BBBBIH", 1, HELLO, 0, 0, 1, len(body))
        packet = b"\xA5\x5A" + head + body + struct.pack("<I", 0)
        parsed = Parser().feed(packet)
        self.assertEqual(parsed[0][1], "BAD_FRAME")
        import zlib

        payload = b"\xff\xfe"
        head = struct.pack("<BBBBIH", 1, HELLO, 0, 0, 4, len(payload))
        region = head + payload
        packet = b"\xA5\x5A" + region + struct.pack("<I", zlib.crc32(region) & 0xFFFFFFFF)
        self.assertEqual(Parser().feed(packet)[0][1], "BAD_JSON")


class ContentTests(unittest.TestCase):
    def test_catalog_and_pack(self):
        self.assertEqual(validate_content(), [])
        config = load_game_config()
        missions = {mission["id"]: mission for mission in load_missions()}
        self.assertNotIn("M09_PROTECTED_WEB", config["pack"]["mission_ids"])
        self.assertEqual(len(pack_hash()), 64)
        for mission_id in config["pack"]["mission_ids"]:
            self.assertTrue(missions[mission_id]["ranked"])


class ScoreTests(unittest.TestCase):
    def test_combo_and_floor_and_rank(self):
        config = load_game_config()
        bonuses = [combo_bonus(streak, config["combo_step"], config["combo_cap"]) for streak in range(1, 11)]
        self.assertEqual(bonuses[0], 0)
        self.assertEqual(bonuses[1], 20)
        self.assertEqual(bonuses[-1], 100)
        self.assertEqual(display_score(-10, 0), 0)
        rows = [
            {"solutions_completed": 4, "score": 2400, "invalid_hits": 3, "last_completed_t_ms": 50000},
            {"solutions_completed": 3, "score": 2900, "invalid_hits": 0, "last_completed_t_ms": 1000},
        ]
        self.assertEqual(sorted(rows, key=rank_key)[0]["solutions_completed"], 4)


class GestureTests(unittest.TestCase):
    def test_double_and_hold_are_exclusive(self):
        clock = Clock()
        mcu = VirtualMcu(lambda: clock.t)
        mcu.cfg["click_window_us"] = 300_000
        mcu.cfg["hold_us"] = 2_000_000
        mcu.click(0, clock.t)
        clock.t += 250_000
        mcu.click(0, clock.t)
        kinds = [frame.payload["gesture"] for frame in mcu.out if frame.msg_type == 0x12]
        self.assertEqual(kinds, ["DOUBLE"])
        clock.t += 1_000_000
        mcu.out.clear()
        mcu.levels[0] = True
        mcu.scan(clock.t)
        mcu.scan(clock.t + 20_000)
        mcu.scan(clock.t + 2_000_000)
        mcu.levels[0] = False
        mcu.scan(clock.t + 2_000_000)
        mcu.scan(clock.t + 2_020_000)
        kinds = [frame.payload["gesture"] for frame in mcu.out if frame.msg_type == 0x12]
        self.assertEqual(kinds, ["HOLD"])


class PlayTests(unittest.TestCase):
    def _engine(self):
        clock = Clock()
        engine = Engine(Store(), clock_us=lambda: clock.t)
        engine.cfg["pre_countdown_ms"] = 0
        engine.mcu.cfg["pre_countdown_ms"] = 0
        return clock, engine

    def test_guided_voice(self):
        clock, engine = self._engine()
        engine.state = "MODE_LOBBY"
        engine.mode = "GUIDED"
        engine.start("M01_VOICE")
        self.assertEqual(engine.state, "ACTIVE")
        for button_id in (13, 3, 9, 14):
            engine.sim_click(button_id)
            clock.t += 100_000
        self.assertEqual(engine.final_state, "VALID")
        self.assertIn("SIMULATED SOLUTION COMPLETE", engine.notice)
        self.assertIn("VOICE WIZARD", engine.achievements)
        self.assertEqual(engine.solutions, 1)

    def test_held_key_blocks_arm(self):
        clock, engine = self._engine()
        engine.mcu.levels[3] = True
        engine.mcu.scan(clock.t)
        engine.mcu.scan(clock.t + 20_000)
        engine.state = "MODE_LOBBY"
        engine.mode = "GUIDED"
        engine.start("M01_VOICE")
        self.assertNotEqual(engine.state, "ACTIVE")
        self.assertEqual(engine.notice, "release_keys")

    def test_deadline_accepts_late_confirm(self):
        clock, engine = self._engine()
        # Isolate the whole-round deadline from the new, earlier per-step deadline.
        engine.cfg["collapse"]["step_timeout_ms"] = 0
        engine.state = "MODE_LOBBY"
        engine.mode = "RUSH60_RANKED"
        engine.start()
        t_raw = engine.deadline_us - 5_000
        engine.mcu.levels[13] = True
        engine.mcu.scan(t_raw)
        clock.t = t_raw + 20_000
        engine.mcu.scan(clock.t)
        for frame in engine.mcu.poll(clock.t):
            engine.on_frame(frame)
        self.assertEqual(engine.score(), 100)
        clock.t = engine.deadline_us + 1_000
        engine.tick()
        self.assertEqual(engine.final_state, "VALID")
        self.assertEqual(engine.leaderboard(), [])

    def test_press_after_deadline_does_not_score(self):
        clock, engine = self._engine()
        engine.state = "MODE_LOBBY"
        engine.mode = "RUSH60_RANKED"
        engine.start()
        t_raw = engine.deadline_us + 1_000
        engine.mcu.levels[13] = True
        engine.mcu.scan(t_raw)
        clock.t = t_raw + 20_000
        engine.mcu.scan(clock.t)
        for frame in engine.mcu.poll(clock.t):
            engine.on_frame(frame)
        self.assertEqual(engine.score(), 0)

    def test_duplicate_press_scores_once(self):
        clock, engine = self._engine()
        engine.state = "MODE_LOBBY"
        engine.mode = "GUIDED"
        engine.start("M01_VOICE")
        engine.sim_click(13)
        hit = engine.store.conn.execute("SELECT boot_id, press_id, service_key, raw_t_us, confirmed_t_us, session_id, round_id, step_epoch, button_id FROM events").fetchone()
        payload = {
            "boot_id": hit["boot_id"],
            "press_id": hit["press_id"],
            "service_key": hit["service_key"],
            "raw_press_t_us": hit["raw_t_us"],
            "confirmed_t_us": hit["confirmed_t_us"],
            "session_id": hit["session_id"],
            "round_id": hit["round_id"],
            "step_epoch": hit["step_epoch"],
            "button_id": hit["button_id"],
        }
        before = engine.score()
        engine.on_frame(type("F", (), {"msg_type": BUTTON_HIT, "payload": payload, "seq": 1, "ack_required": True, "is_response": False})())
        self.assertEqual(engine.score(), before)

    def test_m07_needs_two_lambda_presses(self):
        clock, engine = self._engine()
        engine.state = "MODE_LOBBY"
        engine.mode = "GUIDED"
        engine.start("M07_EVENT_DRIVEN")
        for button_id in (5, 3):
            engine.sim_click(button_id)
            clock.t += 100_000
        mission = engine.missions["M07_EVENT_DRIVEN"]
        self.assertFalse(required_done(mission, engine.done))
        for button_id in (8, 3, 4):
            engine.sim_click(button_id)
            clock.t += 100_000
        self.assertTrue(required_done(mission, engine.done))
        self.assertEqual(engine.final_state, "VALID")

    def test_free_cases(self):
        missions = load_missions()
        partial = analyze_selection(missions, Counter({"S3": 1, "LAMBDA": 1, "REKOGNITION": 1}))
        self.assertEqual(partial["candidates"][0]["mission_id"], "M13_IMAGE_TAGS")
        self.assertEqual(partial["candidates"][0]["status"], "VALID_COMPLETE")
        partial["candidates"] = [r for r in partial["candidates"] if r["mission_id"] == "M02_VISION"]
        self.assertEqual(partial["candidates"][0]["status"], "VALID_PARTIAL")
        self.assertIn("DYNAMODB", partial["candidates"][0]["missing"])
        voice = analyze_selection(missions, Counter({"TRANSCRIBE": 1, "BEDROCK": 1, "POLLY": 1}))
        self.assertEqual(voice["candidates"][0]["mission_id"], "M01_VOICE")
        odd = analyze_selection(missions, Counter({"EC2": 1, "POLLY": 1, "SQS": 1}))
        self.assertEqual(odd["status"], "UNSUPPORTED")
        everything = Counter({mission["service"]: 1 for mission in missions for _ in [0] for mission in []})
        from reference.catalog import load_services

        everything = Counter({row["key"]: 1 for row in load_services()[0] if row["id"]})
        full = analyze_selection(missions, everything)
        self.assertLessEqual(len(full["candidates"]), 3)
        self.assertFalse(any(row["status"] == "VALID_COMPLETE" for row in full["candidates"]))
        self.assertFalse(take_role(engine_mission(), set(), "POLLY"))

    def test_ranked_board_isolates_practice(self):
        clock, engine = self._engine()
        engine.state = "MODE_LOBBY"
        engine.mode = "RUSH60_PRACTICE"
        engine.cfg["pre_countdown_ms"] = 0
        engine.start()
        for button_id in (13, 3, 9, 14):
            engine.sim_click(button_id)
            clock.t += 100_000
        self.assertEqual(engine.solutions, 1)
        self.assertIsNone(engine.final_state)
        self.assertEqual(engine.leaderboard(), [])


def engine_mission():
    return next(mission for mission in load_missions() if mission["id"] == "M01_VOICE")


if __name__ == "__main__":
    unittest.main()
