"""Route the local simulated placement slice to its typed runtime."""
import re

from campaign_agent.agent.draft_permissions import DRAFT_PERMISSIONS
from campaign_agent.agent.planner import DELIVERY_NEXT_TEST_REQUEST, DELIVERY_REQUEST, SIMULATED
from campaign_agent.application.planner_runtime import PILOT_TOOLS, RetainedWorkflow


class PlacementRouter:
    def __init__(self, legacy, placement, runtime):
        self.legacy, self.placement, self.runtime = legacy, placement, runtime
        self.adopted = placement

    def __getattr__(self, name):
        return getattr(self.legacy, name)

    @property
    def catalogs(self):
        return self.legacy.catalogs if self.runtime.foreground else self.placement.catalogs

    @property
    def conversations(self):
        return self.legacy.conversations if self.runtime.foreground else self.placement.conversations

    def owns(self, run_id):
        with self.placement.phase({'command': 'owns_placement_run', 'run_id': run_id}, write=False) as (unit, _):
            return unit.planner.job_snapshot_row(run_id) is not None

    def options(self):
        if self.runtime.foreground:
            return self.legacy.options()
        result = self.placement.options()
        if not self.legacy.web_disabled and not self.legacy.remote.web_disabled:
            result['models'] += [{'id': name, 'label': name, 'mode': 'openrouter'}
                                 for name in self.legacy.remote.models]
            with self.placement.phase({'command': 'planner_options'}, write=False) as (unit, _):
                scope = self.placement.scope
                row = unit.planner.default_row(scope.client_id, scope.brand_id, self.runtime.operator.id)
                if row and row[0] in {item['id'] for item in result['models']}:
                    result['default'] = row[0]
        return result

    def _delivery(self, request):
        if not isinstance(request, str):
            return False
        text = ' '.join(request.split())
        normalized = text.casefold().rstrip('.!?')
        delivery = self.runtime.delivery
        return bool(DELIVERY_NEXT_TEST_REQUEST.fullmatch(text) or DELIVERY_REQUEST.fullmatch(text)
                    or (delivery.reporting is None and normalized == 'review ad viewer activity')
                    or (delivery.demo_scenario and normalized == 'review demo delivery'))

    def start(self, request, model, session_id, run_id, catalog_id, after_message=None,
              draft_permission='none', provider_selection_id=None):
        target = (self.placement if not self.runtime.foreground and model in SIMULATED
                  and provider_selection_id is None and not self._delivery(request) else self.legacy)
        return target.start(request, model, session_id, run_id, catalog_id, after_message,
                            draft_permission, provider_selection_id)

    @staticmethod
    def _retained(result):
        planner = result['planner']
        return (planner['settings']['mode'] != 'simulated' or planner['settings'].get('foreground') or planner['execution'] == 'application'
                or any('error' not in step['result'] and (step['tool'] not in PILOT_TOOLS
                       or step['tool'] == 'respond' and step.get('arguments', {}).get('topic')
                       in {'performance_review', 'experiment_review', 'capabilities'})
                       for step in result['steps']))

    def _eligible(self, run_id):
        return not self._retained(self.placement.read(run_id))

    def can_dispatch_local(self, path, data):
        if self.runtime.foreground or not isinstance(data, dict):
            return False
        if path == "/api/agent/run":
            return (set(data) == {"run_id"} and isinstance(data["run_id"], str)
                    and re.fullmatch(r"[0-9a-f]{32}", data["run_id"]) is not None
                    and self._eligible(data["run_id"]))
        required = {"request", "model", "session_id", "run_id", "catalog_id"}
        if (path != "/api/agent/placements" or not required <= data.keys()
                or data.keys() - required - {"after_message", "draft_permission"}
                or data["model"] not in SIMULATED or self._delivery(data["request"])):
            return False
        if (not isinstance(data["request"], str) or not data["request"].strip()
                or len(data["request"]) > 1500
                or any(not isinstance(data[k], str) or re.fullmatch(r"[0-9a-f]{32}", data[k]) is None
                       for k in ("session_id", "run_id", "catalog_id"))):
            return False
        after = data.get("after_message")
        return ((after is None or type(after) is int and 0 <= after < 2**63)
                and isinstance(data.get("draft_permission", "none"), str)
                and data.get("draft_permission", "none") in DRAFT_PERMISSIONS)

    def resume(self, run_id, max_steps=1):
        if self.runtime.foreground:
            return self.legacy.resume(run_id, max_steps=max_steps)
        result = self.placement.read(run_id)
        if self._retained(result):
            return self.legacy.resume(run_id, max_steps=max_steps)
        try:
            return self.placement.resume(run_id, max_steps=max_steps)
        except RetainedWorkflow as error:
            # The typed unit has exited; the legacy dispatcher consumes the saved receipt.
            remaining = error.remaining_steps if error.remaining_steps is not None else max_steps
            return self.legacy.resume(run_id, max_steps=remaining)

    def read(self, run_id):
        if self.runtime.foreground:
            return self.legacy.read(run_id)
        result = self.placement.read(run_id)
        return self.legacy.read(run_id) if self._retained(result) else result
