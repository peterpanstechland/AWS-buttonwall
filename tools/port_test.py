#!/usr/bin/env python3
"""4x4 port tester. The page asks this process to open the COM port."""

import json
import threading
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import serial
import serial.tools.list_ports

ROOT = Path(__file__).resolve().parents[1]
PORT = 8092
ESPRESSIF_VID = 0x303A

lock = threading.Lock()
lines = deque(maxlen=200)
serial_port = None
stop_read = threading.Event()


def page() -> bytes:
    hardware = json.loads((ROOT / "config" / "hardware.json").read_text(encoding="utf-8"))
    html = Path(__file__).with_name("port_test.html").read_text(encoding="utf-8")
    html = html.replace("__HW_JSON__", json.dumps(hardware, ensure_ascii=False))
    return html.encode("utf-8")


def port_list():
    found = []
    for item in serial.tools.list_ports.comports():
        found.append({
            "device": item.device,
            "description": item.description or "",
            "vid": item.vid,
        })
    found.sort(key=lambda item: (item["vid"] != ESPRESSIF_VID, item["device"]))
    return found


def reader(port):
    buf = b""
    while not stop_read.is_set():
        try:
            chunk = port.read(256)
        except serial.SerialException:
            break
        if not chunk:
            continue
        buf += chunk
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            text = raw.decode("utf-8", "replace").strip()
            if text:
                with lock:
                    lines.append(text)


def close_port():
    global serial_port
    stop_read.set()
    with lock:
        port = serial_port
        serial_port = None
    if port is not None:
        try:
            port.close()
        except serial.SerialException:
            pass


def open_port(name):
    global serial_port
    close_port()
    stop_read.clear()
    port = serial.Serial()
    port.port = name
    port.baudrate = 115200
    port.timeout = 0.05
    port.write_timeout = 1
    port.dtr = False
    port.rts = False
    port.open()
    port.dtr = False
    port.rts = False
    with lock:
        serial_port = port
        lines.clear()
    threading.Thread(target=reader, args=(port,), daemon=True).start()
    port.write(b"BW PING\n")


def send_text(text):
    with lock:
        port = serial_port
    if port is None:
        raise RuntimeError("串口还没打开")
    port.write((text.strip() + "\n").encode("utf-8"))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/ports":
            self._json(port_list())
            return
        if self.path == "/api/lines":
            with lock:
                pending = list(lines)
                lines.clear()
            self._json(pending)
            return
        if self.path.split("?", 1)[0] != "/":
            self.send_error(404)
            return
        body = page()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._json({"error": "请求不是 JSON"}, 400)
            return
        try:
            if self.path == "/api/open":
                open_port(payload["port"])
                self._json({"ok": True})
                return
            if self.path == "/api/send":
                send_text(payload["text"])
                self._json({"ok": True})
                return
        except (OSError, serial.SerialException, RuntimeError, KeyError) as exc:
            self._json({"error": str(exc)}, 400)
            return
        self.send_error(404)

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(url, flush=True)
    webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
