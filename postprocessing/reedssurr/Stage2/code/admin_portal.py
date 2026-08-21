"""Password-protected admin portal and download handlers for ReEDS-Proxy."""

from __future__ import annotations

import asyncio
import html
import mimetypes
import os
import tarfile
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from tornado.web import Finish, HTTPError, RequestHandler

from shared_password_auth import (
    ADMIN_COOKIE_NAME,
    MAX_COOKIE_AGE_DAYS,
    create_session_value,
    get_admin_user,
    verify_admin_password,
)


_STAGE_ROOT = Path(__file__).resolve().parent.parent
_MODELS_ROOT = Path(os.environ.get("REEDSSURR_MODELS_DIR", "/models"))
_DOWNLOADS_ROOT = Path(os.environ.get("REEDSSURR_ADMIN_DOWNLOADS_DIR", "/app/admin-downloads"))
_TEXT_SUFFIXES = {".md", ".ps1", ".py", ".sh", ".txt", ".yaml", ".yml"}
_CHUNK_SIZE = 1024 * 1024


def _safe_destination(value: str | None) -> str:
    if not value:
        return "/admin"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or value.startswith("//"):
        return "/admin"
    return value


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def _resolve_file(root: Path, relative_path: str) -> Path:
    root = root.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPError(404) from exc
    if not candidate.is_file():
        raise HTTPError(404)
    return candidate


def _source_files() -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    for area in ("code", "data_processing", "deploy/gcp"):
        root = _STAGE_ROOT / area
        if not root.is_dir():
            continue
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.suffix.lower() in _TEXT_SUFFIXES or path.name in {"Dockerfile", ".gcloudignore"}:
                files.append((path.relative_to(_STAGE_ROOT).as_posix(), path))
    return files


def _model_files() -> list[tuple[str, Path]]:
    if not _MODELS_ROOT.is_dir():
        return []
    return [
        (path.relative_to(_MODELS_ROOT).as_posix(), path)
        for path in sorted(_MODELS_ROOT.rglob("*.joblib"))
        if path.is_file()
    ]


