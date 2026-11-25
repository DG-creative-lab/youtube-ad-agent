from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from httpx2 import Client, WSGITransport

from preview.application import FIXTURE, PreviewApplication, scope_for
from preview.build_seed import seed_database
from preview.storage import WorkspaceConflict, _turso_ready, sqlite_store


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

    def client(self, code=None, *, store=None):
        if store is None:
            store = sqlite_store(self.path, FIXTURE)
        application = PreviewApplication(store, self.invites, ORIGIN,
                                         self.seed, clock=lambda: CLOCK)
        client = self.enterContext(Client(transport=WSGITransport(app=application), base_url=ORIGIN,
                                          headers=HEADERS))
        if code is not None:
            response = client.post("/invite", data={"code": code})
            self.assertEqual(response.status_code, 303, response.text)
        return client

    def test_health_rechecks_storage_after_a_successful_request(self):
        store = sqlite_store(self.path, FIXTURE)
        client = self.client(CODES[0], store=store)
        self.assertEqual(client.get("/health").status_code, 200)
        with patch.object(store, "connect", side_effect=TimeoutError("synthetic storage failure")):
            health = client.get("/health")
            self.assertEqual(health.status_code, 503)
            self.assertEqual(health.json()["storage"], "unavailable")
            self.assertEqual(client.head("/health").status_code, 503)
        health = client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["storage"], "ready")

    def test_turso_health_probe_requires_a_successful_query_with_a_timeout(self):
        close = {"type": "ok", "response": {"type": "close"}}
        execute = {"type": "ok", "response": {"type": "execute"}}
        error = {"type": "error", "error": {"message": "simulated query failure"}}
        with patch("preview.storage.HTTPSConnection") as connect:
            connection = connect.return_value
            response = MagicMock()
            response.__enter__.return_value = response
            connection.getresponse.return_value = response
            for status, result, ready in ((200, execute, True), (200, error, False), (401, error, False)):
                with self.subTest(status=status, result=result["type"]):
                    response.status = status
                    response.read.return_value = json.dumps({"results": [result, close]}).encode()
                    self.assertIs(_turso_ready("libsql://fixture.example", "test-token"), ready)
                    connect.assert_called_with("fixture.example", None, timeout=2)
            connection.getresponse.side_effect = TimeoutError
            self.assertFalse(_turso_ready("libsql://fixture.example", "test-token"))

    def test_agent_approval_viewer_and_isolation_survive_new_gateway(self):
        anonymous = self.client()
        self.assertEqual(anonymous.get("/invite").headers["referrer-policy"], "same-origin")
        self.assertEqual(anonymous.post("/invite", data={"code": CODES[0]},
                                        headers={"Origin": "null"}).status_code, 403)
        first = self.client(CODES[0])
        second = self.client(CODES[1])
        self.assertEqual(self.client().get("/api/campaign").status_code, 401)
        run_id = "9" * 32
        mode = first.get("/api/mode").json()
        self.assertIs(mode["openrouterAvailable"], False)
        request = mode["demoRequest"]
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


