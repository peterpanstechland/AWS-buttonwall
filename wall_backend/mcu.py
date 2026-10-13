"""Virtual wall MCU: debounce, Kiro gestures, countdown, and AWG1 events."""

from __future__ import annotations

import itertools

from reference.awg1 import (
    ACK,
    BUTTON_HIT,
    BUTTON_RELEASE,
    COUNTDOWN_EVENT,
    COUNTDOWN_START,
    HELLO,
    INPUT_DRAINED,
    LAMP_SET,
    ROUND_ARM,
    ROUND_ARMED,
    START_GESTURE,
    STEP_ARM,
    STEP_ARMED,
    TIMER_EVENT,
    Frame,
    encode_frame,
)
from reference.catalog import load_game_config, load_hardware, load_services, mapping_crc32


class _Key:
    def __init__(self):
        self.stable_down = False
        self.candidate_down = False
        self.candidate_since = 0
        self.context = None


class VirtualMcu:
    def __init__(self, clock_us):
        self.clock_us = clock_us
        self.cfg = load_game_config()
        _, self.by_id, _ = load_services()
        self.hardware = load_hardware()
        self.crc = mapping_crc32(self.hardware)
        self.boot_id = "boot-sim"
        self.seq = itertools.count(1)
        self.keys = [_Key() for _ in range(17)]
        self.levels = [False] * 17
        self.session_id = None
        self.round_id = None
        self.epoch = 0
        self.scoring_open = False
        self.go_us = None
        self.deadline_us = None
        self.countdown_marks = []
        self.expired_sent = False
        self.drained_sent = False
        self.hits = []
        self.acked = set()
        self.gesture = {
            "down_since": None,
            "hold_sent": False,
            "pending_click_at": None,
            "first_release": None,
            "double_armed": False,
        }
        self.press_seq = 0
        self.out: list[Frame] = []
        self.hello_sent = False

    def now(self) -> int:
        return int(self.clock_us())

    def hello(self):
        if self.hello_sent:
            return
        self.hello_sent = True
        self._emit(
            HELLO,
            {
                "device_id": "wall-mcu-01",
                "boot_id": self.boot_id,
                "fw": "1.2.0",
                "proto_major": 1,
                "proto_minor": 2,
                "mapping_crc32": self.crc,
                "button_count": 17,
                "service_count": 16,
                "capabilities": {
                    "rmt_lanes": 4,
                    "start_neopixel": False,
                    "button_lamps": bool(self.hardware["lamps"]["button_lamps"]),
                    "countdown": True,
                    "raw_press_time": True,
                },
            },
            ack=True,
        )

    def set_level(self, button_id: int, down: bool, now: int | None = None):
        self.levels[button_id] = down
        self.scan(self.now() if now is None else now)

    def click(self, button_id: int, now: int | None = None):
        now = self.now() if now is None else now
        gap = self.cfg["debounce_us"]
        self.levels[button_id] = True
        self.scan(now)
        self.scan(now + gap)
        self.levels[button_id] = False
        self.scan(now + gap)
        self.scan(now + 2 * gap)

    def poll(self, now: int | None = None) -> list[Frame]:
        self.scan(self.now() if now is None else now)
        ready, self.out = self.out, []
        return ready

    def handle(self, frame: Frame) -> list[Frame]:
        payload = frame.payload
        if frame.msg_type == ACK:
            self.acked.add(payload.get("press_id"))
            self._maybe_drain()
        elif frame.msg_type == ROUND_ARM:
            released = not any(key.stable_down for key in self.keys)
            self.session_id = payload["session_id"]
            self.round_id = payload["round_id"]
            self.scoring_open = False
            self.expired_sent = False
            self.drained_sent = False
            self.hits = []
            self._emit(
                ROUND_ARMED,
                {
                    "session_id": self.session_id,
                    "round_id": self.round_id,
                    "request_id": payload["request_id"],
                    "ready": released and payload.get("mapping_crc32", self.crc) == self.crc,
                    "all_released": released,
                    "mapping_crc32": self.crc,
                    "t_us": self.now(),
                },
                ack=True,
            )
        elif frame.msg_type == STEP_ARM:
            self.epoch = payload["step_epoch"]
            self.round_id = payload.get("round_id", self.round_id)
            held = [index for index, key in enumerate(self.keys) if key.stable_down and index != 0]
            self._emit(
                STEP_ARMED,
                {
                    "session_id": payload["session_id"],
                    "round_id": self.round_id,
                    "step_epoch": self.epoch,
                    "accepted_from_us": self.now(),
                    "held_buttons": held,
                    "ready": not held,
                },
                ack=True,
            )
        elif frame.msg_type == COUNTDOWN_START:
            start = self.now()
            pre = int(payload["pre_countdown_ms"]) * 1000
            game = int(payload.get("game_duration_ms") or 0) * 1000
            self.countdown_marks = []
            if pre <= 0:
                self._open_gate(start, game)
            else:
                for index, label in enumerate(("3", "2", "1")):
                    self.countdown_marks.append((start + index * (pre // 3), label))
                self.countdown_marks.append((start + pre, "GO"))
                self._pending_game_us = game
        elif frame.msg_type == LAMP_SET:
            if not self.hardware["lamps"]["button_lamps"]:
                self._emit(ACK, {"ack_seq": frame.seq, "request_id": payload.get("request_id"), "status": "ERR_UNSUPPORTED"}, response=True)
            else:
                self._emit(ACK, {"ack_seq": frame.seq, "request_id": payload.get("request_id"), "status": "OK"}, response=True)
        elif frame.ack_required:
            self._emit(ACK, {"ack_seq": frame.seq, "request_id": payload.get("request_id"), "status": "OK"}, response=True)
        ready, self.out = self.out, []
        return ready

    def _context(self) -> dict:
        return {
            "session_id": self.session_id,
            "round_id": self.round_id,
            "step_epoch": self.epoch,
            "scoring_open": self.scoring_open,
            "go_us": self.go_us,
            "deadline_us": self.deadline_us,
        }

    def _on_press(self, button_id: int, key: _Key):
        ctx = key.context or self._context()
        if button_id == 0:
            self.gesture["down_since"] = key.candidate_since
            self.gesture["hold_sent"] = False
            self.gesture["pending_click_at"] = None
            return
        raw_t = key.candidate_since
        deadline = ctx.get("deadline_us")
        in_window = bool(ctx.get("scoring_open")) and raw_t >= (ctx.get("go_us") or 0)
        if deadline:
            in_window = in_window and raw_t < deadline
        hit = {
            "device_id": "wall-mcu-01",
            "boot_id": self.boot_id,
            "session_id": ctx.get("session_id"),
            "round_id": ctx.get("round_id"),
            "step_epoch": ctx.get("step_epoch"),
            "press_id": self._alloc_press(),
            "button_id": button_id,
            "service_key": self.by_id[button_id]["key"],
            "raw_press_t_us": raw_t,
            "confirmed_t_us": key.confirmed_t,
            "in_window": in_window,
            "mapping_version": 1,
        }
        self.hits.append(hit)
        self._emit(BUTTON_HIT, {k: v for k, v in hit.items() if k != "in_window"}, ack=True)

    def _on_release(self, button_id: int, key: _Key):
        if button_id == 0:
            if self.gesture["hold_sent"]:
                self.gesture["down_since"] = None
                self.gesture["hold_sent"] = False
                return
            if self.gesture["double_armed"]:
                self.gesture["double_armed"] = False
                self.gesture["down_since"] = None
                self._emit(START_GESTURE, {"gesture": "DOUBLE", "press_id": self._alloc_press(), "t_us": key.candidate_since}, ack=True)
                return
            self.gesture["first_release"] = key.candidate_since
            self.gesture["pending_click_at"] = key.candidate_since + self.cfg["click_window_us"]
            self.gesture["down_since"] = None
            return
        self._emit(
            BUTTON_RELEASE,
            {"button_id": button_id, "t_us": key.candidate_since},
            ack=False,
        )

    def scan(self, now: int):
        for button_id, key in enumerate(self.keys):
            down = self.levels[button_id]
            if down != key.candidate_down:
                key.candidate_down = down
                key.candidate_since = now
                key.context = self._context()
            if down != key.stable_down and now - key.candidate_since >= self.cfg["debounce_us"]:
                key.confirmed_t = now
                key.stable_down = down
                if down:
                    self._on_press(button_id, key)
                else:
                    self._on_release(button_id, key)
        self._gesture_timers(now)
        self._countdown(now)

    def _gesture_timers(self, now: int):
        gesture = self.gesture
        if gesture["down_since"] is not None and not gesture["hold_sent"]:
            if now - gesture["down_since"] >= self.cfg["hold_us"]:
                gesture["hold_sent"] = True
                gesture["pending_click_at"] = None
                gesture["double_armed"] = False
                self._emit(START_GESTURE, {"gesture": "HOLD", "press_id": self._alloc_press(), "t_us": gesture["down_since"]}, ack=True)
        if (
            self.levels[0]
            and gesture["pending_click_at"] is not None
            and gesture["first_release"] is not None
            and self.keys[0].candidate_since - gesture["first_release"] <= self.cfg["click_window_us"]
        ):
            gesture["double_armed"] = True
            gesture["pending_click_at"] = None
        if gesture["pending_click_at"] is not None and now >= gesture["pending_click_at"] and not self.levels[0]:
            gesture["pending_click_at"] = None
            self._emit(START_GESTURE, {"gesture": "CLICK", "press_id": self._alloc_press(), "t_us": now}, ack=True)

    def _countdown(self, now: int):
        pending = []
        for at, label in self.countdown_marks:
            if now < at:
                pending.append((at, label))
                continue
            if label == "GO":
                self._open_gate(at, getattr(self, "_pending_game_us", 0))
            else:
                self._emit(COUNTDOWN_EVENT, {"event": label, "t_us": at}, ack=True)
        self.countdown_marks = pending
        if self.scoring_open and self.deadline_us and now >= self.deadline_us and not self.expired_sent:
            self.expired_sent = True
            self.scoring_open = False
            self._emit(TIMER_EVENT, {"session_id": self.session_id, "round_id": self.round_id, "event": "EXPIRED", "deadline_us": self.deadline_us}, ack=True)
            self._maybe_drain()

    def _open_gate(self, t0: int, game_us: int):
        self.go_us = t0
        self.deadline_us = t0 + game_us if game_us else None
        self.scoring_open = True
        self.expired_sent = False
        self._emit(TIMER_EVENT, {"session_id": self.session_id, "round_id": self.round_id, "event": "GO", "t0_us": t0, "deadline_us": self.deadline_us}, ack=True)

    def _maybe_drain(self):
        if not self.expired_sent or self.drained_sent:
            return
        unacked = [hit for hit in self.hits if hit["in_window"] and hit["press_id"] not in self.acked]
        if unacked:
            return
        self.drained_sent = True
        window_hits = [hit for hit in self.hits if hit["in_window"]]
        final_press = window_hits[-1]["press_id"] if window_hits else 0
        self._emit(
            INPUT_DRAINED,
            {
                "session_id": self.session_id,
                "round_id": self.round_id,
                "deadline_us": self.deadline_us,
                "final_press_id": final_press,
                "input_event_count": len(window_hits),
                "all_hit_events_acked": True,
            },
            ack=True,
        )

    def _alloc_press(self) -> int:
        self.press_seq += 1
        return self.press_seq

    def _emit(self, msg_type: int, payload: dict, ack: bool = False, response: bool = False):
        seq = next(self.seq)
        self.out.append(Frame(msg_type, payload, seq, ack, response))
        encode_frame(msg_type, payload, seq, ack, response)
