"""Local-only fixture: real HTTP keep-alive plus controlled worker/protocol failures."""

import json
import os
import signal
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httplib2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from contacts_cli.read_worker import ReadSession  # noqa: E402


class Server(ThreadingHTTPServer):
    accepted = 0
    daemon_threads = True

    def get_request(self):
        result = super().get_request()
        self.accepted += 1
        return result


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/slow-body":
            Path(self.server.marker).write_text("slow-body-entered")
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.write(b"{")
            self.wfile.flush()
            time.sleep(60)
            return
        body = json.dumps(
            {
                "connections": self.server.accepted,
                "authorization": self.headers.get("Authorization"),
                "pid": os.getpid(),
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if sys.argv[1:] == ["--no-input"]:
    time.sleep(60)
    raise SystemExit

server = Server(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
session = ReadSession(lambda **kwargs: httplib2.Http(proxy_info=None, **kwargs))
try:
    for line in sys.stdin:
        packet = json.loads(line)
        payload = packet["payload"]
        mode = payload.get("mode", "success")
        if mode == "stubborn":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if payload.get("marker"):
            Path(payload["marker"]).write_text(mode)
        if mode in {"stall", "stubborn"}:
            time.sleep(60)
        if mode == "crash":
            os._exit(7)
        if mode == "malformed":
            print("not json", flush=True)
            continue
        if mode == "partial":
            sys.stdout.write('{"id":')
            sys.stdout.flush()
            time.sleep(60)
        if mode == "stderr":
            sys.stderr.write("x" * 200000)
            sys.stderr.flush()
        if mode == "slow-body":
            server.marker = payload["marker"]
        if mode == "dns":
            session.close()

            def stalled_dns(*args, _marker=payload["marker"], **kwargs):
                Path(_marker).write_text("dns-entered")
                time.sleep(60)

            socket.getaddrinfo = stalled_dns
        if mode == "delay":
            time.sleep(0.15)
        request = {
            "action": "read",
            "method": payload.get("method", "GET"),
            "headers": {},
            "credentials": {
                "token": payload.get("token", "synthetic"),
                "expiry": "2035-01-01T00:00:00Z",
                "refresh_token": "synthetic",
                "token_uri": "https://example.invalid/token",
                "client_id": "synthetic",
                "client_secret": "synthetic",
            },
            "timeout": payload["timeout"],
            "uri": f"http://127.0.0.1:{server.server_port}/" + mode,
        }
        try:
            result = session.perform(request)
            reply = {"id": packet["id"] + (1 if mode == "wrong-id" else 0), "result": result}
        except Exception as exc:
            reply = {"id": packet["id"], "error": type(exc).__name__}
        print(json.dumps(reply), flush=True)
finally:
    session.close()
    server.shutdown()
    server.server_close()
