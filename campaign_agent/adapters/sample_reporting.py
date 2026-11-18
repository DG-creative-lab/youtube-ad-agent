"""Read authored performance scenarios from the bundled fixture."""
import json
from pathlib import Path


DELIVERY_FIXTURE = Path(__file__).resolve().parents[2] / "examples/tts-performance/delivery.json"


class SampleCampaignReporting:
    def __init__(self):
        self.fixture = json.loads(DELIVERY_FIXTURE.read_text())

    def scenarios(self):
        return [{"id": key, "label": value["label"]} for key, value in self.fixture["scenarios"].items()]

    def snapshot(self, scenario, creatives):
        selected = self.fixture["scenarios"].get(scenario)
        if selected is None:
            raise ValueError("Choose a sample delivery scenario.")
        rows = [
            {"creative_version": creative, "metrics": selected["rows"].get(creative)}
            for creative in creatives
        ]
        return {
            "fixture_id": self.fixture["id"], "source": self.fixture["source"], "grain": self.fixture["grain"],
            "window": self.fixture["window"], "scenario": scenario, "label": selected["label"],
            "coverage": "complete" if all(row["metrics"] is not None for row in rows) else "partial",
            "rows": rows,
        }
