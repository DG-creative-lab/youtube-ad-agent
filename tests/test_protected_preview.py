from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from httpx import Client, WSGITransport

from preview.application import FIXTURE, PreviewApplication, scope_for
from preview.build_seed import seed_database
from preview.storage import WorkspaceConflict, sqlite_store


ORIGIN = "https://protected.example"
CODES = ("a" * 43, "b" * 43)
CLOCK = int(datetime(2026, 11, 18, tzinfo=timezone.utc).timestamp())
HEADERS = {"Origin": ORIGIN, "X-Placement-Review": "campaign", "X-Viewer": "comparison"}


class ProtectedPreviewTests(TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / "snapshots.sqlite"
        self.invites = {scope_for(code): CLOCK + 600 for code in CODES}
        self.seed = seed_database()

    def client(self, code=None):
        application = PreviewApplication(sqlite_store(self.path, FIXTURE), self.invites, ORIGIN,
                                         self.seed, clock=lambda: CLOCK)
        client = self.enterContext(Client(transport=WSGITransport(app=application), base_url=ORIGIN,
                                          headers=HEADERS))
        if code is not None:
            response = client.post("/invite", data={"code": code})
            self.assertEqual(response.status_code, 303, response.text)
        return client

    def test_agent_approval_viewer_and_isolation_survive_new_gateway(self):
        anonymous = self.client()
        self.assertEqual(anonymous.get("/invite").headers["referrer-policy"], "same-origin")
        self.assertEqual(anonymous.post("/invite", data={"code": CODES[0]},
                                        headers={"Origin": "null"}).status_code, 403)
        first = self.client(CODES[0])
        second = self.client(CODES[1])
        self.assertEqual(self.client().get("/api/campaign").status_code, 401)
        run_id = "9" * 32
        request = first.get("/api/mode").json()["demoRequest"]
        initial = first.post("/api/agent/run", json={"run_id": run_id, "request": request})
        self.assertEqual(initial.status_code, 200, initial.text)
        run = initial.json()
        for _ in range(12):
            if run["status"] != "running":
                break
            response = first.post("/api/agent/run", json={"run_id": run_id})
            self.assertEqual(response.status_code, 200, response.text)
            run = response.json()
        self.assertEqual(run["status"], "ready_for_review", run)

        first = self.client(CODES[0])
        draft = first.get("/api/campaign").json()
        self.assertEqual(draft["revision"], 2)
        self.assertEqual(second.get("/api/campaign").json()["revision"], 1)
        self.assertEqual(second.get(f"/api/agent/run?id={run_id}").status_code, 404)
        package = first.get("/api/campaign/package?revision=2").json()
        reference = {"campaign_id": draft["campaign_id"], "revision": 2, "fingerprint": package["fingerprint"]}
        self.assertEqual(second.post("/api/campaign/approve", json=reference).status_code, 400)
        self.assertEqual(first.post("/api/campaign/approve", json=reference).status_code, 200)
        handoff = first.post("/api/campaign/export", json=reference)
        self.assertEqual(handoff.status_code, 200, handoff.text)
        self.assertEqual(handoff.json()["viewer_origin"], ORIGIN)
        viewer = first.post("/api/viewer/open", json={"creative_ref": "audiobook-reading-v1",
                                                     "example_ref": None, "visit_id": None})
        self.assertEqual(viewer.status_code, 200, viewer.text)
        take = viewer.json()["example"]["takes"][0]["url"]
        self.assertEqual(first.get(take, headers={"Range": "bytes=0-15"}).status_code, 206)
        self.assertEqual(second.get(take).status_code, 404)
        self.assertEqual(self.client().get(take).status_code, 401)
        self.assertEqual(first.post("/api/openrouter/connect", json={}).status_code, 403)

        self.assertEqual(second.post("/invite/reset", data={"confirm": "yes"}).status_code, 303)
        self.assertEqual(first.get("/api/campaign").json()["revision"], 2)
        self.assertEqual(second.post("/invite/disable", data={"confirm": "yes"}).status_code, 303)
        self.assertEqual(self.client().post("/invite", data={"code": CODES[1]}).status_code, 403)

    def test_stale_writes_cannot_overwrite_another_request_or_revive_a_disabled_invite(self):
        store = sqlite_store(self.path, FIXTURE)
        invite = scope_for(CODES[0])
        store.save(invite, None, self.seed)
        initial = store.load(invite)
        store.save(invite, initial.version, None, disable=True)
        with self.assertRaises(WorkspaceConflict):
            store.save(invite, initial.version, self.seed)
        with self.assertRaises(WorkspaceConflict):
            store.save(invite, None, self.seed)
        self.assertTrue(store.load(invite, include_snapshot=True).disabled)
