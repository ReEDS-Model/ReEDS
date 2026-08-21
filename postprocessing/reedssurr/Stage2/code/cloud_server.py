"""Launch the hosted ReEDS-Proxy dashboard and admin portal."""

from __future__ import annotations

import os
from pathlib import Path

from bokeh.command.util import build_single_handler_application
from bokeh.server.auth_provider import AuthModule
from bokeh.server.server import Server

from admin_portal import ADMIN_ROUTES
from shared_password_auth import SessionStatusHandler


_HERE = Path(__file__).resolve().parent


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    websocket_origin = os.environ.get("BOKEH_ALLOW_WS_ORIGIN", f"localhost:{port}")
    dashboard = build_single_handler_application(str(_HERE / "reeds_proxy.py"))
    auth_provider = AuthModule(_HERE / "shared_password_auth.py")
    server = Server(
        {"/reeds_proxy": dashboard},
        address="0.0.0.0",
        port=port,
        allow_websocket_origin=[websocket_origin],
        auth_provider=auth_provider,
        cookie_secret=os.environ["BOKEH_COOKIE_SECRET"],
        extra_patterns=[*ADMIN_ROUTES, (r"/session/status", SessionStatusHandler)],
        xsrf_cookies=True,
        use_xheaders=True,
        keep_alive_milliseconds=30000,
    )
    server.start()
    server.io_loop.start()


if __name__ == "__main__":
    main()
