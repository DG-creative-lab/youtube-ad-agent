"""Real shared-store boundaries; offline decisions are test fixtures, not authentication."""
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from campaign_agent.access import BrandScope, LOCAL_BRAND, LOCAL_CONTEXT, LOCAL_OPERATOR, Operator, WorkspaceContext
from campaign_agent.agent.run import AgentRuntime, DEMO_REQUEST
from campaign_agent.creatives import EXAMPLES
from campaign_agent.handoff import DEMO_MEDIA_DIR, package_fingerprint
from campaign_agent.measurement import ViewerMeasurement, ViewerNotFound
from campaign_agent.ports.access import AccessUnavailable
from campaign_agent.workspaces import provision_workspace
from scripts.campaign_drafts import BRIEF, POLICY, CampaignDrafts, PackageConflict


class Decisions:
    def __init__(self):
        self.blocked = set()
        self.unavailable = False
        self.requests = []
        self.campaign_grants = {}

    def decide(self, request):
        self.requests.append(request)
        if self.unavailable:
            return "unavailable"
        if request.actor_id in self.campaign_grants and request.campaign_id not in self.campaign_grants[request.actor_id]:
            return "deny"
        return "deny" if (request.actor_id, request.workspace_id, request.capability) in self.blocked else "allow"


class TenantWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(TemporaryDirectory())) / "shared.sqlite3"
        self.contexts = (
            WorkspaceContext(BrandScope("client-a", "brand"), "workspace-a", "install-a"),
            WorkspaceContext(BrandScope("client-b", "brand"), "workspace-b", "install-b"),
            WorkspaceContext(BrandScope("client-a", "second-brand"), "workspace-a2", "install-a"),
        )
        self.operator = Operator("shared-person", frozenset(c.scope for c in self.contexts))
        self.policy = Decisions()
        for index, context in enumerate(self.contexts):
            provision_workspace(self.path, context, f"campaign-{index}", operator=self.operator, access=self.policy)

    def runtime(self, index=0, campaign_id=None, operator=None):
        context = self.contexts[index]
        return AgentRuntime(self.path, self.operator if operator is None else operator, context=context, campaign_id=campaign_id or f"campaign-{index}",
                            access=self.policy, examples=tuple(replace(e, scope=context.scope) for e in EXAMPLES),
                            media_dir=DEMO_MEDIA_DIR)

    def catalog(self, runtime):
        return runtime.planner.catalogs.register("Scoped authored catalog", [
            dict(video_id="SAMPLE00001", description="Video editing", source="synthetic")])

    def block(self, index, capability):
        self.policy.blocked.add((self.operator.id, self.contexts[index].workspace_id, capability))

    def prepare(self, runtime):
        run_id = runtime.start(DEMO_REQUEST)
        runtime.resume(run_id)
        d = runtime.drafts
        review = d.review_package(d.campaign_id, 2)
        return run_id, d.approve_package(d.campaign_id, 2, review["fingerprint"])

    def test_shared_database_separates_clients_brands_catalogs_and_run_ids(self):
        runtimes = [self.runtime(i) for i in range(3)]
        first = runtimes[0]
        run_id, review = self.prepare(first)
        for other in runtimes[1:]:
            self.assertEqual(other.drafts.read()["revision"], 1)
            with self.assertRaises(PermissionError):
                other.read(run_id)
            with self.assertRaises(PermissionError):
                other.start(DEMO_REQUEST, run_id=run_id)
            with self.assertRaises(ValueError):
                other.drafts.export_setup(first.drafts.campaign_id, 2, review["fingerprint"])
            foreign_catalog = self.catalog(first)
            with closing(sqlite3.connect(self.path)) as db, self.assertRaises(ValueError):
                other.planner.catalogs.read(db, foreign_catalog)
        # Different campaigns under one brand are also independent execution contexts.
        provision_workspace(self.path, self.contexts[0], "another-campaign", operator=self.operator, access=self.policy)
        sibling = self.runtime(campaign_id="another-campaign")
        with self.assertRaises(PermissionError):
            sibling.read(run_id)
        self.assertEqual(sibling.drafts.read()["revision"], 1)
        self.assertEqual(first.drafts.read()["revision"], 2)

    def test_conversation_is_bound_to_actor_campaign_client_and_brand(self):
        a, b = self.runtime(), self.runtime(1)
        session, operation = uuid4().hex, uuid4().hex
        catalog = self.catalog(a)
        a.planner.start(DEMO_REQUEST, "simulated", session, operation, catalog, draft_permission="placements")
        a.resume(operation)
        self.assertTrue(a.planner.conversations.read(session)["messages"])
        coworker = AgentRuntime(self.path, replace(self.operator, id="another-person"), context=self.contexts[0],
                                campaign_id="campaign-0", access=self.policy, examples=a.drafts.examples)
        with self.assertRaises(PermissionError):
            coworker.planner.conversations.read(session)
        with self.assertRaises(PermissionError):
            coworker.read(operation)
        with self.assertRaises(PermissionError):
            b.planner.conversations.read(session)
        self.assertEqual(b.planner.conversations.list(), [])
        with self.assertRaises(PermissionError):
            b.planner.start(DEMO_REQUEST, "simulated", session, uuid4().hex,
                            self.catalog(b), draft_permission="placements")
        self.assertEqual(b.drafts.read()["revision"], 1)

    def test_foreign_workspace_installation_and_demo_fallback_are_denied(self):
        c = self.contexts[0]
        for forged in (replace(c, workspace_id="workspace-b"), replace(c, installation_id="install-b")):
            with self.subTest(context=forged), self.assertRaises(PermissionError):
                CampaignDrafts(self.path, False, self.operator, context=forged, campaign_id="campaign-0",
                               access=self.policy, examples=tuple(replace(e, scope=c.scope) for e in EXAMPLES))
        with self.assertRaises(PermissionError):
            provision_workspace(self.path, self.contexts[1], "campaign-0", operator=self.operator, access=self.policy)
        with self.assertRaises(PermissionError):
            CampaignDrafts(self.path, False, self.operator, context=c, campaign_id="campaign-0",
                           examples=tuple(replace(e, scope=c.scope) for e in EXAMPLES))
        with self.assertRaises(PermissionError):
            provision_workspace(self.path, c, "tts-sample", operator=self.operator, access=self.policy)
        with self.assertRaises(PermissionError):
            CampaignDrafts(self.path, False, self.operator, context=c, campaign_id="campaign-0", access=self.policy)

    def test_current_decisions_and_business_approval_both_apply(self):
        runtime = self.runtime()
        _, review = self.prepare(runtime)
        d = runtime.drafts
        self.block(0, "youtube:campaign.draft")
        with self.assertRaises(PermissionError):
            d.save({"campaign_id":d.campaign_id,"revision":2,"placements":[]})
        self.assertEqual(d.read()["revision"], 2)
        self.assertTrue(d.export_setup(d.campaign_id, 2, review["fingerprint"])["approval"])
        self.block(0, "youtube:campaign.approve")
        with self.assertRaises(PermissionError):
            d.approve_package(d.campaign_id, 2, review["fingerprint"])
        with self.assertRaises(PackageConflict):
            d.export_setup(d.campaign_id, 2, "0" * 64)
        self.policy.unavailable = True
        with self.assertRaises(AccessUnavailable):
            d.read()
        with self.assertRaises(AccessUnavailable):
            d.export_setup(d.campaign_id, 2, review["fingerprint"])

    def test_revoked_execution_cannot_resume_or_commit_a_draft(self):
        runtime = self.runtime()
        operation = runtime.start(DEMO_REQUEST)
        self.block(0, "youtube:agent.run")
        with self.assertRaises(PermissionError):
            runtime.resume(operation)
        self.assertEqual(runtime.read(operation)["steps"], [])
        self.assertEqual(runtime.drafts.read()["revision"], 1)

    def test_viewer_visits_reports_and_assets_do_not_cross_scope(self):
        a, b = self.runtime(), self.runtime(1)
        _, ra = self.prepare(a)
        _, rb = self.prepare(b)
        content = package_fingerprint(ra["package"]["groups"][0]["content"])
        va, vb = a.performance.viewer, b.performance.viewer
        visit = va.open_example(EXAMPLES[0].creative_ref, content_fingerprint=content)
        with self.assertRaises(ViewerNotFound):
            vb.record(EXAMPLES[0].creative_ref, visit["visit_id"], EXAMPLES[0].ref, uuid4().hex, "start", "a")
        with self.assertRaises(PermissionError):
            b.drafts.comparison_content(a.drafts.examples[0], content)
        for _ in range(2): va.open_example(EXAMPLES[0].creative_ref, content_fingerprint=content)
        report = a.performance.review(a.drafts.campaign_id, 2, ra["fingerprint"], "balanced")
        other = b.performance.review(b.drafts.campaign_id, 2, rb["fingerprint"], "balanced")
        self.assertEqual(report["local_viewer_activity"]["rows"][0]["arrivals"], 3)
        self.assertEqual(other["local_viewer_activity"]["rows"][0]["arrivals"], 0)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(b.performance.saved_review(db, b.drafts.campaign_id, 2, rb["fingerprint"], report["id"]))

    def test_identical_live_catalog_rows_remain_independently_owned(self):
        catalogs=[]
        for index in range(2):
            c=self.contexts[index]
            d=CampaignDrafts(self.path, True, self.operator, context=c, campaign_id=f"campaign-{index}",
                            access=self.policy, examples=tuple(replace(e,scope=c.scope) for e in EXAMPLES))
            rows=[dict(video_id="SAMPLE00001",description="Licensed tutorial",source="licensed",source_reference="fixture license")]
            catalogs.append((d,d.register_catalog(rows)["SAMPLE00001"]))
        self.assertNotEqual(catalogs[0][1],catalogs[1][1])
        for index,(d,ref) in enumerate(catalogs):
            row=dict(id="SAMPLE00001",title="Licensed tutorial",creative="video-editing",source="licensed",catalog_ref=ref)
            foreign={**row,"catalog_ref":catalogs[1-index][1]}
            with self.assertRaises(ValueError): d.save(dict(campaign_id=d.campaign_id,revision=1,placements=[foreign]))
            self.assertEqual(d.save(dict(campaign_id=d.campaign_id,revision=1,placements=[row]))["revision"],2)

    def test_legacy_history_is_admitted_only_to_the_original_demo(self):
        legacy=self.path.parent/"legacy.sqlite3"
        seed=dict(campaign_id="tts-sample",revision=1,brief=BRIEF,policy=POLICY,placements=[])
        serialized=json.dumps(seed)
        with closing(sqlite3.connect(legacy)) as db,db:
            db.execute("CREATE TABLE campaign_revisions(campaign_id TEXT,revision INTEGER,snapshot TEXT,PRIMARY KEY(campaign_id,revision))")
            db.execute("INSERT INTO campaign_revisions VALUES('tts-sample',1,?)",(serialized,))
            db.execute("INSERT INTO campaign_revisions VALUES('unknown-history',1,?)",(json.dumps({**seed,'campaign_id':'unknown-history'}),))
        self.assertEqual(CampaignDrafts(legacy,False).read(),seed)
        with closing(sqlite3.connect(legacy)) as db:
            self.assertEqual(db.execute("SELECT snapshot FROM campaign_revisions WHERE campaign_id='tts-sample'").fetchone()[0],serialized)
            self.assertEqual(db.execute("SELECT client_id,brand_id FROM campaign_owners WHERE campaign_id='tts-sample'").fetchone(),(LOCAL_BRAND.client_id,LOCAL_BRAND.brand_id))
        with self.assertRaises(PermissionError):
            provision_workspace(legacy,self.contexts[0],"unknown-history",operator=self.operator,access=self.policy)

    def test_legacy_registered_catalog_keeps_its_reference_and_local_owner(self):
        legacy=self.path.parent/"legacy-catalog.sqlite3"
        reference="a"*32
        with closing(sqlite3.connect(legacy)) as db,db:
            db.execute("CREATE TABLE catalog_entries(ref TEXT PRIMARY KEY,video_id TEXT,title TEXT,source TEXT,source_reference TEXT,UNIQUE(video_id,title,source,source_reference))")
            db.execute("INSERT INTO catalog_entries VALUES(?,?,?,?,?)",(reference,"SAMPLE00001","Tutorial","licensed","fixture license"))
        CampaignDrafts(legacy,True)
        with closing(sqlite3.connect(legacy)) as db:
            self.assertEqual(db.execute("SELECT ref,client_id,brand_id,campaign_id FROM catalog_entries").fetchone(),
                             (reference,LOCAL_BRAND.client_id,LOCAL_BRAND.brand_id,"tts-catalog"))

    def prepare_finding_for_fresh_brief(self, runtime):
        _, approved = self.prepare(runtime)
        drafts, viewer = runtime.drafts, runtime.performance.viewer
        campaign, baseline = drafts.campaign_id, approved["fingerprint"]
        content = package_fingerprint(approved["package"]["groups"][0]["content"])
        for _ in range(3):
            viewer.open_example(EXAMPLES[0].creative_ref, content_fingerprint=content)
        review = runtime.performance.review(campaign, 2, baseline, "balanced")
        runtime.performance.save_correction(campaign, 2, baseline, review["id"], "keep_takes", "Keep both.", uuid4().hex)
        review = runtime.performance.review(campaign, 2, baseline, "balanced")
        runtime.resume(runtime.start_next_test(campaign, 2, baseline, review["id"]))
        fingerprint = drafts.review_package(campaign, 3)["fingerprint"]
        drafts.approve_package(campaign, 3, fingerprint)
        test = runtime.instruction_tests.start(campaign, 3, fingerprint, allow_additional_batch=True)
        arrival = 1_700_000_000_000
        with patch("campaign_agent.measurement.time_ns", return_value=arrival * 1_000_000):
            for arm, completions in (("original", 2), ("revised", 18)):
                with patch("campaign_agent.instruction_tests.secrets.choice", return_value=arm):
                    for index in range(20):
                        visit = runtime.instruction_tests.open(test["id"], uuid4().hex)
                        if index < completions:
                            refs = (visit["creative_ref"], visit["visit_id"], visit["example"]["ref"])
                            for take in ("a", "b"):
                                viewer.record(*refs, uuid4().hex, "start", take)
                                viewer.record(*refs, uuid4().hex, "finish", take)
                            viewer.record(*refs, uuid4().hex, "choose", "a")
        with patch("campaign_agent.instruction_tests.time_ns", return_value=(arrival + 300000) * 1_000_000):
            snapshot = runtime.instruction_tests.save_evidence_snapshot(campaign, 3, fingerprint, uuid4().hex)
        finding = runtime.instruction_findings.save(campaign, 3, fingerprint, snapshot_id=snapshot["id"])
        self.assertEqual(finding["decision"]["action"], "reuse")
        drafts.start_brief(campaign, 3, fingerprint, title="Fresh brief", goal="Reuse editing evidence.", context="video-editing")
        return finding, (campaign, 4, drafts.review_package(campaign, 4)["fingerprint"])

    def test_learning_survives_restart_without_crossing_client_or_brand(self):
        finding, target = self.prepare_finding_for_fresh_brief(self.runtime())
        campaign = target[0]
        reopened = self.runtime()
        eligible = reopened.instruction_findings.read(*target)
        self.assertEqual(eligible["finding"], finding)
        for index in (1, 2):
            other = self.runtime(index)
            _, own = self.prepare(other)
            other.drafts.start_brief(other.drafts.campaign_id, 2, own["fingerprint"],
                                    title="Fresh brief", goal="Reuse editing evidence.", context="video-editing")
            foreign_target = (other.drafts.campaign_id, 3, other.drafts.review_package(other.drafts.campaign_id, 3)["fingerprint"])
            self.assertIsNone(other.instruction_findings.read(*foreign_target))
            with self.assertRaises(PackageConflict):
                other.instruction_findings.apply(*foreign_target, finding_id=finding["id"],
                                                correction_id=eligible["correction"]["id"], draft_permission="instruction_test")
            with closing(sqlite3.connect(self.path)) as db, self.assertRaises(ViewerNotFound):
                other.instruction_tests._test(db, finding["test_id"])
            self.assertEqual(other.drafts.read()["revision"], 3)
        with self.assertRaises(PermissionError):
            reopened.instruction_findings.apply(*target, finding_id=finding["id"], correction_id=eligible["correction"]["id"])
        self.block(0, "youtube:campaign.draft")
        with self.assertRaises(PermissionError):
            reopened.instruction_findings.apply(*target, finding_id=finding["id"],
                                               correction_id=eligible["correction"]["id"], draft_permission="instruction_test")
        self.policy.blocked.clear()
        result = reopened.instruction_findings.apply(*target, finding_id=finding["id"],
                                                    correction_id=eligible["correction"]["id"], draft_permission="instruction_test")
        review = reopened.drafts.review_package(campaign, result["revision"])
        self.assertIsNone(review["approval"])
        self.assertEqual(review["package"]["groups"][0]["content"]["instruction"], finding["after"])

    def test_late_revocation_retains_receipt_without_committing_tool(self):
        runtime = self.runtime()
        catalog = self.catalog(runtime)
        session, operation = uuid4().hex, uuid4().hex
        runtime.planner.start(DEMO_REQUEST, "simulated", session, operation, catalog, draft_permission="placements")
        original = runtime.planner.simulator.next_turn
        def revoke(*args):
            receipt = original(*args)
            self.block(0, "youtube:agent.run")
            return receipt
        with patch.object(runtime.planner.simulator, "next_turn", side_effect=revoke), self.assertRaises(PermissionError):
            runtime.resume(operation)
        self.assertEqual(runtime.drafts.read()["revision"], 1)
        self.assertEqual(runtime.read(operation)["steps"], [])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT state FROM planner_turns WHERE run_id=?", (operation,)).fetchone()[0], "received")

    def test_sibling_findings_cannot_shadow_or_retire_each_other(self):
        context = self.contexts[0]
        provision_workspace(self.path, context, "sibling", operator=self.operator, access=self.policy)
        self.policy.campaign_grants = {"buyer-a": {"campaign-0"}, "buyer-b": {"sibling"}}
        a = self.runtime(operator=Operator("buyer-a", frozenset({context.scope})))
        b = self.runtime(campaign_id="sibling", operator=Operator("buyer-b", frozenset({context.scope})))
        finding_a, target_a = self.prepare_finding_for_fresh_brief(a)
        finding_b, target_b = self.prepare_finding_for_fresh_brief(b)
        # These are real supported findings for identical content; B's was saved last.
        with self.subTest(boundary="lookup after restart"):
            reopened = self.runtime(operator=a.operator)
            self.assertEqual(reopened.instruction_findings.read(*target_a)["finding"], finding_a)
            self.assertEqual(b.instruction_findings.read(*target_b)["finding"], finding_b)
        with self.subTest(boundary="foreign retirement"):
            with self.assertRaises(PackageConflict):
                a.instruction_findings.retire(*target_a, finding_id=finding_b["id"])
            with self.assertRaises(PackageConflict):
                b.instruction_findings.retire(*target_b, finding_id=finding_a["id"])
            with closing(sqlite3.connect(self.path)) as db:
                self.assertEqual(db.execute("SELECT retired FROM instruction_findings ORDER BY rowid").fetchall(), [(0,), (0,)])
        with self.subTest(boundary="legacy finding with no verifiable source"):
            orphan = {**finding_a, "id": "e" * 64, "test_id": "f" * 32}
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("INSERT INTO instruction_findings(id,client_id,brand_id,comparison_key,snapshot) "
                           "SELECT ?,client_id,brand_id,comparison_key,? FROM instruction_findings WHERE id=?",
                           (orphan["id"], json.dumps(orphan), finding_a["id"]))
            self.assertEqual(a.instruction_findings.read(*target_a)["finding"], finding_a)
            with self.assertRaises(PackageConflict):
                a.instruction_findings.retire(*target_a, finding_id=orphan["id"])
        with self.subTest(boundary="own retirement does not affect sibling"):
            b.instruction_findings.retire(*target_b, finding_id=finding_b["id"])
            self.assertIsNone(b.instruction_findings.read(*target_b))
            self.assertEqual(a.instruction_findings.read(*target_a)["finding"], finding_a)
            a.instruction_findings.retire(*target_a, finding_id=finding_a["id"])
            self.assertIsNone(a.instruction_findings.read(*target_a))

    def test_brand_membership_cannot_be_replaced_by_an_allow_decision(self):
        limited = Operator(self.operator.id, frozenset({self.contexts[0].scope}))
        for index in (1, 2):
            context = self.contexts[index]
            with self.assertRaises(PermissionError):
                CampaignDrafts(self.path, False, limited, context=context, campaign_id=f"campaign-{index}",
                               access=self.policy, examples=tuple(replace(e, scope=context.scope) for e in EXAMPLES))

    def test_read_only_access_does_not_initialize_a_new_campaign(self):
        self.block(0, "youtube:campaign.draft")
        with self.assertRaises(PermissionError):
            self.runtime()
        with closing(sqlite3.connect(self.path)) as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='campaign_revisions'").fetchone()
            self.assertIsNone(exists)
        self.policy.blocked.clear()
        self.runtime()
        self.block(0, "youtube:campaign.draft")
        self.assertEqual(self.runtime().drafts.read()["revision"], 1)

    def test_provider_dispatch_requires_current_access_and_own_setup(self):
        runtime, other = self.runtime(), self.runtime(1)
        _, approved = self.prepare(runtime)
        _, other_approved = self.prepare(other)
        args = (runtime.drafts.campaign_id, 2, approved["fingerprint"])
        setup = runtime.setup.validate(*args)
        with patch.object(other.setup.provider, "create_paused") as dispatch:
            with self.assertRaises(PackageConflict):
                other.setup.create(other.drafts.campaign_id, 2, other_approved["fingerprint"], setup["id"])
            dispatch.assert_not_called()
        self.block(0, "youtube:setup.manage")
        with patch.object(runtime.setup.provider, "create_paused") as dispatch:
            with self.assertRaises(PermissionError):
                runtime.setup.create(*args, setup["id"])
            dispatch.assert_not_called()
        self.assertEqual(runtime.setup.read(*args)["status"], "validated")

    def test_sibling_campaign_activity_and_freshness_stay_with_the_origin(self):
        context = self.contexts[0]
        provision_workspace(self.path, context, "sibling", operator=self.operator, access=self.policy)
        self.policy.campaign_grants = {"buyer-a": {"campaign-0"}, "buyer-b": {"sibling"}}
        def buyer(actor, campaign):
            return AgentRuntime(self.path, Operator(actor, frozenset({context.scope})), context=context,
                                campaign_id=campaign, access=self.policy,
                                examples=tuple(replace(e, scope=context.scope) for e in EXAMPLES), media_dir=DEMO_MEDIA_DIR)
        a, b = buyer("buyer-a", "campaign-0"), buyer("buyer-b", "sibling")
        with self.assertRaises(PermissionError):
            buyer("buyer-a", "sibling")
        _, ra = self.prepare(a)
        _, rb = self.prepare(b)
        evidence = b.performance.capture_review(b.drafts.campaign_id, 2, rb["fingerprint"], "balanced")
        content = package_fingerprint(ra["package"]["groups"][0]["content"])
        for _ in range(3):
            visit = a.performance.viewer.open_example(EXAMPLES[0].creative_ref, content_fingerprint=content)
        with closing(sqlite3.connect(self.path)) as db, db:
            report_b = b.performance.save_review(db, evidence)
        report_a = a.performance.review(a.drafts.campaign_id, 2, ra["fingerprint"], "balanced")
        self.assertEqual(report_a["local_viewer_activity"]["rows"][0]["arrivals"], 3)
        self.assertEqual(report_b["local_viewer_activity"]["rows"][0]["arrivals"], 0)
        self.assertEqual(report_b["proposal"]["kind"], "collect_activity")
        self.assertEqual(b.drafts.read()["revision"], 2)
        with self.assertRaises(ViewerNotFound):
            b.performance.viewer.open_example(EXAMPLES[0].creative_ref, visit_id=visit["visit_id"], content_fingerprint=content)
        with self.assertRaises(ViewerNotFound):
            b.performance.viewer.record(EXAMPLES[0].creative_ref, visit["visit_id"], EXAMPLES[0].ref, uuid4().hex, "start", "a")

    def test_pre_dispatch_access_failure_releases_setup_for_an_explicit_retry(self):
        for failure, expected in (("deny", PermissionError), ("unavailable", AccessUnavailable), ("error", RuntimeError)):
            with self.subTest(failure=failure):
                runtime = self.runtime(0 if failure == "deny" else 1 if failure == "unavailable" else 2)
                _, approved = self.prepare(runtime)
                args = (runtime.drafts.campaign_id, 2, approved["fingerprint"])
                setup = runtime.setup.validate(*args)
                decide = self.policy.decide
                def revoked_after_reservation(request):
                    with closing(sqlite3.connect(self.path)) as db:
                        creating = db.execute("SELECT 1 FROM campaign_setups WHERE campaign_id=? "
                                              "AND json_extract(snapshot,'$.status')='creating'", (request.campaign_id,)).fetchone()
                    if creating and request.capability == "youtube:setup.manage":
                        if failure == "error":
                            raise RuntimeError("Offline access service failed")
                        return failure
                    return decide(request)
                provider = runtime.setup.provider
                with patch.object(self.policy, "decide", side_effect=revoked_after_reservation), patch.object(provider, "create_paused") as dispatch:
                    with self.assertRaises(expected):
                        runtime.setup.create(*args, setup["id"])
                    dispatch.assert_not_called()
                recovered = runtime.setup.read(*args)
                self.assertEqual(recovered["status"], "validated")
                self.assertIsNone(recovered["approval"])
                self.assertIsNone(provider.readback(setup["id"], setup["plan"]))
                reopened = self.runtime(0 if failure == "deny" else 1 if failure == "unavailable" else 2)
                with patch.object(reopened.setup.provider, "create_paused", wraps=reopened.setup.provider.create_paused) as dispatch:
                    result = reopened.setup.create(*args, setup["id"])
                    self.assertEqual(result["status"], "verified")
                    dispatch.assert_called_once_with(setup["id"], setup["plan"])

    def test_unbound_history_is_not_adopted_by_a_customer_campaign(self):
        a = self.runtime()
        _, approved = self.prepare(a)
        content = package_fingerprint(approved["package"]["groups"][0]["content"])
        customer_visit = a.performance.viewer.open_example(EXAMPLES[0].creative_ref, content_fingerprint=content)
        local_viewer = ViewerMeasurement(self.path)
        local_visit = local_viewer.open_example(EXAMPLES[0].creative_ref, content_fingerprint=content)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("ALTER TABLE viewer_visits DROP COLUMN campaign_id")
        reopened = self.runtime()
        report = reopened.performance.review(a.drafts.campaign_id, 2, approved["fingerprint"], "balanced")
        self.assertEqual(report["local_viewer_activity"]["rows"][0]["arrivals"], 0)
        with self.assertRaises(ViewerNotFound):
            reopened.performance.viewer.open_example(EXAMPLES[0].creative_ref, visit_id=customer_visit["visit_id"],
                                                       content_fingerprint=content)
        # Only the original local demo has a known pre-migration campaign owner.
        local_viewer = ViewerMeasurement(self.path)
        local_viewer.open_example(EXAMPLES[0].creative_ref, visit_id=local_visit["visit_id"], content_fingerprint=content)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT id,campaign_id FROM viewer_visits ORDER BY rowid").fetchall(),
                             [(customer_visit["visit_id"], None), (local_visit["visit_id"], "tts-sample")])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM viewer_events").fetchone()[0], 2)

    def test_unscoped_review_requires_a_fresh_capture_before_preparing_a_test(self):
        runtime = self.runtime()
        _, approved = self.prepare(runtime)
        content = package_fingerprint(approved["package"]["groups"][0]["content"])
        for _ in range(3):
            runtime.performance.viewer.open_example(EXAMPLES[0].creative_ref, content_fingerprint=content)
        args = (runtime.drafts.campaign_id, 2, approved["fingerprint"])
        review = runtime.performance.review(*args, "balanced")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE campaign_performance_reviews SET snapshot=json_set(snapshot," 
                       "'$.local_viewer_activity.attribution','verified_comparison_content') WHERE id=?", (review["id"],))
        self.assertIsNone(runtime.performance.read(*args)["review"])
        with self.assertRaisesRegex(ValueError, "Choose a review"):
            runtime.start_next_test(*args, review["id"])
        self.assertEqual(runtime.drafts.read()["revision"], 2)

    def test_legacy_demo_visits_are_quarantined_when_a_sibling_makes_ownership_ambiguous(self):
        provision_workspace(self.path, LOCAL_CONTEXT, "local-sibling", operator=LOCAL_OPERATOR, access=self.policy)
        viewer = ViewerMeasurement(self.path, campaign_id="local-sibling")
        visit = viewer.open_example(EXAMPLES[0].creative_ref, content_fingerprint="a" * 64)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("ALTER TABLE viewer_visits DROP COLUMN campaign_id")
        local = ViewerMeasurement(self.path)
        row, = local.summarize(LOCAL_BRAND, [(EXAMPLES[0].creative_ref, EXAMPLES[0].ref, "a" * 64)])
        self.assertEqual((row["arrivals"], row["unattributed_arrivals"]), (0, 0))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(db.execute("SELECT campaign_id FROM viewer_visits WHERE id=?", (visit["visit_id"],)).fetchone()[0])

    def test_legacy_run_keeps_its_demo_owner_after_shared_store_migration(self):
        legacy = self.path.parent / "legacy-runs.sqlite3"
        operation = uuid4().hex
        # The old application only created runtime runs in the local sample campaign.
        with closing(sqlite3.connect(legacy)) as db, db:
            db.execute("CREATE TABLE agent_runs(id TEXT PRIMARY KEY,client_id TEXT,brand_id TEXT,actor_id TEXT,request TEXT,status TEXT)")
            db.execute("INSERT INTO agent_runs VALUES(?,?,?,?,?,?)", (operation, LOCAL_BRAND.client_id,
                       LOCAL_BRAND.brand_id, "local-operator", DEMO_REQUEST, "running"))
        local = AgentRuntime(legacy, media_dir=DEMO_MEDIA_DIR)
        local.resume(operation)
        self.assertEqual(local.drafts.read()["revision"], 2)
        provision_workspace(legacy, self.contexts[0], "new-campaign", operator=self.operator, access=self.policy)
        customer = AgentRuntime(legacy, self.operator, context=self.contexts[0], campaign_id="new-campaign",
                                access=self.policy, examples=tuple(replace(e,scope=self.contexts[0].scope) for e in EXAMPLES))
        with self.assertRaises(PermissionError):
            customer.read(operation)
