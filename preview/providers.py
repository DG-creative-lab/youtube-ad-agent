"""Request-local live OpenRouter transport for the invited campaign workspace."""
from io import BytesIO
from urllib.error import HTTPError
import json
import subprocess
import sys
from pathlib import Path

from campaign_agent.adapters.openrouter_models import OpenRouterMetadata
from campaign_agent.application.catalogue_policy import endpoint_fingerprint
from campaign_agent.ports.inference import ChargingProfile, ProviderError

# Exact public endpoint observations reviewed on 19 November 2026.
# The text-only request enables custom function tools and excludes web search.
ROUTES = {
    "openai/gpt-4.1-mini": {
        "tag": "openai",
        "observed_hash": "ae91de17fc803b74392274d73533a1d557000aab09137c717b7052e37f86a747",
        "projected_hash": "7b001e306b9c1a374ece74f5ecc8056a763a2e1452b4c5b8ca6459a3cd558aee",
        "cap": "max_tokens",
        "prompt_ceiling": "0.4000000",
        "completion_ceiling": "1.6000000"
    },
    "openai/gpt-4.1-nano": {
        "tag": "azure",
        "observed_hash": "fd40812eec10cf773351839f0f0c11d94fae52a39c19f80589c6e7a99686ecc8",
        "projected_hash": "5c04834a0e6ac63d3c67e39981d4b41a07414a9121b53256837abd4ed5bbde1a",
        "cap": "max_completion_tokens",
        "prompt_ceiling": "0.1000000",
        "completion_ceiling": "0.4000000"
    }
}
EXPIRES = 1797638400


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
        rows = super().models(credential, sort=sort, tools_only=True)
        selected = []
        for row in rows:
            if row.get("id") in ROUTES and "text" in row.get("architecture", {}).get("input_modalities", []):
                selected.append({**row, "architecture": {**row["architecture"], "input_modalities": ["text"]},
                                 "pricing": {k: row["pricing"][k] for k in ("prompt", "completion")}})
            else:
                selected.append(row)
        return selected

    def endpoints(self, credential, model):
        if model not in ROUTES:
            raise ProviderError("route_unqualified")
        route = ROUTES[model]
        rows = super().endpoints(credential, model)
        for row in rows:
            if row.get("tag") == route["tag"] and endpoint_fingerprint(row) == route["observed_hash"]:
                return [project_endpoint(row)]
        raise ProviderError("route_unqualified")


def project_endpoint(row):
    # OpenRouter's OpenAI-compatible tool API accepts parallel_tool_calls=false.
    # Keep the exact observed fingerprint fence before projecting used prices.
    return {**row, "pricing": {k: row["pricing"][k] for k in ("prompt", "completion")},
            "supported_parameters": [*row["supported_parameters"], "parallel_tool_calls"]}


def profiles():
    return tuple(ChargingProfile(model=model, endpoint=row["tag"], version="preview-text-tools/2026-11-19",
        endpoint_hash=row["projected_hash"], expires_at=EXPIRES,
        max_prompt_usd_per_million=row["prompt_ceiling"],
        max_completion_usd_per_million=row["completion_ceiling"],
        output_cap_parameter=row["cap"],
        evidence="Exact OpenRouter endpoint metadata, 19 November 2026; text/custom tools only")
        for model, row in ROUTES.items())


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
