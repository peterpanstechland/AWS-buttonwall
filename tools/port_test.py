#!/usr/bin/env python3
"""Open the 4x4 port tester. Chrome or Edge is required for the serial port."""

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = 8092


def page() -> bytes:
    hardware = json.loads((ROOT / "config" / "hardware.json").read_text(encoding="utf-8"))
    html = Path(__file__).with_name("port_test.html").read_text(encoding="utf-8")
    html = html.replace("__HW_JSON__", json.dumps(hardware, ensure_ascii=False))
    return html.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = page()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(url)
    webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