class LivePreviewTests(TestCase):
    def setUp(self):
        from campaign_agent.adapters.fixture_access import AuthoredProviderMetadata
        self.metadata = AuthoredProviderMetadata()
        from dataclasses import replace
        self.metadata.profiles = tuple(replace(profile, version="preview-text-tools/test") for profile in self.metadata.profiles)
        self.directory = self.enterContext(TemporaryDirectory())
        self.path = Path(self.directory) / "live-preview.sqlite"
        self.store = sqlite_store(self.path, FIXTURE)
        self.invites = {scope_for(code): CLOCK + 600 for code in CODES}
        self.seed = seed_database()
        self.calls = []
        self.lose_response = False
        self.output_commands = []

    def completion(self, request, *, timeout):
        import io
        # The durable snapshot must already have a possibly-sent reservation.
        import sqlite3
        saved = self.store.load(scope_for(CODES[0]), include_snapshot=True)
        file = Path(self.directory) / "checkpoint.sqlite"
        file.write_bytes(saved.snapshot)
        with sqlite3.connect(file) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM inference_ledger WHERE state='dispatching'").fetchone()[0], 1)
        self.calls.append(request)
        if self.lose_response:
            raise TimeoutError("authored transport failure")
        name, arguments = self.output_commands.pop(0) if self.output_commands else ("respond", {
            "topic": "campaign_summary",
            "message": "I can help you plan a contextual campaign. What audience should we start with?"})
        return io.BytesIO(json.dumps({
            "id": "gen-authored-preview", "model": "fixture/tool-model",
            "usage": {"cost": 0, "prompt_tokens": 100, "completion_tokens": 25},
            "choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{
                "id": "call-authored-preview", "type": "function", "function": {
                    "name": name, "arguments": json.dumps(arguments)}
            }]}}]
        }).encode())

    def client(self, code=CODES[0]):
        application = PreviewApplication(self.store, self.invites, ORIGIN, self.seed,
            clock=lambda: CLOCK, provider_metadata=self.metadata,
            provider_profiles=self.metadata.profiles, completion_transport=self.completion)
        client = self.enterContext(Client(transport=WSGITransport(app=application),
                                         base_url=ORIGIN, headers=HEADERS))
        self.assertEqual(client.post("/invite", data={"code": code}).status_code, 303)
        return client

    def post(self, client, path, data, *, credential=True):
        response = client.post(path, json=data, headers={"X-OpenRouter-Key": self.metadata.keys[0]} if credential else {})
        self.assertNotIn(self.metadata.keys[0], response.text)
        return response

    def prepare(self, permission="none"):
        from uuid import uuid4
        tab = uuid4().hex
        first = self.client()
        mode = first.get("/api/mode").json()
        self.assertIs(mode["liveInference"], True)
        self.assertEqual(mode["agentPlanner"]["models"], [])
        self.assertEqual(mode["agentPlanner"]["default"], "")
        imported = first.post("/api/agent/catalog", json={"label": "Permitted creator catalog", "rows": [
            {"video_id": "SAMPLE00001", "description": "Video editing tutorial",
             "source": "creator_supplied", "source_reference": "Creator permission for test"}]})
        self.assertEqual(imported.status_code, 200, imported.text)
        catalog_id = imported.json()["id"]
        connected = self.post(first, "/api/openrouter/connect",
            {"operation_id": uuid4().hex, "tab_id": tab})
        self.assertEqual(connected.status_code, 200, connected.text)
        connection = connected.json()["connection_id"]
        # Cold instances must preserve the provider identity and selection.
        second = self.client()
        catalogue = self.post(second, "/api/openrouter/models",
            {"connection_id": connection, "tab_id": tab, "search": "", "cursor": None})
        self.assertEqual(catalogue.status_code, 200, catalogue.text)
        selected = self.post(self.client(), "/api/openrouter/select", {
            "operation_id": uuid4().hex, "connection_id": connection, "tab_id": tab,
            "model_id": "fixture/tool-model", "catalogue_revision": catalogue.json()["catalogue_revision"],
            "profile": "planner", "max_run_cost_usd": "0"})
        self.assertEqual(selected.status_code, 200, selected.text)
        session, run = uuid4().hex, uuid4().hex
        start = self.post(second, "/api/agent/placements", {
            "run_id": run, "session_id": session, "request": "Help me plan a campaign",
            "model": "fixture/tool-model", "provider_selection_id": selected.json()["selection_id"],
            "catalog_id": catalog_id, "draft_permission": permission})
        self.assertEqual(start.status_code, 200, start.text)
        return run, session

    def test_dynamic_route_and_cached_prices_survive_fresh_preview_instances(self):
        from campaign_agent.application.catalogue_policy import select_live_endpoint
        self.metadata.profiles=()
        self.metadata.select_route=lambda credential,model,task,now,previous=None: select_live_endpoint(
            model,task,self.metadata.endpoints(credential,model),now,previous=previous)
        self.metadata.endpoint['supported_parameters'].remove('parallel_tool_calls')
        self.metadata.endpoint['pricing'].update(input_cache_read='0',discount=0)
        run,session=self.prepare()
        response=self.post(self.client(),'/api/agent/run',{'run_id':run})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['status'],'answered')
        self.assertEqual(self.post(self.client(),'/api/agent/run',{'run_id':run},credential=False).status_code,200)
        self.assertEqual(len(self.calls),1)
        self.assertNotIn('parallel_tool_calls',json.loads(self.calls[0].data))
        self.assertIn('What audience',self.client().get('/api/agent/conversation',params={'id':session}).json()['messages'][-1]['content'])

    def test_live_reply_cold_instance_checkpoint_and_secret_exclusion(self):
        run, session = self.prepare()
        response = self.post(self.client(), "/api/agent/run", {"run_id": run})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "answered")
        self.assertEqual(response.json()["result"]["reply_code"], "model_response")
        self.assertEqual(len(self.calls), 1)
        replay = self.post(self.client(), "/api/agent/run", {"run_id": run}, credential=False)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(len(self.calls), 1)
        chat = self.client().get("/api/agent/conversation", params={"id": session}).json()
        self.assertIn("What audience", chat["messages"][-1]["content"])
        foreign = self.client(CODES[1]).get("/api/agent/conversation", params={"id": session})
        self.assertIn(foreign.status_code, (403, 404))
        snapshot = self.store.load(scope_for(CODES[0]), include_snapshot=True).snapshot
        self.assertNotIn(self.metadata.keys[0].encode(), snapshot)

    def test_unknown_completion_is_never_resent_after_a_fresh_instance(self):
        run, _ = self.prepare()
        self.lose_response = True
        response = self.post(self.client(), "/api/agent/run", {"run_id": run})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["code"], "inference_outcome_unknown")
        replay = self.post(self.client(), "/api/agent/run", {"run_id": run})
        self.assertEqual(replay.status_code, 409, replay.text)
        self.assertEqual(len(self.calls), 1)

    def test_failed_checkpoint_sends_zero_completions_and_live_cannot_start_offline(self):
        run, _ = self.prepare()
        with patch.object(self.store, "save", side_effect=WorkspaceConflict("authored conflict")):
            response = self.post(self.client(), "/api/agent/run", {"run_id": run})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.calls, [])
        response = self.post(self.client(), "/api/agent/run",
            {"run_id": "f" * 32, "request": "Prepare a YouTube test for ElevenLabs Text to Speech."}, credential=False)
        self.assertEqual(response.status_code, 409, response.text)

    def test_selected_model_classifies_inspected_catalog_without_simulation(self):
        from unittest.mock import patch
        from campaign_agent.placement_discovery import SimulatedClassifier
        self.output_commands = [("read_campaign", {}), ("inspect_catalog", {}),
            ("classify_catalog", {"assignments": [{"id": "SAMPLE00001", "context": "video-editing"}]}),
            ("save_placement_draft", {"video_ids": ["SAMPLE00001"]})]
        run, _ = self.prepare(permission="placements")
        with patch.object(SimulatedClassifier, "classify", side_effect=AssertionError("Unexpected simulation")):
            for _ in range(4):
                response = self.post(self.client(), "/api/agent/run", {"run_id": run})
                self.assertEqual(response.status_code, 200, response.text)
                if response.json()["status"] != "running":
                    break
                if response.json()["steps"][-1]["tool"] == "inspect_catalog":
                    first = response.json()["steps"][-1]["result"]["entries"][0]["video_id"]
                    self.output_commands[0] = ("classify_catalog", {"assignments": [{"id": first, "context": "video-editing"}]})
                    self.output_commands[1] = ("save_placement_draft", {"video_ids": [first]})
        self.assertEqual(response.json()["status"], "ready_for_review")
        self.assertEqual(len(self.calls), 4)
        classified = next(step for step in response.json()["steps"] if step["tool"] == "classify_catalog")
        self.assertEqual(classified["result"]["route"], "main_model")
        self.assertNotIn("simulated", response.json()["result"]["message"].lower())


class LiveTransportTests(TestCase):
    def test_total_deadline_and_credential_stdin(self):
        from urllib.request import Request
        from types import SimpleNamespace
        import subprocess
        from preview.providers import send
        from campaign_agent.ports.inference import ProviderError
        key = "authored-key-for-transport-test"
        request = Request("https://openrouter.ai/api/v1/chat/completions",
                          data=b'{"messages":[]}', headers={"Authorization": "Bearer " + key})
        with patch("preview.providers.subprocess.run",
                   return_value=SimpleNamespace(returncode=0, stdout=b'200\n{"data":[]}')) as run:
            with send(request, timeout=30) as response:
                self.assertEqual(response.read(), b'{"data":[]}')
            args, options = run.call_args
            self.assertNotIn(key, repr(args))
            self.assertIn(key.encode(), options["input"])
            self.assertEqual(options["timeout"], 27)
            self.assertIs(options["stderr"], subprocess.DEVNULL)
        with patch("preview.providers.subprocess.run", side_effect=subprocess.TimeoutExpired("provider", 27)):
            with self.assertRaises(ProviderError) as raised:
                send(request, timeout=30)
            self.assertNotIn(key, str(raised.exception))
