"""HTTP 服务。

只做协议解析与转发：路由与业务决定都在 ``dispatch`` 里，网络层不夹带逻辑。
线程按请求逐个处理，保证同样是确定性行为。
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from .api import Response, dispatch
from .views import render_index


class ConsoleServer(HTTPServer):
    def __init__(self, address: tuple[str, int], line) -> None:
        self.line = line
        super().__init__(address, ControlHandler)

    def endpoint(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"


class ControlHandler(BaseHTTPRequestHandler):
    server_version = "bwms-console/1.0"

    def _respond(self, response: Response) -> None:
        payload = response.body()
        self.send_response(response.status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _line(self):
        return self.server.line

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定名
        parsed = urlparse(self.path)
        if parsed.path == "/":
            page = render_index(self._line()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
        self._respond(
            dispatch(self._line(), "GET", parsed.path, parse_qs(parsed.query))
        )

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定名
        parsed = urlparse(self.path)
        self._respond(
            dispatch(
                self._line(),
                "POST",
                parsed.path,
                parse_qs(parsed.query),
                self._read_body(),
            )
        )

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - 基类签名
        """默认日志会写真实时间，这里静音，避免运行输出不确定。"""


def build_server(line, host: str | None = None, port: int | None = None) -> ConsoleServer:
    spec = line.settings.console
    return ConsoleServer((host or spec.host, int(spec.port if port is None else port)), line)
