"""Request-local live OpenRouter transport for the invited campaign workspace."""
from io import BytesIO
from urllib.error import HTTPError
import json
import subprocess
import sys
from pathlib import Path

from campaign_agent.adapters.openrouter_models import OpenRouterMetadata
from campaign_agent.application.catalogue_policy import select_live_endpoint
from campaign_agent.ports.inference import ProviderError



def send(request, *, timeout):
    if not request.full_url.startswith("https://openrouter.ai/api/v1/"):
        raise ProviderError("invalid_request")
    # Isolate blocking DNS/socket reads in a short-lived child. The parent kills
    # and reaps it on timeout, retaining neither a running worker nor its key.
    wire = {"url": request.full_url, "method": request.get_method(),
            "headers": dict(request.header_items()),
            "body": request.data.decode("utf-8") if request.data is not None else None,
            "timeout": min(timeout, 25)}
    try:
        result = subprocess.run([sys.executable, "-c", "from preview.providers import worker; worker()"],
            input=json.dumps(wire).encode(), cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=min(timeout, 25) + 2, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ProviderError("catalogue_unavailable") from None
    if result.returncode or len(result.stdout) > 2_000_004:
        raise ProviderError("catalogue_unavailable")
    status, separator, body = result.stdout.partition(b"\n")
    if not separator or not status.isdigit() or len(status) != 3:
        raise ProviderError("catalogue_unavailable")
    if int(status) >= 400:
        raise HTTPError(request.full_url, int(status), "Provider request failed", {}, BytesIO(body))
    return BytesIO(body)


class LiveMetadata(OpenRouterMetadata):
    def __init__(self):
        super().__init__(transport=send)

    def models(self, credential, *, sort=None):
        return super().models(credential, sort=sort, tools_only=True)

    def select_route(self, credential, model, task, *, now, previous=None):
        return select_live_endpoint(model, task, self.endpoints(credential, model), now, previous=previous)


def profiles():
    # Live routes are qualified from current metadata rather than a model list.
    return ()


def sessions(path, **options):
    from contextlib import closing
    import sqlite3
    from campaign_agent.bootstrap.runtime import create_provider_sessions
    from campaign_agent.adapters.catalogue_cache import CatalogueCache

    class SnapshotCache(CatalogueCache):
        # Catalogue revisions and cursors must survive a new serverless instance.
        def __init__(self):
            super().__init__()
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE IF NOT EXISTS preview_catalogues(connection TEXT PRIMARY KEY, entry TEXT NOT NULL)")

        def get(self, connection, now):
            with closing(sqlite3.connect(path)) as db:
                row = db.execute("SELECT entry FROM preview_catalogues WHERE connection=?", (connection,)).fetchone()
            if row:
                entry = json.loads(row[0])
                if entry["expires_at"] > now:
                    return entry
            return None

        def finish(self, connection, entry=None):
            super().finish(connection, entry)
            if entry is not None:
                entry["connection"] = connection
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute("INSERT OR REPLACE INTO preview_catalogues VALUES (?,?)", (connection, json.dumps(entry)))

        def page(self, entry, search, cursor, **filters):
            rows = super().page(entry, search, cursor, **filters)
            self.finish(entry["connection"], entry)
            return rows

        def invalidate(self, connection):
            super().invalidate(connection)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("DELETE FROM preview_catalogues WHERE connection=?", (connection,))

    service = create_provider_sessions(path, **options)
    service.cache = SnapshotCache()
    service.route_selector = getattr(service.metadata, "select_route", None)
    return service


def worker():
    from urllib.request import Request
    from urllib.error import HTTPError
    from campaign_agent.adapters.openrouter_reviews import send_request
    value = json.loads(sys.stdin.buffer.read(100_000))
    if not value["url"].startswith("https://openrouter.ai/api/v1/"):
        raise ValueError("Unsupported provider origin")
    request = Request(value["url"], method=value["method"], headers=value["headers"],
                      data=value["body"].encode() if value["body"] is not None else None)
    try:
        response = send_request(request, timeout=value["timeout"])
    except HTTPError as error:
        response = error
    with response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Oversized provider response")
    sys.stdout.buffer.write(str(response.status).encode() + b"\n" + raw)
