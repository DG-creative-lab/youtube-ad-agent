"""Vercel entrypoint for the invite-only demo."""
from functools import lru_cache
import json
import os
from pathlib import Path
import re

from preview.application import FIXTURE, PreviewApplication
from preview.storage import WorkspaceUnavailable, connected_store, expand_snapshot


@lru_cache(maxsize=1)
def deployment():
    invites = json.loads(os.environ["DEMO_INVITES"])
    if (not isinstance(invites, dict) or not invites
            or not all(re.fullmatch(r"[0-9a-f]{64}", code) and type(expires) is int
                       for code, expires in invites.items())):
        raise ValueError("Configure the preview invite digests and deadlines.")
    host = os.environ["VERCEL_URL"]
    if not re.fullmatch(r"[a-z0-9-]+\.vercel\.app", host):
        raise ValueError("Use the protected Vercel deployment hostname.")
    seed = expand_snapshot((Path(__file__).resolve().parent / "preview" / "seed.data").read_bytes())
    from preview.providers import LiveMetadata, profiles, send
    return PreviewApplication(connected_store(FIXTURE), invites, f"https://{host}", seed,
                              journey_seeds={phase: expand_snapshot((Path(__file__).resolve().parent / "preview" / f"journey-{phase}.data").read_bytes())
                                             for phase in ("plan", "wait", "learning")},
                              provider_metadata=LiveMetadata(), provider_profiles=profiles(),
                              completion_transport=send)


def app(environ, start_response):
    if os.getenv("VERCEL_ENV") != "preview":
        start_response("404 Not Found", [("Content-Length", "0")])
        return [b""]
    try:
        handler = deployment()
    except (ImportError, OSError, KeyError, ValueError, WorkspaceUnavailable):
        body = b'{"error":"Preview configuration is unavailable."}'
        start_response("503 Service Unavailable", [("Content-Type", "application/json"),
                       ("Cache-Control", "no-store"), ("Content-Length", str(len(body)))])
        return [body]
    return handler(environ, start_response)
