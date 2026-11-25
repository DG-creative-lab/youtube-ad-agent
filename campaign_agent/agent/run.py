"""Recorded campaign preparation and structured review and drafting runs."""
from copy import deepcopy
import json
import math
import re
from typing import Callable, Protocol

from campaign_agent.ports.agent_runs import AgentRunReader, AgentRunStorage
from campaign_agent.ports.drafts import DraftRepository
from campaign_agent.ports.evidence import EvidenceReader, EvidenceWriter
from campaign_agent.ports.planning import STRUCTURED_MAX_OUTPUT_TOKENS
from campaign_agent.creatives import render_instruction_choices
from campaign_agent.domain.errors import PackageConflict
from campaign_agent.placements import read_catalog, rule_assignment
from campaign_agent.handoff import package_fingerprint
from campaign_agent.instruction_tests import ASSESSMENT_VERSION, recorded_assessment
from campaign_agent.domain.inference_errors import ReviewInferenceError

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
    def __init__(self, drafts, model: ModelInference, *, setup, performance, delivery,
                 instruction_tests, instruction_findings, reviewer, drafter, demo_catalog, web,
                 run_storage: AgentRunStorage, new_run_id: Callable[[], str]):
        self.foreground = None
        self.web = web
        self.structured_foreground_compatible = False
        self.operator = drafts.operator
        self.scope = drafts.scope
        self.drafts = drafts
        self._run_storage = run_storage
        self._new_run_id = new_run_id
        self.setup = setup
        self.performance = performance
        self.delivery = delivery
        self.instruction_tests = instruction_tests
        self.instruction_findings = instruction_findings
        self.model = model
        self.openrouter = reviewer
        self.openrouter_drafts = drafter
        self.demo_catalog = demo_catalog
        # Retain receipt recovery while fresh web inference remains disabled.
        self.openrouter.web_disabled = self.openrouter_drafts.web_disabled = web

    def require(self, capability):
        self.operator.require_brand(self.scope)
        if self.operator.id != self.drafts.operator.id:
            raise PermissionError("The run actor changed. Resolve a new application context.")
        self.drafts.require(capability)

    def capabilities(self):
        from .capabilities import catalogue
        return catalogue(self)

    def start(self, request, *, run_id=None):
        self.require("youtube:agent.run")
        if request != DEMO_REQUEST:
            raise ValueError("The offline recording supports the documented demo request only.")
        self.require("youtube:campaign.read")
        run_id = self._new_run_id() if run_id is None else run_id
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise ValueError("Invalid run ID.")
        with self._run_storage.write() as unit:
            unit.runs.create_run_if_id_absent(
                run_id, self.scope.client_id, self.scope.brand_id,
                self.operator.id, request, "running", self.drafts.campaign_id)
            self._owned_run_from(unit.runs, run_id, expected_request=request)
            unit.commit()
        return run_id

    def start_next_test(self, campaign_id, revision, fingerprint, review_id, *,
                        mode="offline", model=None, operation_id=None, provider_selection_id=None):
        self.drafts._package_scope(campaign_id, revision)
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
               for value in (fingerprint, review_id)):
            raise ValueError("Choose a valid performance review.")
        source = {"campaign_id": campaign_id, "revision": revision,
                  "fingerprint": fingerprint, "review_id": review_id}
        return self._start_test_preparation(source, mode=mode, model=model, operation_id=operation_id,provider_selection_id=provider_selection_id)

    def start_experiment_next_test(self, test_id, review_id, *, mode="offline", model=None, operation_id=None, provider_selection_id=None):
        if (not isinstance(test_id, str) or not RUN_ID.fullmatch(test_id)
                or not isinstance(review_id, str) or not re.fullmatch(r"[0-9a-f]{64}", review_id)):
            raise ValueError("Choose a valid instruction-test assessment.")
        return self._start_test_preparation({"test_id": test_id, "review_id": review_id},
                                            mode=mode, model=model, operation_id=operation_id,provider_selection_id=provider_selection_id)

    def _next_test_context(self, evidence: EvidenceReader, source):
        if "test_id" in source:
            return self.instruction_tests.next_test_context_from(evidence, **source)
        return self.performance.instruction_test_context_from(evidence, **source)

    def _start_test_preparation(self, source, *, mode, model, operation_id,provider_selection_id=None):
        self.require("youtube:agent.run")
        self.require("youtube:campaign.read")
        if not isinstance(mode, str) or mode not in {"offline", "openrouter"}:
            raise ValueError("Choose offline or OpenRouter drafting.")
        if mode == "offline" and model is not None:
            raise ValueError("Offline drafts do not use provider settings.")
        if provider_selection_id is not None and (mode!='openrouter' or self.foreground is None): raise ValueError('Use a provider selection only for OpenRouter.')
        settings = ({"mode":"offline"} if mode=='offline' else
            self.foreground.settings(provider_selection_id,model,'structured_review',self.openrouter_drafts.prompt_version) if provider_selection_id is not None else self._structured_settings(self.openrouter_drafts, model))
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
        with self._run_storage.write() as unit:
            runs = unit.runs
            existing = runs.structured_source_row(run_id)
            if existing is not None:
                self._owned_run_from(runs, run_id, expected_request=NEXT_TEST_REQUEST)
                saved = runs.structured_settings_row(run_id)
                if json.loads(existing[0]) != source or (json.loads(saved[0]) if saved else {"mode": "offline"}) != settings:
                    raise ValueError("This drafting operation was already used for a different request.")
                return run_id
            if mode=='openrouter' and (self.web or self.openrouter_drafts.web_disabled):
                self._require_structured_available(self.openrouter_drafts, settings)
            self._next_test_context(unit.evidence, source)
            runs.create_run(
                run_id, self.scope.client_id, self.scope.brand_id, self.operator.id,
                NEXT_TEST_REQUEST, "running", self.drafts.campaign_id,
            )
            runs.add_structured_source(run_id, json.dumps(source))
            runs.add_structured_settings(run_id, json.dumps(settings))
            unit.commit()
        return run_id

    def _owned_run_from(self, runs: AgentRunReader, run_id, *, expected_request=None):
        self.require("youtube:campaign.read")
        row = runs.scoped_run_row(
            run_id, self.scope.client_id, self.scope.brand_id, self.operator.id, self.drafts.campaign_id,
        )
        if row is None:
            raise PermissionError("The run is unavailable to this operator.")
        if expected_request is not None and row[0] != expected_request:
            raise ValueError("This run ID was already used for a different request.")
        return row

    @staticmethod
    def _structured_source(runs: AgentRunReader, run_id):
        row = runs.structured_source_row(run_id)
        if row is None:
            raise ValueError("The saved structured run has no source.")
        return json.loads(row[0])

    def start_instruction_review(self, test_id, *, mode="offline", model=None, operation_id=None, provider_selection_id=None):
        self.require("youtube:agent.run")
        self.require("youtube:campaign.read")
        if not isinstance(mode, str) or mode not in {"offline", "openrouter"}:
            raise ValueError("Choose offline or OpenRouter reviews.")
        if mode == "offline" and model is not None:
            raise ValueError("Offline reviews do not use provider settings.")
        if provider_selection_id is not None and (mode!='openrouter' or self.foreground is None): raise ValueError('Use a provider selection only for OpenRouter.')
        settings = {"mode": "offline"}
        if mode == "openrouter":
            settings = (self.foreground.settings(provider_selection_id,model,'structured_review',self.openrouter.prompt_version)
                        if provider_selection_id is not None and self.foreground is not None else self._structured_settings(self.openrouter, model))
            if operation_id is None:
                raise ValueError("Use a valid review operation ID.")
        if operation_id is not None:
            if not isinstance(operation_id, str) or not RUN_ID.fullmatch(operation_id):
                raise ValueError("Use a valid review operation ID.")
            run_id = package_fingerprint({"scope": vars(self.scope), "actor": self.operator.id,
                                          "request": REVIEW_TEST_REQUEST, "operation_id": operation_id})[:32]
            with self._run_storage.read() as runs:
                row = runs.structured_start_row(run_id)
                if row is not None:
                    self._owned_run_from(runs, run_id, expected_request=REVIEW_TEST_REQUEST)
                    if json.loads(row[0])["test_id"] != test_id or json.loads(row[1]) != settings:
                        raise ValueError("This review operation was already used for a different request.")
                    return run_id
        if mode=='openrouter' and (self.web or self.openrouter.web_disabled):
            self._require_structured_available(self.openrouter, settings)
        context = self.instruction_tests.review_context(test_id)
        if operation_id is None:
            run_id = package_fingerprint({
                "actor": self.operator.id, "request": REVIEW_TEST_REQUEST, "context": context,
                "assessment_version": ASSESSMENT_VERSION,
            })[:32]
        with self._run_storage.write() as unit:
            runs = unit.runs
            runs.create_run_if_no_conflict(
                run_id, self.scope.client_id, self.scope.brand_id, self.operator.id,
                REVIEW_TEST_REQUEST, "running", self.drafts.campaign_id,
            )
            self._owned_run_from(runs, run_id, expected_request=REVIEW_TEST_REQUEST)
            runs.add_structured_source(run_id, json.dumps(context), ignore_existing=True)
            existing = runs.structured_settings_row(run_id)
            if existing and json.loads(existing[0]) != settings:
                raise ValueError("This review operation was already used for a different request.")
            if self._structured_source(runs, run_id)["test_id"] != test_id:
                raise ValueError("This review operation was already used for a different request.")
            runs.add_structured_settings(run_id, json.dumps(settings), ignore_existing=True)
            unit.commit()
        return run_id

    def resume(self, run_id, max_steps=4):
        if self.foreground: self.foreground.use_run(run_id)
        self.require("youtube:agent.run")
        if type(max_steps) is not int or not 0 <= max_steps <= 4:
            raise ValueError("The step budget must be between zero and four.")
        if self.planner.owns(run_id):
            return self.planner.resume(run_id, max_steps=max_steps)
        for _ in range(max_steps):
            self.require("youtube:campaign.read")
            if self._resume_openrouter(run_id):
                continue
            if self.foreground: self.foreground.before_commit(self.foreground.settings_bound)
            with self._run_storage.write() as unit:
                runs = unit.runs
                request, status = self._owned_run_from(runs, run_id)
                if (self.foreground and status != "running") or status in {"ready_for_review", "waiting_for_evidence"}:
                    return self._read_run(runs, run_id)
                history = self._step_history(runs, run_id)
                tool = self.model.next_tool(request, history)
                self.require("youtube:agent.run")
                if request == REVIEW_TEST_REQUEST:
                    result = self._dispatch_instruction_review(runs, unit.evidence, run_id, tool, history)
                elif request == NEXT_TEST_REQUEST:
                    result = self._dispatch_next_test(runs, unit.evidence, run_id, tool, history)
                else:
                    result = self._dispatch(unit.evidence.drafts, tool, history)
                self.require("youtube:agent.run")
                runs.append_step(run_id, len(history), tool, json.dumps(result))
                if tool in {"finish", "finish_test", "finish_test_review", "wait_for_evidence"}:
                    runs.update_status(run_id, "waiting_for_evidence" if tool == "wait_for_evidence" else "ready_for_review")
                unit.commit()
        if self.foreground: self.foreground.policy.refresh()
        return self.read(run_id)

    def read(self, run_id):
        if self.planner.owns(run_id):
            return self.planner.read(run_id)
        self.require("youtube:campaign.read")
        with self._run_storage.read() as runs:
            return self._read_run(runs, run_id)

    @staticmethod
    def _step_history(runs: AgentRunReader, run_id):
        return [{"tool": tool, "result": json.loads(result)} for tool, result in runs.step_rows(run_id)]

    def _read_run(self, runs: AgentRunReader, run_id):
        request, status = self._owned_run_from(runs, run_id)
        result = {"run_id": run_id, "request": request, "status": status, "steps": self._step_history(runs, run_id)}
        inference = runs.structured_inference_row(run_id)
        if inference is not None:
            receipt = json.loads(inference.receipt) if inference.receipt else None
            result["inference"] = {"settings": json.loads(inference.settings), "state": inference.state,
                                   "receipt": receipt["inference"] if receipt else None, "error": inference.error}
        return result

    @staticmethod
    def _validate_structured_settings(settings):
        fields = {'mode', 'model', 'prompt_version', 'max_calls', 'max_output_tokens', 'max_cost_usd'}
        if (not isinstance(settings, dict) or set(settings) != fields
                or settings['mode'] != 'openrouter'
                or not isinstance(settings['model'], str) or not settings['model']
                or not isinstance(settings['prompt_version'], str) or not settings['prompt_version']
                or type(settings['max_calls']) is not int or settings['max_calls'] != 1
                or type(settings['max_output_tokens']) is not int
                or not 1 <= settings['max_output_tokens'] <= STRUCTURED_MAX_OUTPUT_TOKENS
                or type(settings['max_cost_usd']) not in (int, float) or settings['max_cost_usd'] != 0):
            raise ReviewInferenceError('The structured-model settings exceed the application limits.')

    def _structured_settings(self, service, model):
        settings = deepcopy(service.settings(model))
        if not self.structured_foreground_compatible:
            self._validate_structured_settings(settings)
            if settings['model'] != model or settings['prompt_version'] != service.prompt_version:
                raise ReviewInferenceError('The structured-model settings do not match the selected model.')
        return settings

    @staticmethod
    def _require_structured_receipt(receipt, context, settings):
        metadata = receipt.get('inference') if isinstance(receipt, dict) else None
        if (not isinstance(metadata, dict)
                or any(metadata.get(key) != settings.get(key) for key in ('mode', 'model', 'prompt_version'))
                or metadata.get('evidence_id') != package_fingerprint(context)
                or any(key in metadata and metadata[key] != settings.get(key)
                       for key in ('max_calls', 'max_output_tokens', 'max_cost_usd'))):
            raise ReviewInferenceError(
                'The structured-model receipt does not match the saved request. Its receipt was retained.')

    def _require_structured_available(self, model, settings):
        # Supplied services are offline-only until their dispatch is admitted by a port.
        # This fence is application-owned; a permissive supplied service cannot waive it.
        if not self.structured_foreground_compatible and (self.web or settings.get('foreground')):
            raise ReviewInferenceError(
                'Browser inference awaits scoped admission and recovery. Use offline mode.')
        model.require_available(deepcopy(settings))

    def _resume_openrouter(self, run_id):
        """Reserve one request and commit its receipt separately from the step."""
        self.require("youtube:agent.run")
        self.require("youtube:campaign.read")
        receipt = None
        with self._run_storage.write() as unit:
            runs = unit.runs
            request, status = self._owned_run_from(runs, run_id)
            if status != "running":
                return False
            row = runs.structured_inference_row(run_id)
            if request not in {REVIEW_TEST_REQUEST, NEXT_TEST_REQUEST} or runs.step_count(run_id) != 1 or row is None:
                return False
            settings = json.loads(row.settings)
            if settings["mode"] != "openrouter":
                return False
            if not settings.get("foreground"):
                self._validate_structured_settings(settings)
            source = self._structured_source(runs, run_id)
            context = self._inference_context_from(unit.evidence, request, source)
            if request == NEXT_TEST_REQUEST and context.get("next_action") == "wait":
                return False
            adapter = self.openrouter if request == REVIEW_TEST_REQUEST else self.openrouter_drafts
            if row.state == "received":
                receipt = json.loads(row.receipt)
            elif row.state == "pending" or settings.get('foreground'):
                self._require_structured_available(adapter, settings)
                runs.request_structured_inference(run_id)
                unit.commit()
            else:
                raise ReviewInferenceError(row.error or
                    "This request is in progress or its outcome is unknown. Start a new operation to retry.")
        if receipt is None:
            try:
                receipt = (adapter.assess_instruction_test(deepcopy(context), deepcopy(settings)) if request == REVIEW_TEST_REQUEST
                           else adapter.draft_instructions(deepcopy(context), deepcopy(settings)))
                receipt = deepcopy(receipt)
                usage = receipt["inference"]["usage"]
                for field in ('input_tokens', 'output_tokens'):
                    value = usage[field]
                    if value is not None and (type(value) is not int or value < 0):
                        raise ValueError('Invalid structured-model usage')
                cost = usage['cost_usd']
                if not settings.get('foreground') and cost is not None and (
                        type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0):
                    raise ValueError('Invalid structured-model cost')
                receipt["inference"]["run_id"] = run_id
            except Exception as error:
                if self.structured_foreground_compatible and not isinstance(error, ReviewInferenceError):
                    raise  # Preserve existing native/foreground transport error mappings.
                exc = error if isinstance(error, ReviewInferenceError) else ReviewInferenceError(
                    'The structured-model request failed or its outcome is unknown. Start a new operation to retry.')
                with self._run_storage.write() as unit:
                    unit.runs.fail_structured_inference(run_id, str(exc))
                    unit.commit()
                raise exc from None
            with self._run_storage.write() as unit:
                unit.runs.receive_structured_inference(run_id, json.dumps(receipt))
                unit.commit()
        if self.foreground: self.foreground.before_commit(settings)
        with self._run_storage.write() as unit:
            self.require("youtube:agent.run")
            if self._owned_run_from(unit.runs, run_id, expected_request=request)[1] != "running":
                return True
            if unit.runs.step_exists_row(run_id, 1):
                return True
            self._inference_context_from(unit.evidence, request, source)
            self._require_structured_receipt(receipt, context, settings)
            usage = receipt["inference"]["usage"]
            if ((not settings.get('foreground') and usage["cost_usd"] is not None and usage["cost_usd"] > 0)
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
            unit.runs.append_step(run_id, 1, tool, json.dumps(result))
            unit.commit()
        return True

    def _inference_context_from(self, evidence: EvidenceReader, request, source):
        if request == REVIEW_TEST_REQUEST:
            self.instruction_tests.require_review_context_from(evidence, source)
            return source
        return self._next_test_context(evidence, source)

    def _dispatch_instruction_review(self, runs: AgentRunReader, evidence: EvidenceWriter, run_id, tool, history):
        expected = ("load_test_evidence", "assess_instruction_test", "save_test_review", "finish_test_review")
        if len(history) >= len(expected) or tool != expected[len(history)]:
            raise ValueError("The requested tool is unavailable at this step.")
        context = self._structured_source(runs, run_id)
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
            return self.instruction_tests.save_review_from(
                evidence, history[0]["result"], result.get("assessment", result), inference=inference,
            )
        return {"campaign_id": context["campaign_id"], "revision": context["revision"], "ambiguous": [],
                "message": "Instruction-test assessment saved."}

    def _dispatch_next_test(self, runs: AgentRunReader, evidence: EvidenceWriter, run_id, tool, history):
        expected = ("load_test_context", "draft_instructions", "save_instruction_test", "finish_test")
        if history and history[0]["result"].get("next_action") == "wait":
            expected = ("load_test_context", "wait_for_evidence")
        if len(history) >= len(expected) or tool != expected[len(history)]:
            raise ValueError("The requested tool is unavailable at this step.")
        source = self._structured_source(runs, run_id)
        if tool == "load_test_context":
            return self._next_test_context(evidence, source)
        if tool == "wait_for_evidence":
            context = self._next_test_context(evidence, source)
            if context["next_action"] != "wait":
                raise PackageConflict("The assessment changed. Start from a current review.")
            return {"campaign_id": context["package"]["campaign_id"], "revision": context["package"]["revision"],
                    "ambiguous": [], "outcome": "waiting", "review_id": source["review_id"],
                    "message": context["experiment_review"]["assessment"]["reason"]}
        if tool == "draft_instructions":
            self._next_test_context(evidence, source)
            context = history[0]["result"]
            instruction = self.drafts.validate_instruction(
                self.model.revise_instructions(context), context["comparison"]["instruction"],
            )
            return {"instruction": instruction}
        if tool == "save_instruction_test":
            result = history[1]["result"]
            save = (self.instruction_tests.save_next_test_from if "test_id" in source
                    else self.performance.save_instruction_test_from)
            return save(evidence, source, result["instruction"], inference=result.get("inference"))
        draft = history[2]["result"]
        return {"campaign_id": draft["campaign_id"], "revision": draft["revision"], "ambiguous": [],
                "message": "Revised comparison instructions prepared for approval."}

    def _dispatch(self, drafts: DraftRepository, tool, history):
        # Each decision is constrained to the next capability in this recorded workflow.
        expected = ("load_context", "propose_placements", "save_draft", "finish")
        if len(history) >= len(expected) or tool != expected[len(history)]:
            raise ValueError("The requested tool is unavailable at this step.")
        if tool == "load_context":
            return self.drafts.read_from(drafts)
        if tool == "propose_placements":
            proposals = []
            for row in read_catalog(self.demo_catalog):
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
                                    repository=drafts)
        draft = history[2]["result"]
        return {"campaign_id": draft["campaign_id"], "revision": draft["revision"],
                "ambiguous": [row for row in history[1]["result"] if row["creative"] == "review"],
                "message": "Draft prepared for review. Placements are fictional."}
