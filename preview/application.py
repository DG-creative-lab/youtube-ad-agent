"""Preview-only WSGI gateway for the existing fictional planner and viewer."""
from email.message import Message
from hashlib import sha256
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from io import BytesIO
import json
import logging
from pathlib import Path
import re
import secrets
from tempfile import TemporaryDirectory
from time import time
from traceback import extract_tb
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from campaign_agent.bootstrap.runtime import DEMO_MEDIA_DIR
from scripts.placement_review import build_handler
from .storage import WorkspaceConflict, WorkspaceUnavailable

FIXTURE = "contextual-tts-demo-v1"
COOKIE = "__Host-youtube_demo"
SECRET = re.compile(r"[A-Za-z0-9_-]{32,64}")
MAX_BODY = 800_000
OPERATOR = secrets.token_urlsafe(32)
LOG = logging.getLogger(__name__)
INVITE_FORM = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Contextual YouTube campaign demo</title><link rel="stylesheet" href="/brand/tokens.css">
<style>
body {{ margin: 0; color: var(--ink); background: var(--paper); font: 1rem/1.55 var(--sans); }}
main {{ width: min(36rem, calc(100% - 3rem)); margin: clamp(2rem, 8vw, 6rem) auto; }}
h1 {{ line-height: 1.1; font-size: clamp(2rem, 6vw, 3.1rem); letter-spacing: -.04em; }}
form {{ display: grid; gap: .6rem; max-width: 24rem; margin-block: 1.25rem; }}
input, button {{ font: inherit; }}
input[type=password], button {{ box-sizing: border-box; min-height: 44px; padding-inline: .75rem; }}
input[type=password] {{ width: 100%; border: 1px solid var(--muted); }}
button {{ border: 1px solid var(--ink); background: var(--ink); color: var(--on-dark); justify-self: start; }}
:focus-visible {{ outline: 2px solid var(--focus); outline-offset: 3px; }}
</style>
<main><h1>Contextual YouTube campaign demo</h1>
<p>Use your invite to open an isolated workspace with fictional campaigns and sample media.</p>
<form action="/invite" method="post">
<label for="code">Invite code</label>
<input id="code" name="code" type="password" autocomplete="off" maxlength="64" required>
<button type="submit">Open workspace</button></form>
{controls}</main></html>"""
CONTROLS = """<p><a href="/campaign">Return to the campaign</a></p>
<details><summary>Manage this invite</summary>
<form action="/invite/reset" method="post"><p>Reset clears this invite’s saved progress.</p>
<label><input type="checkbox" name="confirm" value="yes" required> Reset my demo workspace</label>
<button type="submit">Reset workspace</button></form>
<form action="/invite/disable" method="post"><p>Disabling the invite ends access from all preview deployments.</p>
<label><input type="checkbox" name="confirm" value="yes" required> Disable this invite</label>
<button type="submit">Disable invite</button></form></details>"""


class RequestRejected(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def payload(status, value):
    return status, json.dumps(value).encode(), [("Content-Type", "application/json")]


def redirect(location, *headers):
    return 303, b"", [("Location", location), *headers]


def scope_for(code):
    return sha256(code.encode("ascii")).hexdigest()


def verified_invite(code, invites, now):
    if not isinstance(code, str) or not SECRET.fullmatch(code):
        return None
    digest = scope_for(code)
    expiry = invites.get(digest)
    return digest if type(expiry) is int and expiry > now else None


def read_cookie(environ):
    try:
        cookie = SimpleCookie(environ.get("HTTP_COOKIE", "")).get(COOKIE)
        return cookie.value if cookie else None
    except CookieError:
        return None


def read_body(environ, maximum):
    length = environ.get("CONTENT_LENGTH", "")
    if not re.fullmatch(r"[0-9]{1,7}", length) or not 0 < int(length) <= maximum:
        raise RequestRejected(413, "Invalid request size.")
    body = environ["wsgi.input"].read(int(length))
    if len(body) != int(length):
        raise RequestRejected(400, "Incomplete request.")
    return body


def handler_headers(environ, body):
    headers = Message()
    for key in ("Host", "Origin", "Range", "X-Placement-Review", "X-Viewer"):
        value = environ.get("HTTP_" + key.replace("-", "_").upper())
        if value is not None:
            headers[key] = value
    if body:
        headers["Content-Length"] = str(len(body))
        headers["Content-Type"] = environ.get("CONTENT_TYPE", "")
    headers["X-Local-Operator"] = OPERATOR
    return headers


def serve_command(path, query, method, origin, environ, body, database_path):
    handler = build_handler(
        False, database_path, operator_token=OPERATOR, demo_scenario="propose",
        media_dir=DEMO_MEDIA_DIR, initialize=False, register_catalogs=False,
    )
    response = []

    class PreviewRequest(handler):
        def __init__(self):
            self.path = path + ("?" + query if query else "")
            self.headers = handler_headers(environ, body)
            self.rfile = BytesIO(body)
            self.server = SimpleNamespace(
                request_origin=origin, viewer_origin=origin,
                viewer_request=path == "/viewer" or path.startswith("/api/viewer/"),
            )

        def send(self, code, content, content_type="application/json", headers=()):
            encoded = json.dumps(content).encode() if content_type == "application/json" else content
            response.append((code, encoded, [("Content-Type", content_type), *headers]))

    request = PreviewRequest()
    if method == "POST":
        request.do_POST()
    else:
        request.do_GET()
    if len(response) != 1:
        raise WorkspaceUnavailable("Expected one planner response.")
    return response[0]


def scoped_media(invite, value):
    path = "/viewer/media/"
    return value.replace(path, path + invite[:32] + "/", 1) if value.startswith(path) else value


def adjust_response(response, path, method, origin, invite):
    status, body, headers = response
    if status != 200:
        return response
    if path == "/api/mode":
        data = json.loads(body)
        data["previewScope"] = invite[:32]
    elif path in {"/api/viewer/open", "/api/viewer/test/open"}:
        data = json.loads(body)
        # Local viewer responses may nest the selected example under a test or an attribution.
        def bind(value):
            if isinstance(value, list):
                return [bind(item) for item in value]
            if isinstance(value, dict):
                return {key: bind(item) for key, item in value.items()}
            return scoped_media(invite, value) if isinstance(value, str) else value
        data = bind(data)
    elif path == "/api/campaign/export" and method == "POST":
        data = json.loads(body)
        data["viewer_origin"] = origin
    else:
        return response
    return status, json.dumps(data).encode(), headers


class PreviewApplication:
    def __init__(self, store, invites, origin, seed, *, clock=time):
        self.store = store
        self.invites = invites
        self.origin = origin
        self.host = urlsplit(origin).netloc
        self.seed = seed
        self.clock = clock

    def __call__(self, environ, start_response):
        method = environ["REQUEST_METHOD"]
        try:
            response = self.dispatch(environ, method, environ["PATH_INFO"])
        except RequestRejected as error:
            response = payload(error.status, {"error": str(error)})
        except WorkspaceConflict as error:
            response = payload(409, {"error": str(error)})
        except Exception as error:
            frames = extract_tb(error.__traceback__)
            locations = " > ".join(f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}" for frame in frames)
            LOG.warning("Demo request failed: %s (%s)", type(error).__name__, locations)
            response = payload(503, {"error": "The workspace is unavailable. Refresh and try again."})
        status, body, headers = response
        headers.extend([
            ("Content-Length", str(len(body))), ("Cache-Control", "no-store"),
            ("Referrer-Policy", "same-origin"), ("X-Content-Type-Options", "nosniff"),
            ("Cross-Origin-Resource-Policy", "same-origin"), ("X-Frame-Options", "DENY"),
            ("Content-Security-Policy", "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"),
            ("X-Robots-Tag", "noindex, nofollow"),
        ])
        start_response(f"{status} {HTTPStatus(status).phrase}", headers)
        return [b"" if method == "HEAD" else body]

    def dispatch(self, environ, method, path):
        if environ.get("HTTP_HOST") != self.host:
            raise RequestRejected(404, "Preview unavailable.")
        if method not in {"GET", "HEAD", "POST"}:
            raise RequestRejected(405, "Unsupported method.")
        if method == "POST" and environ.get("HTTP_ORIGIN") != self.origin:
            raise RequestRejected(403, "Open the preview before submitting changes.")
        query = environ.get("QUERY_STRING", "")
        if len(query) > 4096:
            raise RequestRejected(400, "Invalid query.")
        if path == "/health" and method in {"GET", "HEAD"}:
            ready = self.store.is_ready()
            return payload(200 if ready else 503, {"service": "contextual-youtube-demo", "fixture": FIXTURE,
                                                  "storage": "ready" if ready else "unavailable"})
        if path in {"/brand/mark.svg", "/brand/tokens.css"} and method in {"GET", "HEAD"}:
            root = Path(__file__).resolve().parents[1]
            content_type = "text/css" if path.endswith("css") else "image/svg+xml"
            return 200, (root / "web" / path.lstrip("/")).read_bytes(), [("Content-Type", content_type)]
        now = int(self.clock())
        code = read_cookie(environ)
        invite = verified_invite(code, self.invites, now)
        if path == "/invite":
            if method != "POST":
                active = bool(invite and not self.store.load(invite).disabled)
                body = INVITE_FORM.format(controls=CONTROLS if active else "").encode()
                return 200, body, [("Content-Type", "text/html; charset=utf-8")]
            fields = self.form(environ)
            code = fields.get("code", [None])[0] if set(fields) == {"code"} and len(fields["code"]) == 1 else None
            invite = verified_invite(code, self.invites, now)
            if not invite or self.store.load(invite).disabled:
                raise RequestRejected(403, "This invite is invalid, expired, or disabled.")
            cookie = f"{COOKIE}={code}; Max-Age={self.invites[invite] - now}; Path=/; Secure; HttpOnly; SameSite=Strict"
            return redirect("/", ("Set-Cookie", cookie), ("Clear-Site-Data", '"storage"'))
        if not invite:
            if path in {"/", "/campaign", "/viewer", "/placements"} and method in {"GET", "HEAD"}:
                return redirect("/invite")
            raise RequestRejected(401, "Open the workspace with your invite.")
        if path.startswith("/api/openrouter/") or environ.get("HTTP_X_OPENROUTER_KEY") is not None:
            raise RequestRejected(403, "Provider connections are disabled in this preview.")
        if path == "/api/agent/catalog" and method == "POST":
            raise RequestRejected(403, "Choose one of the authored preview catalogs.")
        media = path.startswith("/viewer/media/")
        if media:
            first, separator, rest = path.removeprefix("/viewer/media/").partition("/")
            if not separator or not secrets.compare_digest(first, invite[:32]):
                raise RequestRejected(404, "Comparison media unavailable.")
            path = "/viewer/media/" + rest
        workspace = self.store.load(invite, include_snapshot=path.startswith("/api/"))
        if workspace.disabled:
            raise RequestRejected(403, "This invite is disabled.")
        if path in {"/invite/reset", "/invite/disable"} and method == "POST":
            if self.form(environ) != {"confirm": ["yes"]}:
                raise RequestRejected(400, "Confirm the requested workspace action.")
            disable = path.endswith("/disable")
            self.store.save(invite, workspace.version, None, disable=disable)
            if disable:
                return redirect("/invite", ("Set-Cookie", f"{COOKIE}=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Strict"),
                                ("Clear-Site-Data", '"storage"'))
            return redirect("/", ("Clear-Site-Data", '"storage"'))
        body = read_body(environ, MAX_BODY) if method == "POST" else b""
        database = workspace.snapshot if workspace.snapshot is not None else self.seed
        with TemporaryDirectory(prefix="youtube-preview-", dir="/tmp") as directory:
            database_path = Path(directory) / "workspace.sqlite"
            database_path.write_bytes(database)
            result = serve_command(path, query, method, self.origin, environ, body, database_path)
            if method == "POST":
                updated = database_path.read_bytes()
                if updated != database:
                    self.store.save(invite, workspace.version, updated)
        return adjust_response(result, path, method, self.origin, invite)

    @staticmethod
    def form(environ):
        if environ.get("CONTENT_TYPE", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
            raise RequestRejected(415, "Submit the invite form.")
        try:
            return parse_qs(read_body(environ, 512).decode("ascii"), keep_blank_values=True,
                            strict_parsing=True, max_num_fields=3)
        except ValueError:
            raise RequestRejected(400, "Invalid invite form.") from None
