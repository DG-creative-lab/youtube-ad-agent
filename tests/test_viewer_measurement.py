from contextlib import closing
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from campaign_agent.access import BrandScope, LOCAL_BRAND, Operator
from campaign_agent.creatives import EXAMPLES
from campaign_agent.measurement import ViewerMeasurement, ViewerNotFound
from scripts.campaign_drafts import CampaignDrafts


EDIT, BOOK = EXAMPLES


class ViewerMeasurementTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "drafts.sqlite3"
        self.viewer = ViewerMeasurement(self.path)
        self.visit = self.viewer.open_example(EDIT.creative_ref)["visit_id"]

    def event(self, kind, take, event_id=None, example=EDIT):
        return self.viewer.record(
            EDIT.creative_ref, self.visit, example.ref, event_id or uuid4().hex, kind, take,
        )

    def test_completes_once_and_keeps_choice_on_reopen(self):
        with self.assertRaisesRegex(ValueError, "Start this take"):
            self.event("finish", "a")
        self.event("start", "a")
        self.event("finish", "a")
        with self.assertRaisesRegex(ValueError, "Finish both"):
            self.event("choose", "a")
        self.event("start", "b")
        self.event("finish", "b")
        event_id = uuid4().hex
        self.assertTrue(self.event("choose", "b", event_id)["complete"])
        self.assertEqual(self.event("choose", "b", event_id)["choice"], "b")
        with self.assertRaisesRegex(ValueError, "different action"):
            self.event("choose", "a", event_id)
        self.event("choose", "a")
        reopened = ViewerMeasurement(self.path)
        state = reopened.open_example(EDIT.creative_ref, EDIT.ref, self.visit)
        self.assertEqual((state["finished"], state["choice"], state["complete"]), (["a", "b"], "a", True))
        with closing(reopened.connect()) as db:
            self.assertEqual(db.execute("SELECT first_choice FROM viewer_completions").fetchall(), [("b",)])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM viewer_events WHERE kind = 'arrival'").fetchone(), (1,))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM viewer_events WHERE kind = 'choose'").fetchone(), (2,))

    def test_switching_examples_keeps_original_attribution_and_separate_progress(self):
        self.event("start", "a")
        self.event("finish", "a")
        with self.assertRaises(ViewerNotFound):
            self.event("start", "a", example=BOOK)
        switched = self.viewer.open_example(EDIT.creative_ref, BOOK.ref, self.visit)
        self.assertEqual(switched["finished"], [])
        self.event("start", "b", example=BOOK)
        self.event("finish", "b", example=BOOK)
        self.assertEqual(self.viewer.open_example(EDIT.creative_ref, EDIT.ref, self.visit)["finished"], ["a"])
        with closing(self.viewer.connect()) as db:
            self.assertEqual(db.execute("SELECT client_id, brand_id, creative_ref FROM viewer_visits").fetchall(),
                             [(LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, EDIT.creative_ref)])
            self.assertEqual(db.execute(
                "SELECT example_ref, take FROM viewer_events WHERE kind = 'finish' ORDER BY seq",
            ).fetchall(), [(EDIT.ref, "a"), (BOOK.ref, "b")])

    def test_rejects_cross_scope_examples_visits_and_planner_access(self):
        scopes = (BrandScope("other-client", LOCAL_BRAND.brand_id), BrandScope(LOCAL_BRAND.client_id, "other-brand"))
        foreign = tuple(replace(BOOK, ref=f"other-{i}", creative_ref=f"other-cut-{i}", scope=scope)
                        for i, scope in enumerate(scopes))
        viewer = ViewerMeasurement(self.path, (*EXAMPLES, *foreign))
        for target in foreign:
            with self.subTest(scope=target.scope):
                self.assertNotIn(target.ref, {item["ref"] for item in viewer.open_example(
                    EDIT.creative_ref, visit_id=self.visit,
                )["examples"]})
                with self.assertRaises(ViewerNotFound):
                    viewer.open_example(EDIT.creative_ref, target.ref, self.visit)
                with self.assertRaises(ViewerNotFound):
                    viewer.record(EDIT.creative_ref, self.visit, target.ref, uuid4().hex, "start", "a")
                with self.assertRaises(ViewerNotFound):
                    viewer.record(target.creative_ref, self.visit, target.ref, uuid4().hex, "start", "a")
                with self.assertRaises(PermissionError):
                    CampaignDrafts(self.path, False, Operator("restricted", frozenset({target.scope})))
        with self.assertRaises(ViewerNotFound):
            viewer.open_example(BOOK.creative_ref, BOOK.ref, self.visit)
        with closing(viewer.connect()) as db:
            self.assertEqual(db.execute("SELECT kind FROM viewer_events").fetchall(), [("arrival",)])
