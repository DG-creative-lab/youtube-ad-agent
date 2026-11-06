import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import placement_review


CATALOG = Path(__file__).resolve().parents[1] / "examples/placement-review/catalog.json"


class PlacementReviewTests(unittest.TestCase):
    def test_viewer_requires_a_fixed_port_separate_from_planner(self):
        with patch.object(placement_review, "ThreadingHTTPServer", side_effect=AssertionError("Unexpected socket bind")):
            for viewer_port, error in ((0, "fixed viewer port"), (8765, "different ports")):
                with self.subTest(viewer_port=viewer_port):
                    with self.assertRaisesRegex(ValueError, error):
                        placement_review.serve(8765, live=False, viewer_port=viewer_port)

    def test_sample_search_pages_are_repeatable_and_disjoint(self):
        first = placement_review.demo_search("editing", None)
        self.assertEqual(first, placement_review.demo_search("editing", None))
        second = placement_review.demo_search("editing", first["nextPageToken"])
        first_ids = {item["id"]["videoId"] for item in first["items"]}
        second_ids = {item["id"]["videoId"] for item in second["items"]}
        self.assertEqual(len(first_ids | second_ids), 100)
        self.assertNotIn("nextPageToken", second)

    def test_default_assignment_routes_two_matches_and_flags_ambiguity_offline(self):
        output = io.StringIO()
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fake-key"}):
            with patch.object(placement_review, "urlopen") as request:
                with redirect_stdout(output):
                    placement_review.assign(CATALOG, jev_limit=None)
        request.assert_not_called()
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(
            [(row["video_id"], row["route"], row["status"]) for row in rows],
            [
                ("SAMPLE00001", "video-editing", "proposed"),
                ("SAMPLE00002", "audiobook", "proposed"),
                ("SAMPLE00003", "review", "needs_review"),
                ("SAMPLE00004", "review", "needs_review"),
            ],
        )
        self.assertTrue(all(row["source"] == "synthetic" for row in rows))

    def test_catalog_rejects_unapproved_provenance_and_duplicate_identity(self):
        row = {
            "video_id": "SAMPLE00001",
            "description": "An editing tutorial",
            "source": "synthetic",
        }
        with TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.json"
            for rows in ([{**row, "source": "youtube_api"}], [row, row]):
                with self.subTest(rows=rows):
                    catalog.write_text(json.dumps(rows))
                    with self.assertRaises(ValueError):
                        placement_review.read_catalog(catalog)

    def test_model_budget_denial_precedes_network_access(self):
        with patch.object(placement_review, "urlopen") as request:
            with self.assertRaisesRegex(ValueError, "covers the catalog"):
                placement_review.assign(CATALOG, jev_limit=3)
        request.assert_not_called()

    def test_low_confidence_model_response_abstains(self):
        payload = {
            "answers": {
                "placement": {
                    "choice": "video-editing",
                    "probabilities": {"video-editing": 0.65, "audiobook": 0.3, "review": 0.05},
                },
            },
        }
        response = io.BytesIO(json.dumps(payload).encode())
        with patch.object(placement_review, "urlopen", return_value=response) as request:
            route, _, _ = placement_review.jev_assignment("Video editing tutorial", "fake-key")
        self.assertEqual(route, "review")
        sent = json.loads(request.call_args.args[0].data)
        self.assertEqual(sent["state"], {"video_description": "Video editing tutorial"})
