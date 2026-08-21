"""Shared-password authentication for the hosted ReEDS-Proxy dashboard."""

from __future__ import annotations

import hashlib
import hmac
import html
import os
import time
from urllib.parse import urlsplit

from tornado.web import RequestHandler


COOKIE_NAME = "reedssurr_auth"
ADMIN_COOKIE_NAME = "reedssurr_admin_auth"
DEFAULT_DESTINATION = "/reeds_proxy"
DEFAULT_MAX_SESSION_SECONDS = 2 * 60 * 60
MAX_SESSION_SECONDS = int(
    os.environ.get("REEDS_PROXY_MAX_SESSION_SECONDS", DEFAULT_MAX_SESSION_SECONDS)
)
MAX_COOKIE_AGE_DAYS = MAX_SESSION_SECONDS / (24 * 60 * 60)
login_url = "/login"
logout_url = "/logout"


def _password_hash() -> str:
    value = os.environ.get("REEDSSURR_PASSWORD_HASH", "").strip()
    if not value:
        raise RuntimeError("REEDSSURR_PASSWORD_HASH is required")
    return value


def _verify_hash(candidate: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        if iterations < 100_000:
            return False
        salt = bytes.fromhex(salt_text)
        expected = bytes.fromhex(digest_text)
        actual = hashlib.pbkdf2_hmac(
            "sha256", candidate.encode("utf-8"), salt, iterations, dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def _verify_password(candidate: str) -> bool:
    return _verify_hash(candidate, _password_hash())


def verify_admin_password(candidate: str) -> bool:
    """Verify the separate admin password without exposing its hash."""
    encoded_hash = os.environ.get("REEDSSURR_ADMIN_PASSWORD_HASH", "").strip()
    return bool(encoded_hash) and _verify_hash(candidate, encoded_hash)


def _safe_destination(value: str | None) -> str:
    if not value:
        return DEFAULT_DESTINATION
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or value.startswith("//"):
        return DEFAULT_DESTINATION
    return value


def create_session_value(identity: str) -> str:
    """Create a cookie value that carries the server-issued login time."""
    return f"{identity}:{int(time.time())}"


def _decode_session_value(value: bytes | None, expected_identity: str) -> int | None:
    if value is None:
        return None
    try:
        identity, issued_at_text = value.decode("utf-8").rsplit(":", 1)
        issued_at = int(issued_at_text)
    except (UnicodeDecodeError, ValueError):
        return None

    now = int(time.time())
    if identity != expected_identity or issued_at > now:
        return None
    if now - issued_at >= MAX_SESSION_SECONDS:
        return None
    return issued_at


def _session_started_at(
    request_handler: RequestHandler,
    cookie_name: str,
    expected_identity: str,
) -> int | None:
    value = request_handler.get_secure_cookie(
        cookie_name,
        max_age_days=MAX_COOKIE_AGE_DAYS,
    )
    return _decode_session_value(value, expected_identity)


def get_user(request_handler: RequestHandler) -> str | None:
    issued_at = _session_started_at(request_handler, COOKIE_NAME, "shared-user")
    return "shared-user" if issued_at is not None else None


def get_user_session_started_at(request_handler: RequestHandler) -> int | None:
    """Return the authenticated dashboard session's login timestamp."""
    return _session_started_at(request_handler, COOKIE_NAME, "shared-user")


def get_admin_user(request_handler: RequestHandler) -> str | None:
    """Return the admin session identity when its signed cookie is valid."""
    issued_at = _session_started_at(request_handler, ADMIN_COOKIE_NAME, "admin")
    return "admin" if issued_at is not None else None


class _BaseHandler(RequestHandler):
    def set_default_headers(self) -> None:
        self.set_header("Cache-Control", "no-store")
        self.set_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.set_header("Referrer-Policy", "no-referrer")
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("X-Frame-Options", "DENY")


class LoginHandler(_BaseHandler):
    def get(self) -> None:
        if get_user(self):
            self.redirect(_safe_destination(self.get_argument("next", default=None)))
            return
        self._render_login()

    def post(self) -> None:
        destination = _safe_destination(self.get_argument("next", default=None))
        password = self.get_body_argument("password", default="")
        if not _verify_password(password):
            # A short delay makes rapid online guessing less attractive.
            time.sleep(0.35)
            self.set_status(401)
            self._render_login(destination=destination, error="Incorrect password. Please try again.")
            return

        secure_cookie = os.environ.get("REEDSSURR_SECURE_COOKIES", "true").lower() not in {
            "0",
            "false",
            "no",
        }
        self.set_secure_cookie(
            COOKIE_NAME,
            create_session_value("shared-user"),
            expires_days=MAX_COOKIE_AGE_DAYS,
            httponly=True,
            secure=secure_cookie,
            samesite="Lax",
        )
        self.redirect(destination)

    def _render_login(self, destination: str | None = None, error: str = "") -> None:
        destination = _safe_destination(
            destination if destination is not None else self.get_argument("next", default=None)
        )
        error_html = f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ""
        page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ReEDS-Proxy Login</title>
  <style>
    :root {{ color-scheme: light; font-family: Arial, sans-serif; }}
    body {{ background:#f3f6f8; margin:0; min-height:100vh; display:grid; place-items:center; color:#1f2933; }}
    main {{ width:min(390px,calc(100% - 40px)); background:white; padding:32px; border-radius:12px; box-shadow:0 8px 28px #15324322; }}
    h1 {{ font-size:1.45rem; margin:0 0 8px; }}
    p {{ color:#52606d; line-height:1.45; }}
    label {{ display:block; font-weight:600; margin:24px 0 8px; }}
    input[type=password] {{ box-sizing:border-box; width:100%; padding:12px; border:1px solid #9fb3c8; border-radius:7px; font-size:1rem; }}
    button {{ width:100%; margin-top:18px; padding:12px; border:0; border-radius:7px; background:#1769aa; color:white; font-size:1rem; font-weight:700; cursor:pointer; }}
    .error {{ color:#b42318; font-weight:600; }}
  </style>
</head>
<body>
  <main>
    <h1>ReEDS-Proxy</h1>
    <p>Enter the shared project password.</p>
    {error_html}
    <form method="post" action="/login">
      {self.xsrf_form_html()}
      <input type="hidden" name="next" value="{html.escape(destination, quote=True)}">
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
      <button type="submit">Open ReEDS-Proxy</button>
    </form>
  </main>
</body>
</html>"""
        self.set_header("Content-Type", "text/html; charset=UTF-8")
        self.write(page)


class LogoutHandler(_BaseHandler):
    def get(self) -> None:
        self.clear_cookie(COOKIE_NAME)
        self.redirect(login_url)


class SessionStatusHandler(_BaseHandler):
    """Expose the signed dashboard session deadline to the dashboard page."""

    def get(self) -> None:
        issued_at = get_user_session_started_at(self)
        if issued_at is None:
            self.set_status(401)
            self.write({"authenticated": False})
            return

        self.write(
            {
                "authenticated": True,
                "expires_at_milliseconds": (issued_at + MAX_SESSION_SECONDS) * 1000,
            }
        )
