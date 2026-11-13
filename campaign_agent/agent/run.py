"""An offline campaign preparation run using recorded tool decisions."""
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
from typing import Protocol
from uuid import uuid4

from campaign_agent.access import LOCAL_CONTEXT, LOCAL_OPERATOR
from campaign_agent.creatives import render_instruction_choices
from scripts.campaign_drafts import CampaignDrafts, DEFAULT_DRAFT_PATH, PackageConflict
from campaign_agent.placements import read_catalog, rule_assignment
from campaign_agent.handoff import package_fingerprint
from campaign_agent.measurement import ViewerMeasurement
from campaign_agent.performance import CampaignPerformance
from campaign_agent.instruction_tests import ASSESSMENT_VERSION, InstructionTests, recorded_assessment
from campaign_agent.learning import InstructionFindings
from campaign_agent.adapters.openrouter_reviews import OpenRouterReviews, ReviewInferenceError
from campaign_agent.adapters.openrouter_instructions import OpenRouterInstructions
from campaign_agent.adapters.simulated_setup import SimulatedCampaignSetup
from campaign_agent.campaign_setup import CampaignSetup
from campaign_agent.delivery import CampaignDelivery
from .planner import PlacementAgent

CATALOG = Path(__file__).resolve().parents[2] / "examples/placement-review/catalog.json"
DEMO_REQUEST = "Prepare a YouTube test for ElevenLabs Text to Speech."
NEXT_TEST_REQUEST = "Prepare revised comparison instructions."
REVIEW_TEST_REQUEST = "Review the original and revised instruction test."
RUN_ID = re.compile(r"[0-9a-f]{32}")


class ModelInference(Protocol):
    def next_tool(self, request: str, history: list[dict]) -> str: ...
    def revise_instructions(self, context: dict) -> str: ...
    def assess_instruction_test(self, context: dict) -> dict: ...


class RecordedInference:
    """A fixed recording for the authored demo request."""
    def next_tool(self, request, history):
        if request == REVIEW_TEST_REQUEST:
            return ("load_test_evidence", "assess_instruction_test", "save_test_review", "finish_test_review")[len(history)]
        if request == NEXT_TEST_REQUEST:
            if history and history[0]["result"].get("next_action") == "wait":
                return "wait_for_evidence"
            return ("load_test_context", "draft_instructions", "save_instruction_test", "finish_test")[len(history)]
        if request != DEMO_REQUEST:
            raise ValueError("The offline recording supports the documented demo request only.")
        return ("load_context", "propose_placements", "save_draft", "finish")[len(history)]

    def revise_instructions(self, context):
        """Authored offline responses. Evidence and corrections are supplied as data."""
        options = (
            "Play Take A and Take B all the way through. Then choose the delivery that best fits this scene.",
            "Listen to each take in full. Compare their delivery, then choose the one that best fits this scene.",
        )
        return next(text for text in options if text != context["comparison"]["instruction"])

    def assess_instruction_test(self, context):
        return recorded_assessment(context)


