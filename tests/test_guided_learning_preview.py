"""Exercise isolation, real campaign commands and durable learning boundaries."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import uuid4

from httpx2 import Client, WSGITransport

from preview.application import FIXTURE, PreviewApplication, scope_for, serve_command
from preview.build_seed import journey_databases, seed_database
from preview.storage import sqlite_store

ORIGIN = "https://protected.example"
CODES = ("a" * 43, "b" * 43)
HEADERS = {"Origin": ORIGIN, "X-Placement-Review": "campaign", "X-Viewer": "comparison"}


class GuidedLearningPreviewTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seeds = journey_databases()
        cls.seed = seed_database()

    def setUp(self):
        folder = self.enterContext(TemporaryDirectory())
        self.path = Path(folder) / "snapshots.sqlite"
        self.store = sqlite_store(self.path, FIXTURE)
        self.provider = Mock(side_effect=AssertionError("Exercise cannot call a provider"))

    def client(self, code=CODES[0]):
        app = PreviewApplication(sqlite_store(self.path, FIXTURE), {scope_for(c): 2000 for c in CODES},
                                 ORIGIN, self.seed, clock=lambda: 1000, journey_seeds=self.seeds,
                                 provider_metadata=self.provider, completion_transport=self.provider)
        client = self.enterContext(Client(transport=WSGITransport(app=app), base_url=ORIGIN, headers=HEADERS))
        if code:
            self.assertEqual(client.post("/invite", data={"code": code}).status_code, 303)
        return client

    def state(self, client, phase):
        prefix = "/exercise/" + phase
        draft = client.get(prefix + "/api/campaign").json()
        review = client.get(prefix + "/api/campaign/package", params={"revision": draft["revision"]}).json()
        return prefix, draft, review, {"campaign_id": draft["campaign_id"], "revision": draft["revision"], "fingerprint": review["fingerprint"]}

    def test_plan_approval_export_and_media_are_scoped_and_survive_a_fresh_instance(self):
        client = self.client()
        prefix, draft, review, ref = self.state(client, "plan")
        self.assertEqual(draft["revision"], 2)
        self.assertIsNone(review["approval"])
        self.assertEqual(client.post(prefix + "/api/campaign/export", json=ref).status_code, 409)
        self.assertEqual(client.post(prefix + "/api/campaign/approve", json=ref).status_code, 200)
        handoff = client.post(prefix + "/api/campaign/export", json=ref)
        self.assertEqual(handoff.status_code, 200, handoff.text)
        self.assertEqual(handoff.json()["viewer_origin"], ORIGIN + prefix)
        _, _, saved, _ = self.state(self.client(), "plan")
        self.assertIsNotNone(saved["approval"])
        self.assertIsNone(self.state(self.client(CODES[1]), "plan")[2]["approval"])
        self.assertEqual(client.get("/api/campaign").json()["revision"], 1)
        opened = client.post(prefix + "/api/viewer/open", json={"creative_ref": "editing-voiceover-v1", "example_ref": None, "visit_id": None})
        self.assertEqual(opened.status_code, 200, opened.text)
        media = opened.json()["example"]["takes"][0]["url"]
        self.assertTrue(media.startswith(prefix + "/viewer/media/"))
        self.assertEqual(client.get(media, headers={"Range": "bytes=0-15"}).status_code, 206)
        self.assertEqual(self.client(CODES[1]).get(media).status_code, 404)
        self.assertEqual(client.get(media.replace("/plan/", "/wait/")).status_code, 404)
        self.assertEqual(client.post(prefix + "/reset", data={"confirm": "yes"}).status_code, 303)
        self.assertIsNone(self.state(client, "plan")[2]["approval"])
        self.assertEqual(self.state(client, "learning")[1]["revision"], 3)
        self.provider.assert_not_called()

    def test_wait_snapshot_excludes_rehearsals_and_cannot_change_authored_learning(self):
        client = self.client()
        prefix, _, _, ref = self.state(client, "wait")
        query = {"revision": ref["revision"], "fingerprint": ref["fingerprint"]}
        test = client.get(prefix + "/api/campaign/instruction-test", params=query).json()
        self.assertIsNone(test["evidence_snapshot"])
        rehearsal = client.post(prefix + "/api/viewer/test/open", json={"test_id": test["id"], "participant_id": uuid4().hex, "rehearsal": False})
        self.assertEqual(rehearsal.status_code, 200, rehearsal.text)
        response = client.post(prefix + "/api/campaign/instruction-test/evidence", json={**ref, "operation_id": uuid4().hex})
        self.assertEqual(response.status_code, 200, response.text)
        saved = client.get(prefix + "/api/campaign/instruction-test", params=query).json()
        self.assertEqual(saved["evidence_decision"]["action"], "wait_for_evidence")
        self.assertEqual(sum(row["cohorts"]["participant"]["mature_arrivals"] for row in saved["evidence_snapshot"]["rows"]), 0)
        self.assertEqual(sum(row["cohorts"]["rehearsal"]["unresolved"] for row in saved["evidence_snapshot"]["rows"]), 1)
        _, _, _, learning = self.state(client, "learning")
        evidence = client.get("/exercise/learning/api/campaign/instruction-test", params={"revision": learning["revision"], "fingerprint": learning["fingerprint"]}).json()
        self.assertEqual([(row["cohorts"]["participant"]["completions"], row["cohorts"]["participant"]["mature_arrivals"]) for row in evidence["evidence_snapshot"]["rows"]], [(2, 20), (18, 20)])
        self.assertEqual(evidence["evidence_decision"]["action"], "reuse")
        self.assertEqual(self.state(self.client(), "wait")[1]["revision"], 3)

    def test_fresh_brief_reuse_rechecks_permission_compatibility_and_retirement(self):
        for case in ("compatible", "no_permission", "incompatible", "retired"):
            with self.subTest(case=case):
                client = self.client()
                client.post("/exercise/learning/reset", data={"confirm": "yes"})
                prefix, _, original, ref = self.state(client, "learning")
                baseline_history = original["history"]
                response = client.post(prefix + "/api/campaign/brief", json={**ref, "title": "New editing brief", "goal": "Compare tested wording", "context": "audiobook" if case == "incompatible" else "video-editing"})
                self.assertEqual(response.status_code, 200, response.text)
                _, draft, review, target = self.state(self.client(), "learning")
                eligible = client.get(prefix + "/api/campaign/instruction-finding", params={"revision": target["revision"], "fingerprint": target["fingerprint"]}).json()
                if case == "incompatible":
                    self.assertIsNone(eligible)
                    self.assertIsNone(review["approval"])
                    continue
                finding = eligible["finding"]
                if case == "retired":
                    retired = client.post(prefix + "/api/campaign/instruction-finding/retire", json={**target, "finding_id": finding["id"]})
                    self.assertEqual(retired.status_code, 200, retired.text)
                fields = {**target, "finding_id": finding["id"], "correction_id": eligible["correction"]["id"]}
                fields["draft_permission"] = "none" if case == "no_permission" else "instruction_test"
                applied = client.post(prefix + "/api/campaign/instruction-finding/apply", json=fields)
                if case == "compatible":
                    self.assertEqual(applied.status_code, 200, applied.text)
                    _, saved, package, _ = self.state(self.client(), "learning")
                    self.assertEqual(saved["revision"], draft["revision"] + 1)
                    self.assertEqual(package["package"]["groups"][0]["content"]["instruction"], finding["after"])
                    self.assertIsNone(package["approval"])
                    self.assertEqual(package["history"], baseline_history)
                    self.assertEqual(saved["instruction_reuse"]["finding"]["id"], finding["id"])
                else:
                    self.assertIn(applied.status_code, (403, 409), applied.text)
                    self.assertEqual(self.state(client, "learning")[1]["revision"], draft["revision"])
                self.assertEqual(client.get("/api/campaign").json()["revision"], 1)
        self.provider.assert_not_called()

    def test_gate_blocks_unavailable_routes_live_credentials_and_revoked_invites(self):
        client = self.client()
        self.assertEqual(self.client(None).get("/exercise/plan/api/campaign").status_code, 401)
        for path in ("/exercise/other/", "/exercise/plan/reset", "/exercise/plan/api/openrouter/models"):
            self.assertEqual(client.get(path).status_code, 404)
        for path in ("/api/agent/run", "/api/campaign/setup", "/api/openrouter/connect"):
            self.assertEqual(client.post("/exercise/plan" + path, json={}).status_code, 404)
        self.assertEqual(client.get("/exercise/plan/api/campaign", headers={"X-OpenRouter-Key": "authored-test-key"}).status_code, 403)
        self.assertEqual(client.post("/exercise/plan/reset", data={"confirm": "yes"}, headers={"Origin": "https://foreign.example"}).status_code, 403)
        self.assertEqual(client.post("/exercise/plan/reset", data={"confirm": "no"}).status_code, 400)
        stale = self.client()
        self.assertEqual(client.post("/invite/disable", data={"confirm": "yes"}).status_code, 303)
        self.assertEqual(client.get("/exercise/plan/api/campaign").status_code, 401)
        self.assertEqual(stale.get("/exercise/plan/api/campaign").status_code, 403)
        self.provider.assert_not_called()

    def test_lost_snapshot_write_cannot_publish_a_partial_approval(self):
        client = self.client()
        prefix, _, _, ref = self.state(client, "plan")
        scope = scope_for("learning-exercise-v1:plan:" + scope_for(CODES[0]))

        def concurrent_write(*args, **kwargs):
            response = serve_command(*args, **kwargs)
            if args[0] == "/api/campaign/approve":
                self.store.save(scope, None, self.seeds["plan"])
            return response

        with patch("preview.application.serve_command", side_effect=concurrent_write):
            response = client.post(prefix + "/api/campaign/approve", json=ref)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIsNone(self.state(self.client(), "plan")[2]["approval"])
        self.assertEqual(client.get("/api/campaign").json()["revision"], 1)
        self.assertEqual(client.post(prefix + "/api/campaign/approve", json=ref).status_code, 200)
        self.assertIsNotNone(self.state(self.client(), "plan")[2]["approval"])
