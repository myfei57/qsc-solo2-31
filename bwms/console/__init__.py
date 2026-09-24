"""控制台：请求分发、页面渲染与 HTTP 服务。"""

from __future__ import annotations

from .api import Response, dispatch
from .server import ConsoleServer, build_server
from .views import render_index, render_status_lines

__all__ = [
    "Response",
    "dispatch",
    "ConsoleServer",
    "build_server",
    "render_index",
    "render_status_lines",
]
