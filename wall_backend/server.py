"""Localhost HMI server. The browser never sends a score."""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from wall_backend.engine import Engine
from wall_backend.store import Store
from wall_backend.ws import WebSocketClient

ROOT = Path(__file__).resolve().parents[1]
HMI = ROOT / "hmi"
ENGINE: Engine | None = None
CLIENTS: list[WebSocketClient] = []
ADMINS: set[str] = set()
ACTIONS: dict[str, dict] = {}
LOGIN_FAILS = 0
STATE_LOCK = threading.RLock()


def broadcast(engine: Engine):
    kinds = engine.drain_ui()
    if not kinds:
        return
    message = json.dumps(
        {
            "type": kinds[-1],
            "server_seq": engine.server_seq,
            "state_revision": engine.state_revision,
            "session_id": engine.session_id,
            "round_id": engine.round_id,
            "step_epoch": engine.epoch,
            "snapshot": engine.snapshot(),
        },
        ensure_ascii=False,
    )
    dead = []
    for client in CLIENTS:
        try:
            client.send_text(message)
        except OSError:
            dead.append(client)
    for client in dead:
        CLIENTS.remove(client)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if self.headers.get("Upgrade", "").lower() == "websocket":
            return self._get()
        with STATE_LOCK:
            self._get()

    def _get(self):
        parsed = urlparse(self.path)
        if parsed.path in {"/ws", "/ws/events"} and self.headers.get("Upgrade", "").lower() == "websocket":
            client = WebSocketClient(self)
            CLIENTS.append(client)
            client.serve(lambda: None)
            return
        if parsed.path == "/api/health":
            self._json(
                {
                    "ok": True,
                    "device_online": bool(ENGINE.mcu and ENGINE.mcu.hello_sent),
                    "boot_id": ENGINE.boot_id,
                    "db_ok": True,
                    "device_mode": "mock" if ENGINE.sim else "serial",
                    "state": ENGINE.state,
                    "state_revision": ENGINE.state_revision,
                }
            )
            return
        if parsed.path == "/api/snapshot":
            ENGINE.tick()
            broadcast(ENGINE)
            self._json(ENGINE.snapshot())
            return
        if parsed.path == "/api/content/services":
            self._json(ENGINE.services)
            return
        if parsed.path == "/api/content/missions":
            visible = []
            for mission in ENGINE.missions.values():
                visible.append(
                    {
                        "id": mission["id"],
                        "title": mission["title"],
                        "story": mission["story"],
                        "io": mission["io"],
                        "ranked": mission["ranked"],
                    }
                )
            self._json(visible)
            return
        if parsed.path == "/api/leaderboard":
            self._json(ENGINE.leaderboard())
            return
        if parsed.path == "/api/ui":
            from reference.catalog import load_ui_strings

            self._json(load_ui_strings())
            return
        if parsed.path == "/api/preview":
            from wall_backend.graph import project_graph
            mission = next(iter(ENGINE.missions.values()))
            self._json(project_graph(mission, {n["node_id"] for n in mission["nodes"]}))
            return
        rel = "index.html" if parsed.path == "/" else parsed.path.lstrip("/")
        path = (HMI / rel).resolve()
        if not path.is_relative_to(HMI.resolve()) or not path.is_file():
            self.send_error(404)
            return
        kind = "text/html; charset=utf-8"
        if path.suffix == ".css":
            kind = "text/css; charset=utf-8"
        elif path.suffix == ".js":
            kind = "text/javascript; charset=utf-8"
        elif path.suffix == ".svg":
            kind = "image/svg+xml"
        elif path.suffix == ".png":
            kind = "image/png"
        elif path.suffix == ".json":
            kind = "application/json"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        with STATE_LOCK:
            self._post()

    def _post(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._json({"error": "BAD_JSON"}, 400)
            return
        if "score" in body or "solutions_completed" in body:
            self._json({"error": "score is computed by the backend"}, 400)
            return
        action_id = body.get("client_action_id")
        if action_id and action_id in ACTIONS:
            self._json(ACTIONS[action_id])
            return
        path = parsed.path
        if path == "/api/admin/test-panel" and ENGINE.state == "ACTIVE" and ENGINE.mode == "RUSH60_RANKED":
            self._json({"error": "ranked active"}, 409)
            return
        if path == "/api/mode/select":
            ENGINE.select_mode(body.get("mode"))
        elif path == "/api/game/start":
            ENGINE.start(body.get("mission_id"))
        elif path == "/api/sim/press":
            ENGINE.sim_click(int(body["button_id"]))
        elif path == "/api/sim/level":
            ENGINE.sim_level(int(body["button_id"]), bool(body.get("down")))
        elif path == "/api/free/analyze":
            ENGINE.analyze()
        elif path == "/api/free/undo":
            ENGINE.undo()
        elif path == "/api/game/leave":
            ENGINE.leave()
        elif path == "/api/free/confirm":
            ENGINE.confirm_candidate(body.get("mission_id"))
        elif path == "/api/free/instance":
            ENGINE.add_instance(body.get("service", ""))
        elif path == "/api/game/forfeit":
            ENGINE.forfeit()
        elif path == "/api/player/alias":
            ENGINE.set_alias(str(body.get("alias", "")))
        elif path == "/api/admin/login":
            global LOGIN_FAILS
            pin = os.environ.get("WALL_OPERATOR_PIN", "")
            if LOGIN_FAILS >= 5:
                self._json({"error": "locked"}, 429)
                return
            if pin and body.get("pin") == pin:
                token = os.urandom(8).hex()
                ADMINS.add(token)
                LOGIN_FAILS = 0
                self._json({"token": token})
                return
            LOGIN_FAILS += 1
            self._json({"error": "denied"}, 403)
            return
        elif path == "/api/admin/leaderboard/clear":
            if self.headers.get("X-Admin-Token") not in ADMINS:
                self._json({"error": "denied"}, 403)
                return
            if body.get("confirm") != "CLEAR":
                self._json({"error": "confirm"}, 400)
                return
            ENGINE.store.clear_leaderboard()
        else:
            self._json({"error": "not found"}, 404)
            return
        ENGINE.tick()
        broadcast(ENGINE)
        payload = ENGINE.snapshot()
        payload["client_action_id"] = action_id
        if action_id:
            ACTIONS[action_id] = payload
        self._json(payload)

    def _json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(host="127.0.0.1", port=8080, sim=True):
    global ENGINE
    ENGINE = Engine(Store(ROOT / "wall.db"), sim=sim)
    httpd = ThreadingHTTPServer((host, port), Handler)
    def tick_game():
        while True:
            with STATE_LOCK:
                ENGINE.tick()
                broadcast(ENGINE)
            time.sleep(0.02)
    threading.Thread(target=tick_game, daemon=True).start()
    print(f"wall-backend http://{host}:{port}/")
    httpd.serve_forever()
