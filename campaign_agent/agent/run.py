"""An offline campaign preparation run using recorded tool decisions."""
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
from typing import Protocol
from uuid import uuid4

from campaign_agent.access import LOCAL_BRAND, LOCAL_OPERATOR
from scripts.campaign_drafts import CampaignDrafts, DEFAULT_DRAFT_PATH
from campaign_agent.placements import read_catalog, rule_assignment

CATALOG = Path(__file__).resolve().parents[2] / "examples/placement-review/catalog.json"
DEMO_REQUEST = "Prepare a YouTube test for ElevenLabs Text to Speech."
RUN_ID = re.compile(r"[0-9a-f]{32}")


class ModelInference(Protocol):
    def next_tool(self, request: str, history: list[dict]) -> str: ...


class RecordedInference:
    """A fixed recording for the authored demo request."""
    def next_tool(self, request, history):
        if request != DEMO_REQUEST:
            raise ValueError("The offline recording supports the documented demo request only.")
        return ("load_context", "propose_placements", "save_draft", "finish")[len(history)]


class AgentRuntime:
    def __init__(self, path=DEFAULT_DRAFT_PATH, operator=LOCAL_OPERATOR, model=None):
        operator.require_brand(LOCAL_BRAND)
        self.operator = operator
        self.path = Path(path)
        self.drafts = CampaignDrafts(self.path, live=False, operator=operator)
        self.model = model or RecordedInference()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL, request TEXT NOT NULL, status TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS agent_steps (
                    run_id TEXT NOT NULL, position INTEGER NOT NULL, tool TEXT NOT NULL,
                    result TEXT NOT NULL, PRIMARY KEY (run_id, position)
                )
            """)

    def start(self, request, *, run_id=None):
        if request != DEMO_REQUEST:
            raise ValueError("The offline recording supports the documented demo request only.")
        self.operator.require_brand(LOCAL_BRAND)
        run_id = uuid4().hex if run_id is None else run_id
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise ValueError("Invalid run ID.")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO agent_runs VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
                       (run_id, LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id,
                        self.operator.id, request, "running"))
            self._owned_run(db, run_id)
        return run_id

    def _owned_run(self, db, run_id):
        row = db.execute(
            "SELECT request, status FROM agent_runs WHERE id = ? AND client_id = ? "
            "AND brand_id = ? AND actor_id = ?",
            (run_id, LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, self.operator.id),
        ).fetchone()
        if row is None:
            raise PermissionError("The run is unavailable to this operator.")
        return row

    def resume(self, run_id, max_steps=4):
        if type(max_steps) is not int or not 0 <= max_steps <= 4:
            raise ValueError("The step budget must be between zero and four.")
        for _ in range(max_steps):
            self.operator.require_brand(LOCAL_BRAND)
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                run = self._owned_run(db, run_id)
                history = [
                    {"tool": tool, "result": json.loads(result)}
                    for tool, result in db.execute(
                        "SELECT tool, result FROM agent_steps WHERE run_id = ? ORDER BY position", (run_id,)
                    )
                ]
                if run[1] == "ready_for_review":
                    return {"run_id": run_id, "status": run[1], "steps": history}
                tool = self.model.next_tool(run[0], history)
                result = self._dispatch(db, tool, history)
                db.execute("INSERT INTO agent_steps VALUES (?, ?, ?, ?)",
                           (run_id, len(history), tool, json.dumps(result)))
                if tool == "finish":
                    db.execute("UPDATE agent_runs SET status = ? WHERE id = ?",
                               ("ready_for_review", run_id))
        return self.read(run_id)

    def read(self, run_id):
        self.operator.require_brand(LOCAL_BRAND)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("BEGIN")
            _, status = self._owned_run(db, run_id)
            steps = [{"tool": tool, "result": json.loads(result)} for tool, result in db.execute(
                "SELECT tool, result FROM agent_steps WHERE run_id = ? ORDER BY position", (run_id,)
            )]
            return {"run_id": run_id, "status": status, "steps": steps}

    def _dispatch(self, db, tool, history):
        # Each decision is constrained to the next capability in this recorded workflow.
        expected = ("load_context", "propose_placements", "save_draft", "finish")
        if len(history) >= len(expected) or tool != expected[len(history)]:
            raise ValueError("The requested tool is unavailable at this step.")
        if tool == "load_context":
            return self.drafts._read(db)
        if tool == "propose_placements":
            proposals = []
            for row in read_catalog(CATALOG):
                route = rule_assignment(row["description"])
                proposals.append({"id": row["video_id"], "title": row["description"],
                                  "creative": route, "source": row["source"]})
            return proposals
        if tool == "save_draft":
            context, proposals = history[0]["result"], history[1]["result"]
            selected = list(context["placements"])
            existing = {row["id"] for row in selected}
            selected.extend(row for row in proposals if row["creative"] != "review" and row["id"] not in existing)
            return self.drafts.save({"campaign_id": context["campaign_id"],
                                     "revision": context["revision"], "placements": selected},
                                    connection=db)
        draft = history[2]["result"]
        return {"campaign_id": draft["campaign_id"], "revision": draft["revision"],
                "ambiguous": [row for row in history[1]["result"] if row["creative"] == "review"],
                "message": "Draft prepared for review. Placements are fictional."}
