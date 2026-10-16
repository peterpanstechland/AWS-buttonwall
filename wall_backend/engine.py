"""Single writer for a play session. Scores come only from MCU hit events."""

from __future__ import annotations

import time
import uuid
import sqlite3
import random
from collections import Counter

from reference.awg1 import (
    ACK,
    BUTTON_HIT,
    COUNTDOWN_EVENT,
    HELLO,
    INPUT_DRAINED,
    ROUND_ARMED,
    START_GESTURE,
    STEP_ARMED,
    TIMER_EVENT,
    Frame,
)
from reference.catalog import load_game_config, load_hardware, load_missions, load_services, mapping_crc32, pack_hash
from reference.rules import analyze_selection, frontier, required_done, take_role
from reference.scoring import combo_bonus, display_score
from wall_backend.mcu import VirtualMcu
from wall_backend.store import Store
from wall_backend.graph import project_graph


class Engine:
    def __init__(self, store: Store, clock_us=None, sim: bool = True):
        self.store = store
        self.ui_settings = self.store.ui_settings()
        self.clock_us = clock_us or (lambda: time.monotonic() * 1_000_000)
        self.sim = sim
        self.bridge = None
        self.cfg = load_game_config()
        self.services, self.by_id, self.by_key = load_services()
        self.missions = {mission["id"]: mission for mission in load_missions()}
        self.crc = mapping_crc32()
        self.pack_hash = pack_hash()
        self.mcu = VirtualMcu(self.clock_us) if sim else None
        self.ui = []
        self.visit_plays = 0
        self.visit_seen = set()
        self.handoff_until = None
        self._reset_idle()

    def _reset_idle(self):
        if self.mcu:
            self.mcu.reset_session()
        self.state = "IDLE"
        self.mode = None
        self.session_id = None
        self.round_id = None
        self.epoch = 0
        self.mission_id = None
        self.mission_ids = []
        self.mission_index = 0
        self.done = set()
        self.streak = 0
        self.raw_score = 0
        self.invalid_hits = 0
        self.solutions = 0
        self.go_us = None
        self.deadline_us = None
        self.last_completed_t_ms = None
        self.trajectory = []
        self.selected = Counter()
        self.paused = False
        self.forfeit_pending = False
        self.expired = False
        self.drain_payload = None
        self.seen = set()
        self.window_hits = []
        self.final_state = None
        self.alias = None
        self.boot_id = self.mcu.boot_id if self.mcu else None
        self.candidates = []
        self.confirmed_mission = None
        self.achievements = []
        self.mission_types_done = set()
        self.notice = ""
        self.failure = None
        self.step_deadline_us = None
        self.pause_started_us = None
        self.last_completed_graph = None
        self.finalized_us = None
        self.menu_mission_index = 0
        self.menu_random = True
        self.play_started_us = None
        self.free_review = False
        self.candidate_index = 0
        self.selection_history = []
        self.panels = {service["id"]: "OFF" for service in self.services if service["id"]}
        self.link_lost = False
        self.state_revision = getattr(self, "state_revision", 0)
        self.server_seq = getattr(self, "server_seq", 0)
        self.last_activity_us = self.now()
        self.navigation_since_us = self.now()
        self._last_pushed_state = self.state
        self.settings_return_state = None
        self.settings_error = None

    def now(self) -> int:
        return int(self.clock_us())

    def _activity(self):
        # Called only for participant input, never for HMI polling or device ticks.
        self.last_activity_us = self.now()

    def _idle_return_remaining_ms(self):
        settings = self.cfg.get("inactivity", {})
        duration = 0
        if self.state == 'IDLE' and self.visit_plays:
            duration = settings.get('menu_ms', 90000)
        if self.state in {"MODE_LOBBY", "MISSION_SELECT", "SETTINGS"}:
            duration = settings.get("menu_ms", 0)
        elif self.state == "PREPARE" and not str(self.mode).startswith("RUSH"):
            duration = settings.get("menu_ms", 0)
        elif self.state == "ACTIVE" and self.mode == "FREE":
            duration = settings.get("free_ms", 0)
        elif self.state == "ACTIVE" and self.mode == "GUIDED" and self.paused:
            duration = settings.get("paused_ms", 0)
        elif self.state in {"RESULT", "INTERRUPTED"}:
            duration = settings.get("result_ms", 0)
            if self.state == 'RESULT' and (self.last_completed_graph or self.confirmed_mission):
                duration = max(duration, settings.get('explanation_result_ms', 60000))
        if not duration:
            return None
        # A result gets its full reading time even when the last input was long ago.
        since = max(self.last_activity_us, self.finalized_us or 0)
        return max(0, (since + duration * 1000 - self.now() + 999) // 1000)

    def tick(self):
        if self.bridge:
            self.bridge.poll()
            if not self.bridge.online or not self.bridge.ready:
                return
        self._tick_core()
        if self.bridge:
            self.bridge.lights()

    def _tick_core(self):
        if self.handoff_until is not None:
            if self.now() >= self.handoff_until:
                self.visit_plays = 0
                self.visit_seen.clear()
                self.handoff_until = None
                self._reset_idle()
                self._push('device.state')
            return
        if self.mcu:
            if self.state == "IDLE" and not self.mcu.hello_sent:
                self.mcu.hello()
            for frame in self.mcu.poll(self.now()):
                self.on_frame(frame)
        # Poll/debounce eligible hits first; never let a browser animation decide a result.
        if (self.state == "ACTIVE" and not self.paused and self.step_deadline_us
                and self.now() >= self.step_deadline_us + self.cfg["debounce_us"]):
            self._collapse("STEP_TIMEOUT")
        if self.state == 'ACTIVE' and self.mode == 'FREE' and self.play_started_us is not None and self.now() - self.play_started_us >= self.cfg['visitor']['free_duration_ms'] * 1000:
            self.notice = 'FREE_TIME_UP'
            self._finalize('EXPLORATION')
        if self._idle_return_remaining_ms() == 0:
            if self.visit_plays < self.cfg['visitor']['max_plays']:
                self.visit_plays = 0
                self.visit_seen.clear()
            self.home()

    def _handoff(self):
        self._reset_idle()
        self.state = 'VISIT_DONE'
        self.handoff_until = self.now() + self.cfg['visitor']['handoff_ms'] * 1000
        self._push('game.visit_done')

    def on_frame(self, frame: Frame):
        if frame.msg_type == HELLO:
            minor = frame.payload.get("proto_minor", 0)
            crc = frame.payload.get("mapping_crc32")
            self.boot_id = frame.payload.get("boot_id")
            if self.state in {"ACTIVE", "SETTLING"} and self.mode == "RUSH60_RANKED" and self.boot_id:
                self._interrupt("boot changed")
            if minor < 2 or crc != self.crc:
                self.state = "OPERATOR"
                self.notice = "MAP_MISMATCH" if crc != self.crc else "VERSION_MISMATCH"
            self._push("device.state")
            return
        if frame.msg_type == START_GESTURE:
            self._gesture(frame.payload.get("gesture"))
            return
        if frame.msg_type == BUTTON_HIT:
            self._hit(frame.payload)
            return
        if frame.msg_type == ROUND_ARMED:
            self._armed(frame.payload)
            return
        if frame.msg_type == STEP_ARMED:
            self.epoch = frame.payload["step_epoch"]
            self._push("game.step_updated")
            return
        if frame.msg_type == COUNTDOWN_EVENT:
            if (self.state not in {"PREPARE", "COUNTDOWN"}
                    or frame.payload.get("session_id") != self.session_id):
                return
            self.state = "COUNTDOWN"
            self.notice = frame.payload.get("event", "")
            self._push("game.countdown")
            return
        if frame.msg_type == TIMER_EVENT:
            self._timer(frame.payload)
            return
        if frame.msg_type == INPUT_DRAINED:
            self._drained(frame.payload)
            return
        if frame.msg_type == ACK and frame.payload.get("status") == "ERR_UNSUPPORTED":
            self.notice = "ERR_UNSUPPORTED"

    def sim_click(self, button_id: int):
        if self.bridge or not self.sim or not self.mcu:
            raise RuntimeError("simulator input is off")
        self.mcu.click(button_id, self.now())
        self.tick()

    def sim_level(self, button_id: int, down: bool):
        if self.bridge or not self.sim or not self.mcu:
            raise RuntimeError("simulator input is off")
        self.mcu.set_level(button_id, down, self.now())
        self.tick()

    def select_mode(self, mode: str):
        if self.bridge and not self.bridge.ready:
            return
        if self.state != "MODE_LOBBY":
            return
        if mode not in {"GUIDED", "FREE", "RUSH60_RANKED", "RUSH60_PRACTICE"}:
            return
        self._activity()
        self.mode = mode
        self._push("game.lobby")

    def start(self, mission_id: str | None = None):
        if self.bridge and not self.bridge.ready:
            return
        if self.state not in {"MODE_LOBBY", "MISSION_SELECT", "IDLE"} or not self.mode:
            return
        if self.visit_plays >= self.cfg['visitor']['max_plays']:
            self._handoff()
            return
        if self.mode == 'GUIDED' and mission_id is not None and mission_id not in self.missions:
            return
        self.visit_plays += 1
        self.play_started_us = self.now()
        self._activity()
        self.session_id = uuid.uuid4().hex[:12]
        self.alias = self.alias or f"BUILDER-{self.store.next_alias():03d}"
        self.solutions = 0
        self.raw_score = 0
        self.invalid_hits = 0
        self.streak = 0
        self.trajectory = []
        self.final_state = None
        self.seen = set()
        self.window_hits = []
        self.candidates = []
        self.confirmed_mission = None
        if self.mode == "FREE":
            self.mission_ids = []
            self.mission_id = None
            self.selected = Counter()
            self._begin_round(None)
            return
        if self.mode in {"RUSH60_RANKED", "RUSH60_PRACTICE"}:
            self.mission_ids = list(self.cfg["pack"]["mission_ids"])
        else:
            pool = [mid for mid in self.missions if mid not in self.visit_seen] or list(self.missions)
            chosen = mission_id or random.choice(pool)
            self.visit_seen.add(chosen)
            self.mission_ids = [chosen]
        self.mission_index = 0
        self._begin_round(self.mission_ids[0])

    def _begin_round(self, mission_id: str | None):
        self.mission_id = mission_id
        self.round_id = uuid.uuid4().hex[:8]
        self.done = set()
        self.epoch = 0
        self.state = "PREPARE"
        self.panels = {service["id"]: "OFF" for service in self.services if service["id"]}
        if not self.mcu:
            return
        frames = self.mcu.handle(
            Frame(
                0x34,
                {
                    "session_id": self.session_id,
                    "round_id": self.round_id,
                    "request_id": f"arm-{self.round_id}",
                    "mode": self.mode,
                    "require_all_released": True,
                    "mapping_crc32": self.crc,
                    "pack_id": self.cfg["pack"]["pack_id"],
                    "duration_ms": self.cfg["rush_duration_ms"] if self.mode.startswith("RUSH") else 0,
                },
                next(self.mcu.seq),
                True,
                False,
            )
        )
        for frame in frames:
            self.on_frame(frame)

    def _armed(self, payload: dict):
        if not payload.get("ready"):
            self.notice = "release_keys"
            self._push("game.step_updated")
            return
        self._arm_step(1)

    def _arm_step(self, epoch: int):
        if not self.mcu:
            self.epoch = epoch
            return
        frames = self.mcu.handle(
            Frame(
                0x36,
                {
                    "session_id": self.session_id,
                    "round_id": self.round_id,
                    "request_id": f"step-{epoch}",
                    "step_epoch": epoch,
                    "require_release": True,
                },
                next(self.mcu.seq),
                True,
                False,
            )
        )
        for frame in frames:
            self.on_frame(frame)
        if self.epoch == 1 and self.go_us is None and self.mode != "FREE":
            pre = 0 if self.mode == "FREE" else self.cfg["pre_countdown_ms"]
            game = self.cfg["rush_duration_ms"] if str(self.mode).startswith("RUSH") else 0
            for frame in self.mcu.handle(
                Frame(
                    0x30,
                    {
                        "session_id": self.session_id,
                        "round_id": self.round_id,
                        "request_id": f"timer-{self.session_id}",
                        "pre_countdown_ms": pre,
                        "game_duration_ms": game,
                        "policy": "INVALIDATE_ON_USB_LOSS",
                    },
                    next(self.mcu.seq),
                    True,
                    False,
                )
            ):
                self.on_frame(frame)
        elif self.mode == "FREE":
            self.state = "ACTIVE"
            self._paint()
        self._paint()

    def _timer(self, payload: dict):
        if (self.final_state or not self.session_id
                or payload.get("session_id") != self.session_id):
            return
        if payload.get("event") == "GO":
            self.go_us = payload["t0_us"]
            self.deadline_us = payload.get("deadline_us")
            self.state = "ACTIVE"
            self.notice = "GO"
            self._reset_step_timer()
            self._paint()
            self._push("game.countdown")
        elif payload.get("event") == "EXPIRED":
            self.expired = True
            self.state = "SETTLING"
            self._push("game.countdown")
            self._try_finalize_rush()

    def _gesture(self, kind: str):
        if self.state == 'VISIT_DONE':
            return
        if kind not in {"CLICK", "DOUBLE", "HOLD"}:
            return
        self._activity()
        if self.state == "SETTINGS":
            self.close_settings()
            return
        if self.state == "IDLE" and kind == "HOLD":
            self.open_settings()
            return
        if kind in {"CLICK", "DOUBLE"} and self.state == "IDLE":
            self.state = "MODE_LOBBY"
            self.mode = self.mode or "GUIDED"
            self._push("game.lobby")
            return
        if self.state == "MODE_LOBBY" and kind in {"CLICK", "DOUBLE"}:
            if self.mode == "GUIDED":
                self.state = "MISSION_SELECT"
                self._push("game.lobby")
            else:
                self.start()
            return
        if self.state == "MISSION_SELECT":
            if kind in {"CLICK", "DOUBLE"}:
                self.start(None if self.menu_random else self.cfg["pack"]["mission_ids"][self.menu_mission_index])
            elif kind == "HOLD":
                self.state = "MODE_LOBBY"
            self._push("game.lobby")
            return
        if self.state == "MODE_LOBBY" and kind == "HOLD":
            self._reset_idle()
            self._push("device.state")
            return
        if self.state == "ACTIVE" and self.mode == "FREE" and kind == "CLICK":
            if self.free_review and self.candidates:
                self.candidate_index = (self.candidate_index + 1) % len(self.candidates)
                self._push("game.step_updated")
            else:
                self.analyze()
            return
        if self.state == "ACTIVE" and self.mode == "FREE" and kind == "DOUBLE":
            if self.free_review and self.candidates:
                self.confirm_candidate(self.candidates[self.candidate_index]["mission_id"])
            else:
                self.undo()
            return
        if self.state == "ACTIVE" and self.mode == "FREE" and kind == "HOLD" and self.free_review:
            self._dismiss_candidates()
            self._push("game.step_updated")
            return
        if self.state == "ACTIVE" and self.mode in {"FREE", "GUIDED"} and kind == "HOLD":
            self.leave()
            return
        if self.state == "ACTIVE" and self.mode == "GUIDED" and kind == "CLICK":
            self.paused = not self.paused
            if self.paused:
                self.pause_started_us = self.now()
            elif self.step_deadline_us and self.pause_started_us is not None:
                self.step_deadline_us += self.now() - self.pause_started_us
                self.pause_started_us = None
            self._push("game.step_updated")
            return
        if self.state == "ACTIVE" and str(self.mode).startswith("RUSH"):
            if self.forfeit_pending and kind == "DOUBLE":
                self._interrupt("forfeit")
            elif kind == "CLICK":
                self.forfeit_pending = False
                self._push("game.step_updated")
            elif kind == "HOLD":
                self.forfeit_pending = True
                self.notice = "forfeit?"
                self._push("game.step_updated")
            return
        if self.state in {"PREPARE", "COUNTDOWN"} and kind == "HOLD":
            self.leave()
            return
        if self.state in {"RESULT", "INTERRUPTED"}:
            if self.visit_plays >= self.cfg['visitor']['max_plays']:
                self._handoff()
                return
            mode, mission_id = self.mode, self.mission_id
            if kind == "CLICK" and mode == "GUIDED" and not self.failure and self.final_state == "VALID":
                mission_id = None
            self._reset_idle()
            if kind != "HOLD":
                self.state = "MODE_LOBBY"
                self.mode = mode or "GUIDED"
                if kind == "CLICK":
                    self.start(mission_id)
            self._push("game.lobby")
            return
        if self.state == "OPERATOR" and kind == "HOLD":
            self._reset_idle()
            self._push("device.state")

    def open_settings(self) -> bool:
        if self.state not in {"IDLE", "MODE_LOBBY", "MISSION_SELECT", "RESULT", "INTERRUPTED"}:
            return False
        self.settings_return_state = self.state
        self.settings_error = None
        self.state = "SETTINGS"
        self._activity()
        self._push("ui.settings")
        return True

    def close_settings(self):
        if self.state != "SETTINGS":
            return
        self.state = self.settings_return_state or "IDLE"
        self.settings_return_state = None
        self.settings_error = None
        self._activity()
        self._push("ui.settings")

    def update_ui_settings(self, changes: dict, replay=False):
        result_replay = (self.state == 'RESULT' and replay and changes == {'voice_enabled': True}
                         and (self.last_completed_graph or self.confirmed_mission))
        if self.state != "SETTINGS" and not result_replay:
            raise RuntimeError("SETTINGS_NOT_OPEN")
        allowed = {"language", "voice_enabled", "volume", "reduced_motion"}
        if not isinstance(changes, dict) or not changes or set(changes) - allowed:
            raise ValueError("INVALID_SETTINGS")
        for name, value in changes.items():
            if name == "language" and (type(value) is not str or value not in {"zh", "en"}):
                raise ValueError("INVALID_LANGUAGE")
            if name in {"voice_enabled", "reduced_motion"} and type(value) is not bool:
                raise ValueError("INVALID_BOOLEAN")
            if name == "volume" and (type(value) is not int or not 0 <= value <= 100):
                raise ValueError("INVALID_VOLUME")
        self._activity()
        try:
            saved = self.store.save_ui_settings(changes, replay=replay)
        except (sqlite3.Error, OSError):
            self.settings_error = "SETTINGS_SAVE_FAILED"
            self._push("ui.settings")
            raise
        self.ui_settings = saved
        self.settings_error = None
        self._push("ui.settings")

    def _navigation_hit(self, payload: dict) -> str:
        button = self.by_id.get(payload.get("button_id"))
        if not button or not button["id"] or button["key"] != payload.get("service_key"):
            return "INVALID_NAVIGATION_BUTTON"
        self._activity()
        cell = next((cell for cell in self.navigation()["cells"] if cell["button_id"] == button["id"]), None)
        if not cell:
            return "UNMAPPED_NAVIGATION"
        action = cell["action"]
        if action.startswith("mode:"):
            self.select_mode(action.split(":", 1)[1])
        elif action.startswith("mission:"):
            self.menu_random = False
            self.menu_mission_index = self.cfg["pack"]["mission_ids"].index(action.split(":", 1)[1])
            self._push("game.lobby")
        elif action == 'random':
            self.menu_random = True
            self._push('game.lobby')
        elif action == "settings":
            self.open_settings()
        elif action == "home":
            self.home()
        elif action == "back":
            if self.state == "SETTINGS":
                self.close_settings()
            elif self.state == "MISSION_SELECT":
                self.state = "MODE_LOBBY"
                self._push("game.lobby")
        else:
            prefs = self.ui_settings
            changes = {
                "language:zh": {"language": "zh"},
                "language:en": {"language": "en"},
                "voice_toggle": {"voice_enabled": not prefs["voice_enabled"]},
                "replay": {"voice_enabled": True},
                "volume_down": {"volume": max(0, prefs["volume"] - 20)},
                "volume_up": {"volume": min(100, prefs["volume"] + 20)},
                "motion_toggle": {"reduced_motion": not prefs["reduced_motion"]},
            }.get(action)
            if changes:
                try:
                    self.update_ui_settings(changes, replay=action == "replay")
                except (sqlite3.Error, OSError):
                    return "SETTINGS_SAVE_FAILED"
        return "NAVIGATION"

    def navigation(self) -> dict:
        """A display and future-LED plan; this does not transmit to physical hardware."""
        by_slot = {button["slot"]: button for button in self.services if button["id"]}
        blue, yellow, purple, white = [41, 90, 240], [255, 221, 0], [139, 73, 255], [255, 255, 255]
        cells = []
        label = lambda zh, en: {"zh": zh, "en": en}
        def cell(slot, action, text, selected=False, color=None, effect=None):
            button = by_slot[slot]
            cells.append({"button_id": button["id"], "slot": slot, "key": button["key"],
                          "action": action, "label": text, "selected": selected,
                          "color": color if color is not None else yellow if selected else blue,
                          "effect": effect or ("pulse" if selected else "breathe")})
        cfg = self.cfg["navigation"]
        kiro = {"label": label("Kiro 确认", "Kiro confirms"),
                "click": label("确认当前选择", "Confirm selection"),
                "double": label("确认当前选择", "Confirm selection"),
                "hold": label("返回", "Back"), "rgb": False, "lamp": "constant"}
        if self.state == "IDLE":
            cell(cfg["settings_slot"], "settings", label("设置", "Settings"), color=purple, effect="steady")
            kiro.update(label=label("Kiro 开始", "Kiro starts"), click=label("开始游戏", "Start game"),
                        double=label("开始游戏", "Start game"), hold=label("打开设置", "Open settings"))
        elif self.state == "MODE_LOBBY":
            titles = {"GUIDED": label("引导构建", "Guided build"), "RUSH60_RANKED": label("60 秒竞速", "60-second rush"), "FREE": label("自由探索", "Free exploration")}
            for slot, mode in cfg["mode_slots"].items():
                cell(slot, "mode:" + mode, titles[mode], self.mode == mode)
            cell(cfg["back_slot"], "home", label("回首页", "Home"), color=white, effect="steady")
            cell(cfg["settings_slot"], "settings", label("设置", "Settings"), color=purple, effect="steady")
        elif self.state == "MISSION_SELECT":
            for index, (slot, mission_id) in enumerate(zip(cfg["mission_slots"], self.cfg["pack"]["mission_ids"])):
                title = self.missions[mission_id]["title"]
                if mission_id == "M08_ML":
                    title = {**title, "en": "ML Inference"}
                cell(slot, "mission:" + mission_id, title, not self.menu_random and index == self.menu_mission_index)
            cell('C1', 'random', label('随机方案', 'Random workflow'), self.menu_random)
            cell(cfg["back_slot"], "back", label("返回模式", "Back to modes"), color=white, effect="steady")
            cell(cfg["settings_slot"], "settings", label("设置", "Settings"), color=purple, effect="steady")
        elif self.state == "SETTINGS":
            prefs = self.ui_settings
            cell("A1", "language:zh", label("中文", "Chinese"), prefs["language"] == "zh")
            cell("A2", "language:en", label("English", "English"), prefs["language"] == "en")
            cell("B1", "voice_toggle", label("语音开关", "Voice on / off"), prefs["voice_enabled"])
            cell("B2", "replay", label("重听设置说明", "Replay settings help"))
            cell("A3", "volume_down", label("音量 −20", "Volume −20"))
            cell("A4", "volume_up", label("音量 +20", "Volume +20"))
            cell("B3", "motion_toggle", label("减少动态", "Reduce motion"), prefs["reduced_motion"])
            cell("C3", "back", label("返回", "Back"), color=white, effect="steady")
            cell("D4", "home", label("回首页", "Home"), color=white, effect="steady")
            kiro.update(label=label("Kiro 返回", "Kiro returns"), click=label("返回上一页", "Return to previous screen"),
                        double=label("返回上一页", "Return to previous screen"), hold=label("返回上一页", "Return to previous screen"))
        elif self.state in {"RESULT", "INTERRUPTED"}:
            cell(cfg["back_slot"], "home", label("回首页", "Home"), color=white, effect="steady")
            cell(cfg["settings_slot"], "settings", label("设置", "Settings"), color=purple, effect="steady")
            if self.state == 'RESULT' and (self.last_completed_graph or self.confirmed_mission):
                cell('B2', 'replay', label('再听方案解说', 'Replay explanation'), color=blue, effect='breathe')
            next_mission = self.mode == "GUIDED" and not self.failure and self.final_state == "VALID"
            kiro.update(label=label("Kiro 继续", "Kiro continues"), click=label("下一场景" if next_mission else "再玩一次", "Next scenario" if next_mission else "Play again"),
                        double=label("选择模式", "Choose mode"), hold=label("回首页", "Home"))
            if self.visit_plays >= self.cfg['visitor']['max_plays']:
                kiro.update(label=label('Kiro 结束体验', 'Kiro finishes visit'), click=label('结束体验', 'Finish visit'), double=label('结束体验', 'Finish visit'), hold=label('结束体验', 'Finish visit'))
        elif self.state == "ACTIVE":
            for button in self.services:
                if not button["id"]:
                    continue
                color, effect = self._panel_effect(self.panels[button["id"]])
                cell(button["slot"], "service", label(button["display_name_cn_event"], button["official_en"]),
                     self.panels[button["id"]] in {"ACCEPTED", "SELECTED_FREE"}, color, effect)
            if self.mode == "GUIDED":
                kiro.update(label=label("Kiro 暂停 / 继续", "Kiro pauses / resumes"), click=label("继续" if self.paused else "暂停", "Resume" if self.paused else "Pause"), double=label("无操作", "No action"), hold=label("返回模式", "Back to modes"))
            elif self.mode == "FREE":
                kiro.update(label=label("Kiro 分析 / 确认", "Kiro analyzes / confirms"), click=label("下个方案" if self.free_review else "分析组合", "Next workflow" if self.free_review else "Analyze"), double=label("确认完整方案" if self.free_review else "撤销", "Confirm complete workflow" if self.free_review else "Undo"), hold=label("返回编辑" if self.free_review else "返回模式", "Back to editing" if self.free_review else "Back to modes"))
            else:
                kiro.update(label=label("Kiro 结束确认", "Kiro end-run confirmation"), click=label("取消结束" if self.forfeit_pending else "继续游戏", "Cancel forfeit" if self.forfeit_pending else "Keep playing"), double=label("确认结束" if self.forfeit_pending else "无操作", "Confirm end" if self.forfeit_pending else "No action"), hold=label("打开结束确认", "Ask to end run"))
        else:
            back = label("回首页", "Home") if self.state == "OPERATOR" else label("返回模式", "Back to modes") if self.state in {"PREPARE", "COUNTDOWN"} else label("等待", "Wait")
            kiro.update(label=label("请稍候", "Please wait"), click=label("等待", "Wait"), double=label("等待", "Wait"), hold=back)
        return {"context": self.state, "cells": cells, "kiro": kiro}

    @staticmethod
    def _panel_effect(state):
        return {"TARGET_HINT": ([255, 221, 0], "pulse"), "ACCEPTED": ([44, 210, 120], "steady"),
                "SELECTED_FREE": ([255, 221, 0], "steady"), "AVAILABLE": ([41, 90, 240], "breathe"),
                "REJECTED": ([240, 50, 65], "pulse")}.get(state, ([0, 0, 0], "off"))

    def light_plan(self, navigation):
        active = {cell["button_id"]: cell for cell in navigation["cells"]}
        cells = []
        for button in self.services:
            if not button["id"]:
                continue
            source = active.get(button["id"])
            cells.append({"button_id": button["id"], "slot": button["slot"], "key": button["key"],
                          "action": "none", "label": {"zh": "", "en": ""}, "selected": False,
                          "color": [0, 0, 0], "effect": "off", **(source or {}),
                          "panel_state": self.panels[button["id"]] if self.state == "ACTIVE" else "NAVIGATION" if source else "OFF"})
        return {"simulated": not bool(self.bridge), "hardware_applied": bool(self.bridge and self.bridge.online and self.bridge.applied and self.bridge.lamps_ok), "brightness_cap": self.cfg["brightness_cap"], "cells": cells,
                "kiro": {"rgb": False, "lamp": "constant"}}

    def _hit(self, payload: dict):
        identity = (payload.get("boot_id"), payload.get("press_id"))
        if identity in self.seen:
            return
        self.seen.add(identity)
        self.store.persist_event(payload, "PENDING")
        if self.state in {"IDLE", "MODE_LOBBY", "MISSION_SELECT", "SETTINGS", "RESULT", "INTERRUPTED"}:
            valid_context = (
                isinstance(payload.get("raw_press_t_us"), int)
                and payload["raw_press_t_us"] >= self.navigation_since_us
                and payload.get("boot_id") == self.boot_id
                and payload.get("session_id") == self.session_id
                and payload.get("round_id") == self.round_id
            )
            if valid_context:
                disposition = self._navigation_hit(payload)
            else:
                disposition = "STALE_NAVIGATION"
            self.store.mark_event(identity, disposition)
            self._ack_hit(payload)
            return
        if payload.get("session_id") != self.session_id or self.state not in {"ACTIVE", "SETTLING"}:
            self.store.mark_event(identity, "REJECTED_SESSION")
            self._ack_hit(payload)
            return
        if payload.get("round_id") != self.round_id or payload.get("step_epoch") != self.epoch:
            self.store.mark_event(identity, "IGNORED_TRANSITION")
            self.notice = "wait_step"
            self._ack_hit(payload)
            self._push("game.input_feedback")
            return
        raw_t = payload["raw_press_t_us"]
        if self.go_us is not None and (raw_t < self.go_us or (self.deadline_us and raw_t >= self.deadline_us)):
            self.store.mark_event(identity, "OUTSIDE_WINDOW")
            self._ack_hit(payload)
            return
        self._activity()
        self.window_hits.append(payload)
        if self.mode == "FREE":
            self._toggle(payload["service_key"], payload["button_id"])
            self.store.mark_event(identity, "TOGGLED")
            self._ack_hit(payload)
            return
        if self.paused:
            self.store.mark_event(identity, "PAUSED")
            self._ack_hit(payload)
            return
        if self.step_deadline_us and raw_t >= self.step_deadline_us:
            self.store.mark_event(identity, "STEP_TIMEOUT")
            self._collapse("STEP_TIMEOUT")
            self._ack_hit(payload)
            return
        mission = self.missions[self.mission_id]
        node = take_role(mission, self.done, payload["service_key"])
        if node is None:
            self._invalid(identity, payload["button_id"])
            if self.cfg.get("collapse", {}).get("wrong_service"):
                self._collapse("WRONG_SERVICE", payload["service_key"])
            self._ack_hit(payload)
            return
        self.done.add(node["node_id"])
        if node["required"]:
            self._reset_step_timer()
            self.streak += 1
            self.raw_score += self.cfg["node_points"] + combo_bonus(self.streak, self.cfg["combo_step"], self.cfg["combo_cap"])
            self.store.mark_event(identity, "VALID_ROLE", node["node_id"])
        else:
            self.raw_score += self.cfg["ranked_optional_points"]
            self.store.mark_event(identity, "OPTIONAL", node["node_id"])
        self.panels[payload["button_id"]] = "ACCEPTED"
        self._ack_hit(payload)
        if required_done(mission, self.done):
            self._complete_solution()
        else:
            self.epoch += 1
            self._arm_step(self.epoch)
            self._paint()
        self._push("game.step_updated")

    def _toggle(self, service: str, button_id: int):
        # Two instances are selectable even when no current example uses both.
        maximum = 2
        self.selection_history.append((service, self.selected[service]))
        self.selected[service] = (self.selected[service] + 1) % (maximum + 1)
        self.panels[button_id] = "SELECTED_FREE" if self.selected[service] else "OFF"
        self._dismiss_candidates()
        self._push("game.step_updated")

    def _dismiss_candidates(self):
        self.candidates = []
        self.candidate_index = 0
        self.free_review = False

    def _invalid(self, identity, button_id: int):
        self.streak = 0
        self.invalid_hits += 1
        self.raw_score -= self.cfg["error_points"]
        self.panels[button_id] = "REJECTED"
        self.store.mark_event(identity, "INVALID_ROLE")
        self._push("game.input_feedback")

    def _complete_solution(self):
        self.raw_score += self.cfg["complete_points"]
        self.solutions += 1
        if self.go_us is not None:
            self.last_completed_t_ms = max(0, (self.now() - self.go_us) // 1000)
            self.trajectory.append({"t_ms": self.last_completed_t_ms, "solutions": self.solutions})
        self.mission_types_done.add(self.mission_id)
        self._grant_achievements()
        self.notice = "SIMULATED SOLUTION COMPLETE"
        self.last_completed_graph = project_graph(self.missions[self.mission_id], self.done)
        self._push("game.mission_completed")
        if str(self.mode).startswith("RUSH"):
            self.mission_index += 1
            if self.mission_index >= len(self.mission_ids):
                self.notice = "PACK_CLEARED"
                self._finalize("VALID")
                return
            self.mission_id = self.mission_ids[self.mission_index]
            self.round_id = uuid.uuid4().hex[:8]
            self.done = set()
            self.panels = {service["id"]: "OFF" for service in self.services if service["id"]}
            self._reset_step_timer()
            self._arm_step(1)
            self._paint()
            return
        self._finalize("VALID")

    def _drained(self, payload: dict):
        self.drain_payload = payload
        self._try_finalize_rush()

    def _try_finalize_rush(self):
        if self.final_state or not self.expired or not self.drain_payload:
            return
        if self.drain_payload.get("input_event_count") != len(self.window_hits):
            self._interrupt("drain mismatch")
            return
        if (self.cfg.get("collapse", {}).get("round_timeout") and self.mission_id
                and not required_done(self.missions[self.mission_id], self.done)):
            self._collapse("ROUND_TIMEOUT")
        else:
            self._finalize("VALID")

    def _reset_step_timer(self):
        duration = self.cfg.get("collapse", {}).get("step_timeout_ms", 0)
        self.step_deadline_us = self.now() + duration * 1000 if duration and self.mode != "FREE" else None

    def _collapse(self, reason: str, wrong_service: str | None = None):
        if self.final_state or not self.mission_id:
            return
        missing = [n["node_id"] for n in self.missions[self.mission_id]["nodes"]
                   if n["required"] and n["node_id"] not in self.done]
        self.failure = {"reason": reason, "missing_nodes": missing, "wrong_service": wrong_service}
        self.notice = reason
        # A rules-based loss is a validly played session, separate from device interruption.
        self._finalize("VALID")

    def _ack_hit(self, payload: dict):
        if not self.mcu:
            return
        for frame in self.mcu.handle(Frame(ACK, {"ack_seq": 0, "press_id": payload["press_id"], "status": "OK"}, 1, False, True)):
            self.on_frame(frame)

    def analyze(self):
        if self.mode != "FREE" or self.state != "ACTIVE":
            return
        self._activity()
        result = analyze_selection(list(self.missions.values()), self.selected)
        self.candidates = result["candidates"]
        self.candidate_index = 0
        self.free_review = bool(self.candidates)
        self.notice = result["status"]
        self._push("game.step_updated")
        return result

    def confirm_candidate(self, mission_id: str):
        if self.mode != "FREE" or self.state != "ACTIVE":
            return
        match = next((row for row in self.candidates if row["mission_id"] == mission_id and row["status"] == "VALID_COMPLETE"), None)
        if not match:
            return
        self._activity()
        self.confirmed_mission = mission_id
        self.mission_id = mission_id
        self.solutions = 1
        self.mission_types_done.add(mission_id)
        self._grant_achievements()
        self.notice = "SIMULATED SOLUTION COMPLETE"
        self._finalize("VALID")

    def leave(self):
        if self.state == 'VISIT_DONE':
            return
        if self.visit_plays >= self.cfg['visitor']['max_plays']:
            self._handoff()
            return
        if self.mode == "RUSH60_RANKED" and self.state in {"ACTIVE", "COUNTDOWN", "SETTLING", "PREPARE"} and not self.final_state:
            self._interrupt("leave")
        self._reset_idle()
        self.state = "MODE_LOBBY"
        self.mode = "GUIDED"
        self._push("game.lobby")

    def home(self) -> bool:
        if self.state == 'VISIT_DONE':
            return False
        # A home shortcut must not bypass the explicit timed-game forfeit flow.
        if (str(self.mode).startswith("RUSH") and not self.final_state
                and self.state in {"PREPARE", "COUNTDOWN", "ACTIVE", "SETTLING"}):
            return False
        if self.visit_plays >= self.cfg['visitor']['max_plays']:
            self._handoff()
            return True
        self._reset_idle()
        self._push("device.state")
        return True

    def undo(self):
        if self.mode != "FREE" or self.state != "ACTIVE":
            return
        self._activity()
        if self.selection_history:
            service, previous = self.selection_history.pop()
            self.selected[service] = previous
            button_id = self.by_key[service]["id"]
            self.panels[button_id] = "SELECTED_FREE" if previous else "OFF"
            self._dismiss_candidates()
            self._push("game.step_updated")

    def add_instance(self, service: str):
        if self.mode != "FREE" or self.state != "ACTIVE" or service not in self.by_key or service == "KIRO_START":
            return
        self._activity()
        self.selected[service] += 1
        self.selection_history.append((service, self.selected[service] - 1))
        self._dismiss_candidates()
        self._push("game.step_updated")

    def forfeit(self):
        if self.forfeit_pending and self.mode == "RUSH60_RANKED":
            self._interrupt("forfeit")

    def set_alias(self, alias: str):
        cleaned = "".join(ch for ch in alias if ch.isprintable() and ch not in "<>&")
        points = list(cleaned)
        self._activity()
        self.alias = "".join(points[:16]) or self.alias
        self._push("device.state")

    def _grant_achievements(self):
        earned = set(self.achievements)
        if self.mission_types_done:
            earned.add("FIRST BUILD")
        if "M05_SERVERLESS_WEB" in self.mission_types_done or "M09_PROTECTED_WEB" in self.mission_types_done:
            earned.add("SERVERLESS MAKER")
        if "M04_AGENT" in self.mission_types_done:
            earned.add("AGENT BUILDER")
        if "M01_VOICE" in self.mission_types_done:
            earned.add("VOICE WIZARD")
        if "M03_IOT" in self.mission_types_done:
            earned.add("IoT CONNECTOR")
        if len(self.mission_types_done) >= 5:
            earned.add("ARCHITECT EXPLORER")
        self.achievements = sorted(earned)

    def _interrupt(self, reason: str):
        if self.final_state:
            return
        self.finalized_us = self.now()
        self.final_state = "INTERRUPTED"
        self.state = "INTERRUPTED"
        self.notice = reason
        self.link_lost = reason == "link"
        self.store.finish_session(self._row(), ranked=False)
        self._push("game.interrupted")

    def _finalize(self, status: str):
        if self.final_state:
            return
        self.finalized_us = self.now()
        self.final_state = status
        self.state = "RESULT"
        ranked = self.mode == "RUSH60_RANKED" and status == "VALID" and not self.sim
        self.store.finish_session(self._row(), ranked=ranked)
        self._push("game.result_finalized")
        if ranked:
            self._push("leaderboard.updated")

    def _paint(self):
        if self.mode == "FREE" or not self.mission_id:
            return
        mission = self.missions[self.mission_id]
        ready = {node["service"] for node in frontier(mission, self.done) if node["required"]}
        for service in self.services:
            if not service["id"]:
                continue
            if self.panels.get(service["id"]) == "ACCEPTED":
                continue
            if self.mode == "GUIDED" and service["key"] in ready:
                self.panels[service["id"]] = "TARGET_HINT"
            elif self.mode == "RUSH60_PRACTICE" and service["key"] in ready:
                self.panels[service["id"]] = "TARGET_HINT"
            else:
                self.panels[service["id"]] = "AVAILABLE" if self.state == "ACTIVE" else "OFF"

    def _push(self, kind: str):
        if self.state != self._last_pushed_state:
            self.navigation_since_us = self.now()
            self._last_pushed_state = self.state
        self.state_revision += 1
        self.server_seq += 1
        self.ui.append(kind)

    def drain_ui(self) -> list[str]:
        ready, self.ui = self.ui, []
        return ready

    def score(self) -> int:
        return display_score(self.raw_score, self.cfg["score_floor"])

    def _row(self) -> dict:
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "state": self.final_state or self.state,
            "pack_id": self.cfg["pack"]["pack_id"],
            "pack_hash": self.pack_hash,
            "ruleset_version": self.cfg["ruleset_version"],
            "scoring_version": self.cfg["scoring_version"],
            "participant_class": self.cfg["participant_class"],
            "boot_id": self.boot_id,
            "alias": self.alias,
            "solutions_completed": self.solutions,
            "score": self.score(),
            "invalid_hits": self.invalid_hits,
            "last_completed_t_ms": self.last_completed_t_ms,
            "trajectory": self.trajectory,
            "failure": self.failure,
        }

    def snapshot(self) -> dict:
        navigation = self.navigation()
        mission = self.missions.get(self.mission_id) if self.mission_id else None
        hint = None
        if mission and self.mode != "RUSH60_RANKED":
            node = next((item for item in frontier(mission, self.done) if item["required"]), None)
            hint = node["role"] if node else None
        elif mission and self.mode == "RUSH60_RANKED":
            node = next((item for item in frontier(mission, self.done) if item["required"]), None)
            hint = node["role"] if node else None
        remaining = None
        if self.mode == 'FREE' and self.play_started_us is not None:
            remaining = max(0, self.cfg['visitor']['free_duration_ms'] - ((self.finalized_us or self.now()) - self.play_started_us) // 1000)
        if self.deadline_us and self.go_us:
            remaining = max(0, (self.deadline_us - (self.finalized_us or self.now())) // 1000)
        graph = None
        if mission:
            graph = project_graph(mission, self.done, self.selected if self.mode == "FREE" else None,
                                  self.mode == "RUSH60_RANKED" and not self.final_state, self.failure)
        step_now = self.finalized_us or (self.pause_started_us if self.paused and self.pause_started_us is not None else self.now())
        return {
            "state": self.state,
            "visit_plays": self.visit_plays,
            "visit_limit": self.cfg['visitor']['max_plays'],
            "visit_remaining": max(0, self.cfg['visitor']['max_plays'] - self.visit_plays),
            "handoff_remaining_ms": max(0, (self.handoff_until - self.now()) // 1000) if self.handoff_until is not None else None,
            "ui_settings": dict(self.ui_settings),
            "settings_error": self.settings_error,
            "settings_return_state": self.settings_return_state,
            "navigation": navigation,
            "light_plan": self.light_plan(navigation),
            "mode": self.mode,
            "menu_mission_id": None if self.menu_random else self.cfg["pack"]["mission_ids"][self.menu_mission_index],
            "free_review": self.free_review,
            "focused_candidate_id": self.candidates[self.candidate_index]["mission_id"] if self.candidates else None,
            "session_id": self.session_id,
            "round_id": self.round_id,
            "step_epoch": self.epoch,
            "mission": None
            if not mission
            else {"id": mission["id"], "title": mission["title"], "story": mission["story"], "io": mission["io"]},
            "role_hint": hint,
            "graph": graph,
            "failure": self.failure,
            "step_remaining_ms": max(0, (self.step_deadline_us - step_now) // 1000) if self.step_deadline_us else None,
            "step_duration_ms": self.cfg.get("collapse", {}).get("step_timeout_ms", 0),
            "last_completed_graph": self.last_completed_graph,
            "candidate_graphs": {row["mission_id"]: project_graph(self.missions[row["mission_id"]], set(), self.selected)
                                 for row in self.candidates},
            "panels": self.panels,
            "score": self.score(),
            "solutions_completed": self.solutions,
            "invalid_hits": self.invalid_hits,
            "streak": self.streak,
            "remaining_ms": remaining,
            "notice": self.notice,
            "alias": self.alias,
            "candidates": self.candidates,
            "achievements": self.achievements,
            "selected": {key: value for key, value in self.selected.items() if value},
            "final_state": self.final_state,
            "sim_input": self.sim and not self.bridge,
            "demo": self.sim,
            "device_mode": "bw_serial" if self.bridge else "mock" if self.sim else "serial",
            "physical_link": self.bridge.status() if self.bridge else None,
            "state_revision": self.state_revision,
            "server_seq": self.server_seq,
            "done_nodes": sorted(self.done),
            "ghost": None if self.sim else self.store.top_ghost(self.cfg["pack"]["pack_id"], self.pack_hash),
            "mapping_crc32": self.crc,
            "pack_id": self.cfg["pack"]["pack_id"],
            "pack_hash": self.pack_hash,
            "banner": {"zh": "模拟架构构建完成", "en": "SIMULATED SOLUTION COMPLETE"},
            "forfeit_pending": self.forfeit_pending,
            "paused": self.paused,
            "idle_return_remaining_ms": self._idle_return_remaining_ms(),
            "grid": load_hardware()["display_grid"],
            "buttons": [
                {"id": button["id"], "key": button["key"], "slot": button["slot"]}
                for button in load_hardware()["buttons"]
            ],
        }

    def leaderboard(self):
        return self.store.leaderboard(self.cfg["pack"]["pack_id"], self.pack_hash)