def _input_files() -> list[tuple[str, Path]]:
    root = _STAGE_ROOT / "inputs"
    if not root.is_dir():
        return []
    return [
        (path.relative_to(root).as_posix(), path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


class _AdminBaseHandler(RequestHandler):
    def set_default_headers(self) -> None:
        self.set_header("Cache-Control", "no-store")
        self.set_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.set_header("Referrer-Policy", "no-referrer")
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("X-Frame-Options", "DENY")

    def require_admin(self) -> None:
        if not get_admin_user(self):
            destination = self.request.uri
            self.redirect(f"/admin/login?{urlencode({'next': destination})}")
            raise Finish()


class AdminLoginHandler(_AdminBaseHandler):
    def get(self) -> None:
        destination = _safe_destination(self.get_argument("next", default=None))
        if get_admin_user(self):
            self.redirect(destination)
            return
        self._render(destination)

    def post(self) -> None:
        destination = _safe_destination(self.get_body_argument("next", default=None))
        password = self.get_body_argument("password", default="")
        if not verify_admin_password(password):
            time.sleep(0.35)
            self.set_status(401)
            self._render(destination, "Incorrect admin password. Please try again.")
            return
        secure_cookie = os.environ.get("REEDSSURR_SECURE_COOKIES", "true").lower() not in {
            "0", "false", "no",
        }
        self.set_secure_cookie(
            ADMIN_COOKIE_NAME,
            create_session_value("admin"),
            expires_days=MAX_COOKIE_AGE_DAYS,
            httponly=True,
            secure=secure_cookie,
            samesite="Strict",
        )
        self.redirect(destination)

    def _render(self, destination: str, error: str = "") -> None:
        error_html = f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ""
        self.set_header("Content-Type", "text/html; charset=UTF-8")
        self.write(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ReEDS-Proxy Admin Login</title><style>
:root {{ color-scheme:light;font-family:Arial,sans-serif }}
body {{ background:#f3f6f8;margin:0;min-height:100vh;display:grid;place-items:center;color:#1f2933 }}
main {{ width:min(410px,calc(100% - 40px));background:#fff;padding:32px;border-radius:12px;box-shadow:0 8px 28px #15324322 }}
h1 {{ font-size:1.45rem;margin:0 0 8px }} p {{ color:#52606d;line-height:1.45 }}
label {{ display:block;font-weight:600;margin:24px 0 8px }} input {{ box-sizing:border-box;width:100%;padding:12px;border:1px solid #9fb3c8;border-radius:7px;font-size:1rem }}
button {{ width:100%;margin-top:18px;padding:12px;border:0;border-radius:7px;background:#1769aa;color:#fff;font-size:1rem;font-weight:700;cursor:pointer }}
.error {{ color:#b42318;font-weight:600 }}
</style></head><body><main><h1>ReEDS-Proxy Admin Portal</h1>
<p>Enter the admin password to review and download project resources.</p>{error_html}
<form method="post" action="/admin/login">{self.xsrf_form_html()}
<input type="hidden" name="next" value="{html.escape(destination, quote=True)}">
<label for="password">Admin password</label><input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
<button type="submit">Open Admin Portal</button></form></main></body></html>""")


class AdminLogoutHandler(_AdminBaseHandler):
    def get(self) -> None:
        self.clear_cookie(ADMIN_COOKIE_NAME)
        self.redirect("/admin/login")


class AdminPortalHandler(_AdminBaseHandler):
    def get(self) -> None:
        self.require_admin()
        source_rows = []
        for relative, path in _source_files():
            query = urlencode({"path": relative})
            source_rows.append(
                f'<tr><td><a href="/admin/code?{query}">{html.escape(relative)}</a></td>'
                f'<td>{_format_bytes(path.stat().st_size)}</td></tr>'
            )
        model_rows = []
        for relative, path in _model_files():
            query = urlencode({"path": relative})
            model_rows.append(
                f'<tr><td>{html.escape(relative)}</td><td>{_format_bytes(path.stat().st_size)}</td>'
                f'<td><a class="small" href="/admin/download/model?{query}">Download</a></td></tr>'
            )
        if not model_rows:
            model_rows.append('<tr><td colspan="3">No .joblib files are currently available.</td></tr>')
        input_rows = []
        for relative, path in _input_files():
            query = urlencode({"path": relative})
            input_rows.append(
                f'<tr><td>{html.escape(relative)}</td><td>{_format_bytes(path.stat().st_size)}</td>'
                f'<td><a class="small" href="/admin/download/input?{query}">Download</a></td></tr>'
            )
        self.set_header("Content-Type", "text/html; charset=UTF-8")
        self.write(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ReEDS-Proxy Admin Portal</title><style>
:root {{ color-scheme:light;font-family:Arial,sans-serif }} body {{ margin:0;background:#f4f7f9;color:#1f2933 }}
header {{ background:#153243;color:#fff;padding:20px max(24px,calc((100% - 1180px)/2)) }} header h1 {{ margin:0;font-size:1.55rem }}
nav {{ margin-top:10px }} nav a {{ color:#d9efff;margin-right:18px }} main {{ max-width:1180px;margin:24px auto;padding:0 20px 40px }}
section {{ background:#fff;border:1px solid #d9e2ec;border-radius:10px;padding:22px;margin-bottom:20px }} h2 {{ margin-top:0 }}
.actions {{ display:flex;gap:12px;flex-wrap:wrap;margin:14px 0 }} .button,.small {{ display:inline-block;background:#1769aa;color:#fff;text-decoration:none;border-radius:6px;padding:10px 14px;font-weight:700 }}
.small {{ padding:6px 10px;font-size:.9rem }} table {{ width:100%;border-collapse:collapse }} th,td {{ text-align:left;padding:9px;border-bottom:1px solid #e4e7eb;vertical-align:top }}
th {{ background:#f5f7fa }} code {{ overflow-wrap:anywhere }} .note {{ color:#52606d }}
</style></head><body><header><h1>ReEDS-Proxy Admin Portal</h1><nav><a href="/reeds_proxy">Dashboard</a><a href="/admin/logout">Sign out</a></nav></header>
<main><section><h2>Download packages</h2><p class="note">These packages contain the deployed ReEDS-Proxy source code and all deployed input data.</p>
<div class="actions"><a class="button" href="/admin/download/bundle?name=source">Download source code (.zip)</a>
<a class="button" href="/admin/download/bundle?name=inputs">Download input data (.zip)</a>
<a class="button" href="/admin/download/models">Download all trained models (.tar)</a></div></section>
<section><h2>Source code browser</h2><table><thead><tr><th>File</th><th>Size</th></tr></thead><tbody>{''.join(source_rows)}</tbody></table></section>
<section><h2>Input data</h2><table><thead><tr><th>File</th><th>Size</th><th>Action</th></tr></thead><tbody>{''.join(input_rows)}</tbody></table></section>
<section><h2>Trained models</h2><p class="note">Model artifacts remain in the private Google Cloud Storage bucket and are delivered only after admin authentication.</p>
<table><thead><tr><th>Model</th><th>Size</th><th>Action</th></tr></thead><tbody>{''.join(model_rows)}</tbody></table></section></main></body></html>""")


class AdminCodeHandler(_AdminBaseHandler):
    def get(self) -> None:
        self.require_admin()
        relative = self.get_argument("path")
        path = _resolve_file(_STAGE_ROOT, relative)
        allowed = {candidate.resolve() for _, candidate in _source_files()}
        if path not in allowed:
            raise HTTPError(404)
        content = path.read_text(encoding="utf-8", errors="replace")
        self.set_header("Content-Type", "text/html; charset=UTF-8")
        self.write(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(relative)} - ReEDS-Proxy</title><style>
body {{ margin:0;background:#f4f7f9;color:#1f2933;font-family:Arial,sans-serif }} header {{ position:sticky;top:0;background:#153243;color:#fff;padding:14px 20px }}
header a {{ color:#d9efff;margin-right:16px }} h1 {{ display:inline;font-size:1rem }} pre {{ margin:20px;white-space:pre;overflow:auto;background:#fff;border:1px solid #d9e2ec;border-radius:8px;padding:18px;line-height:1.45;tab-size:4 }}
</style></head><body><header><a href="/admin">Back to portal</a><h1>{html.escape(relative)}</h1></header><pre><code>{html.escape(content)}</code></pre></body></html>""")


class AdminBundleDownloadHandler(_AdminBaseHandler):
    async def get(self) -> None:
        self.require_admin()
        name = self.get_argument("name")
        bundles = {
            "source": _DOWNLOADS_ROOT / "reeds-proxy-source-code.zip",
            "inputs": _DOWNLOADS_ROOT / "reeds-proxy-input-data.zip",
        }
        if name not in bundles:
            raise HTTPError(404)
        await self._send_file(_resolve_file(_DOWNLOADS_ROOT, bundles[name].name))

    async def _send_file(self, path: Path) -> None:
        self.set_header("Content-Type", "application/zip")
        self.set_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.set_header("Content-Length", str(path.stat().st_size))
        with path.open("rb") as stream:
            while chunk := await asyncio.to_thread(stream.read, _CHUNK_SIZE):
                self.write(chunk)
                await self.flush()


class AdminModelDownloadHandler(_AdminBaseHandler):
    async def get(self) -> None:
        self.require_admin()
        path = _resolve_file(_MODELS_ROOT, self.get_argument("path"))
        if path.suffix.lower() != ".joblib":
            raise HTTPError(404)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.set_header("Content-Type", content_type)
        self.set_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.set_header("Content-Length", str(path.stat().st_size))
        with path.open("rb") as stream:
            while chunk := await asyncio.to_thread(stream.read, _CHUNK_SIZE):
                self.write(chunk)
                await self.flush()


class AdminInputDownloadHandler(_AdminBaseHandler):
    async def get(self) -> None:
        self.require_admin()
        input_root = _STAGE_ROOT / "inputs"
        path = _resolve_file(input_root, self.get_argument("path"))
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.set_header("Content-Type", content_type)
        self.set_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.set_header("Content-Length", str(path.stat().st_size))
        with path.open("rb") as stream:
            while chunk := await asyncio.to_thread(stream.read, _CHUNK_SIZE):
                self.write(chunk)
                await self.flush()


class AdminModelsArchiveHandler(_AdminBaseHandler):
    async def get(self) -> None:
        self.require_admin()
        model_files = _model_files()
        if not model_files:
            raise HTTPError(404)
        self.set_header("Content-Type", "application/x-tar")
        self.set_header("Content-Disposition", 'attachment; filename="reeds-proxy-trained-models.tar"')
        for relative, path in model_files:
            stat = path.stat()
            info = tarfile.TarInfo(relative)
            info.size = stat.st_size
            info.mtime = int(stat.st_mtime)
            info.mode = 0o644
            self.write(info.tobuf(format=tarfile.PAX_FORMAT))
            await self.flush()
            with path.open("rb") as stream:
                while chunk := await asyncio.to_thread(stream.read, _CHUNK_SIZE):
                    self.write(chunk)
                    await self.flush()
            padding = (-stat.st_size) % tarfile.BLOCKSIZE
            if padding:
                self.write(b"\0" * padding)
                await self.flush()
        self.write(b"\0" * (tarfile.BLOCKSIZE * 2))


ADMIN_ROUTES = [
    (r"/admin", AdminPortalHandler),
    (r"/admin/login", AdminLoginHandler),
    (r"/admin/logout", AdminLogoutHandler),
    (r"/admin/code", AdminCodeHandler),
    (r"/admin/download/bundle", AdminBundleDownloadHandler),
    (r"/admin/download/input", AdminInputDownloadHandler),
    (r"/admin/download/model", AdminModelDownloadHandler),
    (r"/admin/download/models", AdminModelsArchiveHandler),
]
