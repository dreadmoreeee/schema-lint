import pathlib
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AVOID = {8765, 8737, 8787}


def _free_port() -> int:
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port not in AVOID:
            return port


class Site:
    """A local web site: routes maps path -> (status, content_type, body)."""

    def __init__(self, routes: dict) -> None:
        self.routes = routes
        self.requests: list[tuple[float, str, str, str]] = []  # (time, method, path, user-agent)
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                site.requests.append((time.monotonic(), "GET", self.path, self.headers.get("User-Agent", "")))
                status, ctype, body = site.routes.get(self.path, (404, "text/plain", "not found"))
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.port = _free_port()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.port}"

    def paths(self) -> list[str]:
        return [p for _, _, p, _ in self.requests]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def site():
    made = []

    def make(routes: dict) -> Site:
        s = Site(routes)
        made.append(s)
        return s

    yield make
    for s in made:
        s.close()


@pytest.fixture
def unused_port() -> int:
    return _free_port()