class AgentRuntime:
    def __init__(self, path=DEFAULT_DRAFT_PATH, operator=LOCAL_OPERATOR, model=None, *, media_dir=None,
                 openrouter_models=(), review_transport=None, openrouter_draft_models=(), draft_transport=None,
                 main_models=(), main_transport=None, planner_simulator=None, placement_classifier=None, reporting=None,
                 demo_scenario=None, context=LOCAL_CONTEXT, campaign_id=None, access=None, examples=None, viewer_links=None):
        operator.require_brand(context.scope)
        self.operator = operator
        self.scope = context.scope
        self.path = Path(path)
        self.drafts = CampaignDrafts(self.path, live=False, operator=operator, media_dir=media_dir,
                                     context=context, campaign_id=campaign_id, access=access, examples=examples)
        self.setup = CampaignSetup(self.drafts, SimulatedCampaignSetup(self.path), viewer_links=viewer_links)
        self.performance = CampaignPerformance(self.drafts, ViewerMeasurement(self.path, self.drafts.examples,
                                                                            campaign_id=self.drafts.campaign_id))
        self.delivery = CampaignDelivery(self.drafts, self.setup, self.performance, reporting, demo_scenario=demo_scenario)
        self.instruction_tests = InstructionTests(self.drafts, self.performance.viewer, self.performance)
        self.instruction_findings = InstructionFindings(self.instruction_tests)
        self.model = model or RecordedInference()
        self.openrouter = OpenRouterReviews(openrouter_models, transport=review_transport)
        self.openrouter_drafts = OpenRouterInstructions(openrouter_draft_models, transport=draft_transport)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL, request TEXT NOT NULL, status TEXT NOT NULL, campaign_id TEXT NOT NULL
                )
            """)
            if "campaign_id" not in {row[1] for row in db.execute("PRAGMA table_info(agent_runs)")}:
                db.execute("ALTER TABLE agent_runs ADD COLUMN campaign_id TEXT")
                db.execute("UPDATE agent_runs SET campaign_id='tts-sample' WHERE client_id=? AND brand_id=?",
                           (LOCAL_CONTEXT.scope.client_id, LOCAL_CONTEXT.scope.brand_id))
            db.execute("""
                CREATE TABLE IF NOT EXISTS agent_steps (
                    run_id TEXT NOT NULL, position INTEGER NOT NULL, tool TEXT NOT NULL,
                    result TEXT NOT NULL, PRIMARY KEY (run_id, position)
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS agent_test_sources (
                    run_id TEXT PRIMARY KEY, source TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS agent_review_inference (
                    run_id TEXT PRIMARY KEY, settings TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending', receipt TEXT, error TEXT
                )
            """)

        self.planner = PlacementAgent(self, main_models, transport=main_transport,
                                      simulator=planner_simulator, classifier=placement_classifier)

    def require(self, capability):
        self.operator.require_brand(self.scope)
        if self.operator.id != self.drafts.operator.id:
            raise PermissionError("The run actor changed. Resolve a new application context.")
        self.drafts.require(capability)

    def start(self, request, *, run_id=None):
        self.require("youtube:agent.run")
        if request != DEMO_REQUEST:
            raise ValueError("The offline recording supports the documented demo request only.")
        self.require("youtube:campaign.read")
        run_id = uuid4().hex if run_id is None else run_id
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise ValueError("Invalid run ID.")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO agent_runs VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
                       (run_id, self.scope.client_id, self.scope.brand_id,
                        self.operator.id, request, "running", self.drafts.campaign_id))
            self._owned_run(db, run_id)
        return run_id

    def start_next_test(self, campaign_id, revision, fingerprint, review_id, *,
                        mode="offline", model=None, operation_id=None):
        self.drafts._package_scope(campaign_id, revision)
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
               for value in (fingerprint, review_id)):
            raise ValueError("Choose a valid performance review.")
        source = {"campaign_id": campaign_id, "revision": revision,
                  "fingerprint": fingerprint, "review_id": review_id}
        return self._start_test_preparation(source, mode=mode, model=model, operation_id=operation_id)

    def start_experiment_next_test(self, test_id, review_id, *, mode="offline", model=None, operation_id=None):
        if (not isinstance(test_id, str) or not RUN_ID.fullmatch(test_id)
                or not isinstance(review_id, str) or not re.fullmatch(r"[0-9a-f]{64}", review_id)):
            raise ValueError("Choose a valid instruction-test assessment.")
        return self._start_test_preparation({"test_id": test_id, "review_id": review_id},
                                            mode=mode, model=model, operation_id=operation_id)

    def _next_test_context(self, db, source):
        if "test_id" in source:
            return self.instruction_tests.next_test_context(db, **source)
        return self.performance.instruction_test_context(db, **source)

    def _start_test_preparation(self, source, *, mode, model, operation_id):
        self.require("youtube:agent.run")
        self.require("youtube:campaign.read")
        if not isinstance(mode, str) or mode not in {"offline", "openrouter"}:
            raise ValueError("Choose offline or OpenRouter drafting.")
        if mode == "offline" and model is not None:
            raise ValueError("Offline drafts do not use provider settings.")
        settings = {"mode": "offline"} if mode == "offline" else self.openrouter_drafts.settings(model)
        if mode == "openrouter" and operation_id is None:
            raise ValueError("Use a valid drafting operation ID.")
        identity = {"client": self.scope.client_id, "brand": self.scope.brand_id,
                    "actor": self.operator.id, "request": NEXT_TEST_REQUEST}
        if operation_id is not None:
            if not isinstance(operation_id, str) or not RUN_ID.fullmatch(operation_id):
                raise ValueError("Use a valid drafting operation ID.")
            identity["operation_id"] = operation_id
        else:
            identity["source"] = source
        run_id = package_fingerprint(identity)[:32]
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT source FROM agent_test_sources WHERE run_id = ?", (run_id,)).fetchone()
            if existing is not None:
                self._owned_run(db, run_id)
                saved = db.execute("SELECT settings FROM agent_review_inference WHERE run_id = ?", (run_id,)).fetchone()
                if json.loads(existing[0]) != source or (json.loads(saved[0]) if saved else {"mode": "offline"}) != settings:
                    raise ValueError("This drafting operation was already used for a different request.")
                return run_id
            self._next_test_context(db, source)
            db.execute("INSERT INTO agent_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (run_id, self.scope.client_id, self.scope.brand_id,
                        self.operator.id, NEXT_TEST_REQUEST, "running", self.drafts.campaign_id))
            db.execute("INSERT INTO agent_test_sources VALUES (?, ?)", (run_id, json.dumps(source)))
            db.execute("INSERT INTO agent_review_inference (run_id, settings) VALUES (?, ?)",
                       (run_id, json.dumps(settings)))
        return run_id

    def _owned_run(self, db, run_id):
        self.require("youtube:campaign.read")
        row = db.execute(
            "SELECT request, status FROM agent_runs WHERE id = ? AND client_id = ? "
            "AND brand_id = ? AND actor_id = ? AND campaign_id = ?",
            (run_id, self.scope.client_id, self.scope.brand_id, self.operator.id, self.drafts.campaign_id),
        ).fetchone()
        if row is None:
            raise PermissionError("The run is unavailable to this operator.")
        return row

    def start_instruction_review(self, test_id, *, mode="offline", model=None, operation_id=None):
        self.require("youtube:agent.run")
        self.require("youtube:campaign.read")
        if not isinstance(mode, str) or mode not in {"offline", "openrouter"}:
            raise ValueError("Choose offline or OpenRouter reviews.")
        if mode == "offline" and model is not None:
            raise ValueError("Offline reviews do not use provider settings.")
        settings = {"mode": "offline"}
        if mode == "openrouter":
            settings = self.openrouter.settings(model)
            if operation_id is None:
                raise ValueError("Use a valid review operation ID.")
        if operation_id is not None:
            if not isinstance(operation_id, str) or not RUN_ID.fullmatch(operation_id):
                raise ValueError("Use a valid review operation ID.")
            run_id = package_fingerprint({"scope": vars(self.scope), "actor": self.operator.id,
                                          "request": REVIEW_TEST_REQUEST, "operation_id": operation_id})[:32]
            with closing(sqlite3.connect(self.path)) as db:
                row = db.execute(
                    "SELECT s.source, i.settings FROM agent_test_sources s JOIN agent_review_inference i "
                    "ON i.run_id = s.run_id WHERE s.run_id = ?", (run_id,),
                ).fetchone()
                if row:
                    self._owned_run(db, run_id)
                    if json.loads(row[0])["test_id"] != test_id or json.loads(row[1]) != settings:
                        raise ValueError("This review operation was already used for a different request.")
                    return run_id
        context = self.instruction_tests.review_context(test_id)
        if operation_id is None:
            run_id = package_fingerprint({
                "actor": self.operator.id, "request": REVIEW_TEST_REQUEST, "context": context,
                "assessment_version": ASSESSMENT_VERSION,
            })[:32]
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO agent_runs VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                       (run_id, self.scope.client_id, self.scope.brand_id,
                        self.operator.id, REVIEW_TEST_REQUEST, "running", self.drafts.campaign_id))
            self._owned_run(db, run_id)
            db.execute("INSERT INTO agent_test_sources VALUES (?, ?) ON CONFLICT DO NOTHING",
                       (run_id, json.dumps(context)))
            existing = db.execute("SELECT settings FROM agent_review_inference WHERE run_id = ?", (run_id,)).fetchone()
            if existing and json.loads(existing[0]) != settings:
                raise ValueError("This review operation was already used for a different request.")
            source = json.loads(db.execute("SELECT source FROM agent_test_sources WHERE run_id = ?", (run_id,)).fetchone()[0])
            if source["test_id"] != test_id:
                raise ValueError("This review operation was already used for a different request.")
            db.execute("INSERT INTO agent_review_inference (run_id, settings) VALUES (?, ?) ON CONFLICT DO NOTHING",
                       (run_id, json.dumps(settings)))
        return run_id

    def resume(self, run_id, max_steps=4):
        self.require("youtube:agent.run")
        if type(max_steps) is not int or not 0 <= max_steps <= 4:
            raise ValueError("The step budget must be between zero and four.")
        if self.planner.owns(run_id):
            return self.planner.resume(run_id, max_steps=max_steps)
        for _ in range(max_steps):
            self.require("youtube:campaign.read")
            if self._resume_openrouter(run_id):
                continue
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                run = self._owned_run(db, run_id)
                history = [
                    {"tool": tool, "result": json.loads(result)}
                    for tool, result in db.execute(
                        "SELECT tool, result FROM agent_steps WHERE run_id = ? ORDER BY position", (run_id,)
                    )
                ]
                if run[1] in {"ready_for_review", "waiting_for_evidence"}:
                    return self.read(run_id)
                tool = self.model.next_tool(run[0], history)
                self.require("youtube:agent.run")
                if run[0] == REVIEW_TEST_REQUEST:
                    result = self._dispatch_instruction_review(db, run_id, tool, history)
                elif run[0] == NEXT_TEST_REQUEST:
                    result = self._dispatch_next_test(db, run_id, tool, history)
                else:
                    result = self._dispatch(db, tool, history)
                self.require("youtube:agent.run")
                db.execute("INSERT INTO agent_steps VALUES (?, ?, ?, ?)",
                           (run_id, len(history), tool, json.dumps(result)))
                if tool in {"finish", "finish_test", "finish_test_review", "wait_for_evidence"}:
                    db.execute("UPDATE agent_runs SET status = ? WHERE id = ?",
                               ("waiting_for_evidence" if tool == "wait_for_evidence" else "ready_for_review", run_id))
        return self.read(run_id)

    def read(self, run_id):
        if self.planner.owns(run_id):
            return self.planner.read(run_id)
        self.require("youtube:campaign.read")
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("BEGIN")
            request, status = self._owned_run(db, run_id)
            steps = [{"tool": tool, "result": json.loads(result)} for tool, result in db.execute(
                "SELECT tool, result FROM agent_steps WHERE run_id = ? ORDER BY position", (run_id,)
            )]
            inference = db.execute(
                "SELECT settings, state, receipt, error FROM agent_review_inference WHERE run_id = ?", (run_id,),
            ).fetchone()
            result = {"run_id": run_id, "request": request, "status": status, "steps": steps}
            if inference:
                receipt = json.loads(inference[2]) if inference[2] else None
                result["inference"] = {"settings": json.loads(inference[0]), "state": inference[1],
                                       "receipt": receipt["inference"] if receipt else None, "error": inference[3]}
            return result

    def _resume_openrouter(self, run_id):
        """Reserve a single request, call outside SQLite, and persist its receipt before the step."""
        self.require("youtube:agent.run")
        self.require("youtube:campaign.read")
        receipt = None
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            request, _ = self._owned_run(db, run_id)
            row = db.execute(
                "SELECT settings, state, receipt, error FROM agent_review_inference WHERE run_id = ?", (run_id,),
            ).fetchone()
            count = db.execute("SELECT COUNT(*) FROM agent_steps WHERE run_id = ?", (run_id,)).fetchone()[0]
            if request not in {REVIEW_TEST_REQUEST, NEXT_TEST_REQUEST} or count != 1 or not row:
                return False
            settings = json.loads(row[0])
            if settings["mode"] != "openrouter":
                return False
            source = json.loads(db.execute("SELECT source FROM agent_test_sources WHERE run_id = ?", (run_id,)).fetchone()[0])
            context = self._inference_context(db, request, source)
            if request == NEXT_TEST_REQUEST and context.get("next_action") == "wait":
                return False
            adapter = self.openrouter if request == REVIEW_TEST_REQUEST else self.openrouter_drafts
            if row[1] == "received":
                receipt = json.loads(row[2])
            elif row[1] == "pending":
                adapter.require_available(settings)
                db.execute("UPDATE agent_review_inference SET state = 'requested' WHERE run_id = ?", (run_id,))
            else:
                raise ReviewInferenceError(row[3] or
                    "This request is in progress or its outcome is unknown. Start a new operation to retry.")
        if receipt is None:
            try:
                receipt = (adapter.assess_instruction_test(context, settings) if request == REVIEW_TEST_REQUEST
                           else adapter.draft_instructions(context, settings))
                receipt["inference"]["run_id"] = run_id
            except ReviewInferenceError as exc:
                with closing(sqlite3.connect(self.path)) as db, db:
                    db.execute("UPDATE agent_review_inference SET state = 'failed', error = ? WHERE run_id = ?",
                               (str(exc), run_id))
                raise
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("UPDATE agent_review_inference SET state = 'received', receipt = ? WHERE run_id = ?",
                           (json.dumps(receipt), run_id))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self.require("youtube:agent.run")
            self._owned_run(db, run_id)
            if db.execute("SELECT 1 FROM agent_steps WHERE run_id = ? AND position = 1", (run_id,)).fetchone():
                return True
            self._inference_context(db, request, source)
            usage = receipt["inference"]["usage"]
            if ((usage["cost_usd"] is not None and usage["cost_usd"] > 0)
                    or (usage["output_tokens"] is not None and usage["output_tokens"] > settings["max_output_tokens"])):
                raise ReviewInferenceError("The provider reported usage beyond the inference limits. Its receipt was retained.")
            try:
                if request == REVIEW_TEST_REQUEST:
                    assessment = self.instruction_tests.validate_assessment(context, receipt["assessment"])
                    tool = "assess_instruction_test"
                    result = {"assessment": assessment, "inference": receipt["inference"]}
                else:
                    draft = receipt["draft"]
                    instruction = self.drafts.validate_instruction(
                        render_instruction_choices(draft), context["comparison"]["instruction"],
                    )
                    tool = "draft_instructions"
                    result = {"instruction": instruction,
                              "inference": {**receipt["inference"], "wording_choices": draft}}
            except ValueError:
                raise ReviewInferenceError(
                    "The model output did not pass validation. Start a new operation to retry."
                ) from None
            db.execute("INSERT INTO agent_steps VALUES (?, 1, ?, ?)", (run_id, tool, json.dumps(result)))
        return True

    def _inference_context(self, db, request, source):
        if request == REVIEW_TEST_REQUEST:
            self.instruction_tests.require_review_context(db, source)
            return source
        return self._next_test_context(db, source)

    def _dispatch_instruction_review(self, db, run_id, tool, history):
        expected = ("load_test_evidence", "assess_instruction_test", "save_test_review", "finish_test_review")
        if len(history) >= len(expected) or tool != expected[len(history)]:
            raise ValueError("The requested tool is unavailable at this step.")
        context = json.loads(db.execute("SELECT source FROM agent_test_sources WHERE run_id = ?", (run_id,)).fetchone()[0])
        if tool == "load_test_evidence":
            return context
        if tool == "assess_instruction_test":
            return self.instruction_tests.validate_assessment(
                history[0]["result"], self.model.assess_instruction_test(history[0]["result"]),
            )
        if tool == "save_test_review":
            result = history[1]["result"]
            inference = result.get("inference") if "assessment" in result else {
                "mode": "offline", "model": "recorded", "prompt_version": "offline-review-v2",
                "evidence_id": package_fingerprint(history[0]["result"]),
                "run_id": run_id,
                "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0},
            }
            return self.instruction_tests.save_review(
                db, history[0]["result"], result.get("assessment", result), inference=inference,
            )
        return {"campaign_id": context["campaign_id"], "revision": context["revision"], "ambiguous": [],
                "message": "Instruction-test assessment saved."}

    def _dispatch_next_test(self, db, run_id, tool, history):
        expected = ("load_test_context", "draft_instructions", "save_instruction_test", "finish_test")
        if history and history[0]["result"].get("next_action") == "wait":
            expected = ("load_test_context", "wait_for_evidence")
        if len(history) >= len(expected) or tool != expected[len(history)]:
            raise ValueError("The requested tool is unavailable at this step.")
        source = json.loads(db.execute("SELECT source FROM agent_test_sources WHERE run_id = ?", (run_id,)).fetchone()[0])
        if tool == "load_test_context":
            return self._next_test_context(db, source)
        if tool == "wait_for_evidence":
            context = self._next_test_context(db, source)
            if context["next_action"] != "wait":
                raise PackageConflict("The assessment changed. Start from a current review.")
            return {"campaign_id": context["package"]["campaign_id"], "revision": context["package"]["revision"],
                    "ambiguous": [], "outcome": "waiting", "review_id": source["review_id"],
                    "message": context["experiment_review"]["assessment"]["reason"]}
        if tool == "draft_instructions":
            self._next_test_context(db, source)
            context = history[0]["result"]
            instruction = self.drafts.validate_instruction(
                self.model.revise_instructions(context), context["comparison"]["instruction"],
            )
            return {"instruction": instruction}
        if tool == "save_instruction_test":
            result = history[1]["result"]
            save = self.instruction_tests.save_next_test if "test_id" in source else self.performance.save_instruction_test
            return save(db, source, result["instruction"], inference=result.get("inference"))
        draft = history[2]["result"]
        return {"campaign_id": draft["campaign_id"], "revision": draft["revision"], "ambiguous": [],
                "message": "Revised comparison instructions prepared for approval."}

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
            selected.extend(row for row in proposals
                            if row["creative"] in context["brief"]["contexts"] and row["id"] not in existing)
            return self.drafts.save({"campaign_id": context["campaign_id"],
                                     "revision": context["revision"], "placements": selected},
                                    connection=db)
        draft = history[2]["result"]
        return {"campaign_id": draft["campaign_id"], "revision": draft["revision"],
                "ambiguous": [row for row in history[1]["result"] if row["creative"] == "review"],
                "message": "Draft prepared for review. Placements are fictional."}
