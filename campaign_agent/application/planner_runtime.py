"""The bounded local placement workflow over one injected store and current permits.

Other campaign workflows remain supported by the original runtime. This selected
entry point never hands a native connection to application commands.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
import re

from campaign_agent.access import require_access
from campaign_agent.application.campaigns import CampaignDrafts
from campaign_agent.application.planner_context import PlannerContext
from campaign_agent.agent.planner import PlacementAgent, MAX_TURNS, SIMULATED
from campaign_agent.agent.conversations import CampaignConversations
from campaign_agent.agent.review_tools import CampaignReviewTools
from campaign_agent.agent.replies import REPLY_VERSION, clarification, reply, verified_result
from campaign_agent.agent.draft_permissions import DRAFT_PERMISSIONS
from campaign_agent.domain.errors import PackageConflict
from campaign_agent.domain.inference_errors import ReviewInferenceError
from campaign_agent.placement_discovery import PlacementDiscovery
from campaign_agent.ports.planner_records import PlannerRunScope
from campaign_agent.ports.storage_errors import StorageError
from campaign_agent.ports.placement_commit import PlacementStorage
from campaign_agent.ports.planner_records import PlannerReceiptStorage
from campaign_agent.ports.planning import MainModel, PlacementClassifier
from campaign_agent.ports.planner_context import PlacementMedia

ID = re.compile(r'[0-9a-f]{32}')
class RetainedWorkflow(RuntimeError):
    """Resume the already received nonplacement tool outside the adopted unit."""
    remaining_steps = None


PILOT_TOOLS = {'read_campaign', 'inspect_catalog', 'classify_catalog', 'save_placement_draft',
               'ask_clarification', 'respond'}


class PlacementDraftCommands(CampaignDrafts):
    """Reuse draft policy with effect-free construction and port-only public writes."""
    def __init__(self, runtime, context, operator, campaign_id, access, examples):
        self._runtime = runtime
        self.context, self.scope = context, context.scope
        self.operator, self.campaign_id, self.access = operator, campaign_id, access
        self._examples = tuple(examples)
        self.live = False
        self.sources = {'sample_search', 'synthetic'}
        operator.require_brand(context.scope)
        if (not self._examples or any(example.scope != self.scope for example in self._examples)
                or len({example.ref for example in self._examples}) != len(self._examples)
                or len({example.creative_ref for example in self._examples}) != len(self._examples)):
            raise PermissionError("Supply the brand's own comparison catalog.")

    def read(self, revision=None):
        with self._runtime.phase({'command': 'read_draft'}, write=False) as (unit, _):
            return self.read_from(unit.drafts, revision)

    def save(self, payload, *, repository=None, connection=None):
        if connection is not None:
            raise ValueError('Placement commands require a typed repository.')
        if repository is not None:
            saved = super().save(payload, repository=repository)
            permit = self.access.permits.get('youtube:campaign.draft')
            if permit is not None and str(saved['revision']) != permit.campaign_revision:
                self.access.transition(saved)
            return saved
        with self._runtime.phase({'command': 'save_draft', 'payload': payload}) as (unit, _):
            saved = super().save(payload, repository=unit.drafts)
            self._runtime.note_transition(unit)
            self._runtime.commit(unit)
            return saved


class PlacementConversations(CampaignConversations):
    def __init__(self, runtime):
        self.planner, self.operator = runtime, runtime.operator
        self._runtime = runtime

    def read(self, session_id):
        with self._runtime.phase({'command': 'read_conversation', 'session_id': session_id}, write=False) as (unit, _):
            settings = self.session(unit.conversations, session_id)
            if settings is None:
                raise LookupError('Conversation unavailable.')
            messages = self.messages(unit.conversations, session_id)
            return {'id': session_id, 'campaign_id': self.planner.drafts.campaign_id, 'settings': settings,
                    'messages': messages, 'latest_message': messages[-1]['id'] if messages else 0,
                    'latest_run_id': messages[-1]['run_id'] if messages else None}

    def list(self):
        self.planner.drafts.require('youtube:campaign.read')
        with self._runtime.phase({'command': 'list_conversations'}, write=False) as (unit, _):
            return [{'id': key, 'model': json.loads(settings)['model'], 'title': title[:80]}
                    for key, settings, title in unit.conversations.list_rows(
                        self.planner.drafts.scope.client_id, self.planner.drafts.scope.brand_id,
                        self.operator.id, self.planner.drafts.campaign_id) if title]


class _CatalogTransactions:
    def __init__(self, runtime):
        self._runtime = runtime

    @contextmanager
    def read(self):
        with self._runtime.phase({'command': 'catalogue_list'}, write=False) as (unit, _):
            self._runtime.require('youtube:campaign.read')
            yield unit.catalogs

    @contextmanager
    def write(self):
        runtime = self._runtime
        with runtime.phase({'command': 'catalogue_register'}) as (unit, _):
            runtime.require('youtube:catalog.write')
            runtime.require('youtube:campaign.read')

            class CatalogUnit:
                catalogs = unit.catalogs

                def commit(self):
                    runtime.commit(unit)

            yield CatalogUnit()


class PlacementRuntime:
    """One request-local application graph; effects arrive solely through ports."""
    _history = PlacementAgent._history
    _owned_placement_run = PlacementAgent._owned_placement_run
    _placement_context = PlacementAgent._placement_context
    _save_placement_tool = PlacementAgent._save_placement_tool

    def __init__(self, *, context, operator, campaign_id, access, storage: PlacementStorage, receipts: PlannerReceiptStorage,
                 media: PlacementMedia, examples, simulator: MainModel, classifier: PlacementClassifier):
        self.owner = self.planner = self
        self.operator, self.scope = operator, context.scope
        self.foreground = None
        self.access, self.storage, self.receipts = access, storage, receipts
        self.media, self.examples = media, tuple(examples)
        self.simulator, self.classifier = simulator, classifier
        self.drafts = PlacementDraftCommands(self, context, operator, campaign_id, access, self.examples)
        self.catalogs = PlacementDiscovery(self.drafts, _CatalogTransactions(self))
        self.conversations = PlacementConversations(self)
        # Only pure reply/outcome methods are used by the selected tool set.
        self.performance = self.instruction_tests = None
        self.review_tools = CampaignReviewTools(self)

    def require(self, capability):
        self.operator.require_brand(self.scope)
        if self.operator.id != self.drafts.operator.id:
            raise PermissionError('The run actor changed. Resolve a new application context.')
        require_access(self.operator, self.drafts.context, self.access, capability, self.drafts.campaign_id)

    @contextmanager
    def phase(self, command, *, write=True, media=False, agent=False):
        self.require('youtube:campaign.read')
        required = ('youtube:campaign.read', 'youtube:agent.run') if agent else ('youtube:campaign.read',)
        self.access.refresh(command, required=required)  # Acquire before the unit opens.
        captured = self.media.capture(self.examples) if media else None
        with (self.storage.write() if write else self.storage.read()) as unit:
            with self.access.bind(unit.drafts):
                for capability in required:
                    self.require(capability)
                context = PlannerContext(self.drafts, self.examples, captured) if media else None
                self.access.media = captured
                try:
                    if captured is not None:
                        captured.validate()
                    yield unit, context
                except (json.JSONDecodeError, TypeError):
                    raise StorageError('invalid', 'Placement storage contains invalid records.') from None
                finally:
                    self.access.media = None

    def note_transition(self, unit):
        current = json.loads(unit.drafts.read_snapshot(self.drafts.campaign_id))
        permit = self.access.permits.get('youtube:campaign.draft')
        if permit is not None and str(current['revision']) != permit.campaign_revision:
            self.access.transition(current)

    def commit(self, unit):
        captured = self.access.media
        if captured is not None:
            captured.validate()
        self.access.before_commit()
        unit.commit()

    def options(self):
        with self.phase({'command': 'planner_options'}, write=False) as (unit, _):
            self.require('youtube:campaign.read')
            row = unit.planner.default_row(self.scope.client_id, self.scope.brand_id, self.operator.id)
            default = row[0] if row and row[0] in SIMULATED else 'simulated'
            return {'models': [{'id': 'simulated', 'label': 'Simulated agent', 'mode': 'simulated'},
                               {'id': 'simulated-inspect', 'label': 'Simulated agent · inspect first', 'mode': 'simulated'}],
                    'default': default, 'max_turns': MAX_TURNS, 'specialist': 'simulated_decision',
                    'specialist_label': 'Automatic · simulated decision model'}

    def start(self, request, model, session_id, run_id, catalog_id, after_message=None,
              draft_permission='none', provider_selection_id=None):
        self.require('youtube:agent.run')
        self.require('youtube:campaign.read')
        if (any(not isinstance(value, str) or not ID.fullmatch(value) for value in (session_id, run_id, catalog_id))
                or not isinstance(request, str) or not request.strip() or len(request) > 1500):
            raise ValueError('Supply a request and valid session, run and catalog references.')
        if after_message is not None and (type(after_message) is not int or not 0 <= after_message < 2**63):
            raise ValueError('Supply a valid conversation message reference.')
        if not isinstance(draft_permission, str) or draft_permission not in DRAFT_PERMISSIONS:
            raise ValueError('Choose a valid draft permission for this request.')
        if model not in SIMULATED or provider_selection_id is not None:
            raise ValueError('This local placement composition supports simulated models only.')
        settings = {'mode': 'simulated', 'model': model}
        with self.phase({'command': 'start_placements', 'run_id': run_id, 'request': request,
                         'model': model, 'session_id': session_id, 'catalog_id': catalog_id,
                         'after_message': after_message, 'draft_permission': draft_permission,
                         'provider_selection_id': provider_selection_id}, media=True, agent=True) as (unit, context):
            existing = unit.planner.job_snapshot_row(run_id)
            if existing:
                self._owned_placement_run(unit, run_id)
                source = json.loads(existing[0])
                if (source['request'], source['settings'], source['session_id'], source['catalog_id']) != (
                        request, settings, session_id, catalog_id):
                    raise ValueError('This run ID belongs to a different request.')
                if source.get('after_message') != after_message:
                    raise ValueError('This run ID belongs to a different conversation turn.')
                if source.get('draft_permission', 'none') != draft_permission:
                    raise ValueError('This run ID has different draft authority. Send a new request to change it.')
                return run_id
            self.catalogs.read(unit.catalogs, catalog_id)
            current = self.drafts.read_from(unit.drafts)
            previous, truncated = self.conversations.begin(unit.conversations, session_id, settings, run_id,
                                                          request, catalog_id, current['revision'], after_message)
            source = {'request': request, 'session_id': session_id, 'catalog_id': catalog_id,
                      'revision': current['revision'], 'settings': settings, 'draft_permission': draft_permission,
                      'conversation': previous, 'conversation_truncated': truncated, 'after_message': after_message,
                      **context.pin(unit.context, unit.drafts, current),
                      'routing': {'classifier': 'simulated_decision', 'max_classifier_calls': 1}, 'max_turns': MAX_TURNS}
            scope = PlannerRunScope(self.scope.client_id, self.scope.brand_id, self.operator.id, self.drafts.campaign_id)
            unit.planner.upsert_default(scope.client_id, scope.brand_id, scope.actor_id, model)
            unit.runs.create_run(run_id, scope, request, 'running')
            unit.planner.create_job(run_id, session_id, json.dumps(source))
            self.commit(unit)
        return run_id

    def _context(self, unit, run_id):
        source = self._placement_context(unit, run_id)
        if source['settings']['mode'] != 'simulated' or source.get('delivery_request'):
            raise RetainedWorkflow('Continue this request through its retained workflow.')
        return source

    @staticmethod
    def _placement_history(history):
        # Genuine review/experiment observations belong to their retained runtime,
        # whose freshness/refresh checks remain supported. No native callback crosses here.
        if any(step['tool'] not in PILOT_TOOLS and 'error' not in step['result'] for step in history):
            raise RetainedWorkflow('Continue this history through its retained workflow.')

    def _classify(self, run_id, expected_source):
        with self.phase({'command': 'classify_placements', 'run_id': run_id, 'source': expected_source}, agent=True) as (unit, _):
            source = self._context(unit, run_id)
            if source != expected_source:
                raise PackageConflict('The run source changed. Start a new request.')
            state, saved = unit.planner.classification_row(run_id)
            if state == 'received':
                return json.loads(saved)
            if state != 'pending':
                raise ReviewInferenceError('The specialist request outcome is unknown. Start a new run.')
            if self.classifier.route != source['routing']['classifier']:
                raise ValueError('The pinned specialist route is unavailable.')
            rows = self.catalogs.read(unit.catalogs, source['catalog_id'])
            contexts = self.drafts.read_from(unit.drafts)['brief']['contexts']
            unit.planner.request_classification(run_id)
            self.commit(unit)
        try:
            assignments = self.classifier.classify(rows, contexts)
            if (not isinstance(assignments, list) or len(assignments) != len(rows)
                    or any(not isinstance(row, dict) or set(row) != {'id', 'context'}
                           or not isinstance(row['id'], str) or not isinstance(row['context'], str)
                           or row['context'] not in {*contexts, 'review'} for row in assignments)
                    or len({row['id'] for row in assignments}) != len(rows)
                    or {row['id'] for row in assignments} != {row['video_id'] for row in rows}):
                raise ValueError('Invalid classification receipt')
        except Exception:
            self.receipts.fail_classification(run_id)
            raise ReviewInferenceError('The specialist response failed validation. Start a new run.') from None
        result = {'assignments': assignments, 'route': source['routing']['classifier'],
                  'label': 'Simulated decision response; accuracy not evaluated'}
        self.receipts.receive_classification(run_id, json.dumps(result))
        return result

    def _tool(self, unit, context, source, history, call, classified):
        name, args = call['tool'], call['arguments']
        if name not in PILOT_TOOLS or (name == 'respond' and args.get('topic') in {'performance_review', 'experiment_review', 'capabilities'}):
            raise RetainedWorkflow('Continue the received tool through its retained workflow.')
        if source.get('settings', {}).get('charging_profile', '').startswith('preview-text-tools/') and name in {'review_performance', 'validate_campaign_setup'}:
            raise ValueError('This tool uses evaluation fixtures and is unavailable for live requests.')
        if name == 'classify_catalog' and source.get('settings', {}).get('charging_profile', '').startswith('preview-text-tools/'):
            from campaign_agent.placement_discovery import model_assignments
            return model_assignments(args, history, self.drafts.read_from(unit.drafts)['brief']['contexts']), 'running'
        if name in {'read_campaign', 'inspect_catalog', 'classify_catalog'} and args:
            raise ValueError('Unexpected fields')
        if name == 'read_campaign':
            return context.read_campaign(unit.context, unit.drafts, source), 'running'
        if name == 'inspect_catalog':
            rows = self.catalogs.read(unit.catalogs, source['catalog_id'])
            return {'entries': [{**row, 'description': row['description'][:300], 'source_reference': row['source_reference'][:200]}
                                for row in rows[:10]], 'total': len(rows), 'shown': min(10, len(rows))}, 'running'
        if name == 'classify_catalog':
            return classified, 'running'
        if name == 'save_placement_draft':
            return self._save_placement_tool(unit, source, history, call)
        if name == 'ask_clarification' and set(args) == {'reason'}:
            return clarification(args['reason'], source['revision']), 'needs_input'
        if name == 'respond' and source.get('settings', {}).get('charging_profile', '').startswith('preview-text-tools/'):
            from campaign_agent.agent.replies import model_reply
            return model_reply(args, source['revision']), 'answered'
        if name == 'respond' and set(args) == {'topic'} and args['topic'] not in {'performance_review', 'experiment_review', 'capabilities'}:
            draft = self.drafts.read_from(unit.drafts)
            approved = context.package_review(unit.context, unit.drafts, draft['revision'])['approval'] is not None if args['topic'] == 'approval_and_launch' else False
            return reply(args['topic'], draft, approved=approved), 'answered'
        raise ValueError('Unknown tool')

    def _commit_turn(self, run_id, position, receipt, classified, expected_source):
        with self.phase({'command': 'commit_placement_turn', 'run_id': run_id, 'position': position,
                         'receipt': receipt, 'source': expected_source}, media=True, agent=True) as (unit, context):
            _, status = self._owned_placement_run(unit, run_id)
            if status != 'running':
                return False
            source = self._context(unit, run_id)
            if source != expected_source:
                raise PackageConflict('The run source changed. Start a new request.')
            if unit.runs.step_exists_row(run_id, position):
                return True
            history = self._history(unit.planner, run_id)
            self._placement_history(history)
            self.require('youtube:agent.run')
            try:
                with unit.tool_attempt():
                    result, status = self._tool(unit, context, source, history, receipt, classified)
            except PackageConflict:
                raise
            except (ValueError, TypeError):
                result, status = {'error': 'Invalid tool arguments or unavailable capability; use the declared tool schemas.'}, 'running'
            unit.runs.append_step(run_id, position, receipt['tool'], json.dumps(result))
            if status == 'running' and position + 1 >= source['max_turns']:
                result, status = {'revision': source['revision'], 'ambiguous': [],
                                  'message': 'The turn allowance is exhausted. Start a new request with more context.',
                                  'reply_version': REPLY_VERSION, 'reply_code': 'turn_limit'}, 'needs_input'
            if status != 'running':
                unit.runs.update_status(run_id, status)
                unit.planner.update_outcome(run_id, json.dumps(result))
                self.conversations.finish(unit.conversations, run_id, result, status)
            self.note_transition(unit)
            self.commit(unit)
        return True

    def resume(self, run_id, max_steps=4):
        self.require('youtube:agent.run')
        if type(max_steps) is not int or not 0 <= max_steps <= 4:
            raise ValueError('The step budget must be between zero and four.')
        for attempt in range(max_steps):
            with self.phase({'command': 'reserve_placement_turn', 'run_id': run_id, 'max_steps': max_steps}, agent=True) as (unit, _context):
                _, status = self._owned_placement_run(unit, run_id)
                self.require('youtube:campaign.read')
                if status != 'running':
                    break
                source = self._context(unit, run_id)
                history = self._history(unit.planner, run_id)
                self._placement_history(history)
                position = len(history)
                row = unit.planner.turn_row(run_id, position)
                if row and row[0] != 'received':
                    raise ReviewInferenceError(row[2] or 'This model request is in progress or its outcome is unknown. Start a new run.')
                receipt = json.loads(row[1]) if row and row[1] else None
                if not row:
                    unit.planner.request_turn(run_id, position)
                self.commit(unit)
            if receipt is None:
                try:
                    receipt = self.simulator.next_turn(deepcopy(source), deepcopy(history), dict(source['settings']))
                    if (not isinstance(receipt, dict) or not isinstance(receipt.get('call_id'), str)
                            or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', receipt['call_id'])
                            or not isinstance(receipt.get('tool'), str) or len(receipt['tool']) > 64
                            or not isinstance(receipt.get('arguments'), dict)):
                        raise ValueError('Invalid tool request')
                    usage = receipt.get('inference', {}).get('usage') or {}
                    if (usage.get('cost_usd') is not None and usage['cost_usd'] > 0
                            or usage.get('output_tokens') is not None and usage['output_tokens'] > 512):
                        raise ValueError('Exceeded inference limit')
                except Exception:
                    self.receipts.fail_turn(run_id, position, 'The main-model request failed or its outcome is unknown. Start a new run.')
                    raise ReviewInferenceError('The main-model request failed or its outcome is unknown. Start a new run.') from None
                self.receipts.receive_turn(run_id, position, json.dumps(receipt))
            self.require('youtube:agent.run')
            classified = self._classify(run_id, source) if receipt['tool'] == 'classify_catalog' and not receipt['arguments'] else None
            try:
                if not self._commit_turn(run_id, position, receipt, classified, source):
                    break
            except RetainedWorkflow as error:
                error.remaining_steps = max_steps - attempt
                raise
        return self.read(run_id)

    def read(self, run_id):
        self.require('youtube:campaign.read')
        with self.phase({'command': 'read_placement_run', 'run_id': run_id}, write=False) as (unit, _):
            request, status = self._owned_placement_run(unit, run_id)
            snapshot, outcome = unit.planner.job_result_row(run_id)
            source = json.loads(snapshot)
            turns = [{'position': position, 'state': state, 'inference': json.loads(receipt).get('inference') if receipt else None}
                     for position, state, receipt in unit.planner.turn_rows(run_id)]
            return {'run_id': run_id, 'request': request, 'status': status, 'steps': self._history(unit.planner, run_id),
                    'result': verified_result(json.loads(outcome), status) if outcome else None,
                    'planner': {'session_id': source['session_id'], 'settings': source['settings'],
                                'draft_permission': source.get('draft_permission', 'none'),
                                'execution': 'application' if source.get('delivery_request') else 'model',
                                'delivery_demo_scenario': source.get('delivery_demo_scenario'),
                                'routing': source['routing'], 'max_turns': source['max_turns'], 'turns': turns}}
