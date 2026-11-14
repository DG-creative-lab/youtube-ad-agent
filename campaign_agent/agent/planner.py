"""Durable, bounded main-model loop over campaign application commands."""
from contextlib import closing
import json
import re
import sqlite3

from campaign_agent.adapters.openrouter_reviews import ReviewInferenceError
from campaign_agent.delivery import delivery_message
from campaign_agent.delivery_next_test import recommendation_message
from campaign_agent.handoff import package_fingerprint
from campaign_agent.placement_discovery import PlacementDiscovery, SimulatedClassifier
from scripts.campaign_drafts import PackageConflict
from .planning_models import OpenRouterPlanner, SimulatedPlanner
from .conversations import CampaignConversations
from .replies import REPLY_VERSION, clarification, reply, verified_result
from .review_tools import CampaignReviewTools
from .draft_permissions import DRAFT_PERMISSIONS, permits


ID = re.compile(r'[0-9a-f]{32}')
MAX_TURNS = 8
SIMULATED = ('simulated', 'simulated-inspect')
CURRENT_CAMPAIGN = r'(?:this|the|my|our)(?: current)? campaign'
GOOGLE_ADS = r'(?:(?:the|my|our) )?google ads'
DELIVERY_TOPIC = (
    r'(?:delivery|performance)(?: (?:report|metrics))?'
    r'|(?:video )?placement report|reported (?:video )?placements'
)
CURRENT_SCOPE = rf'(?: (?:for|of) {CURRENT_CAMPAIGN})?'
PERFORMANCE_VERB = r'(?:perform(?:ing)?|do(?:ing)?|deliver(?:ing)?)'
# Match an explicit request for the current campaign. Keep quoted mentions and other scopes out.
DELIVERY_REQUEST = re.compile(
    r'(?:(?:can|could|would) you (?:please )?|please,? )?'
    r'(?:'
    r'(?:review|check|pull|fetch|show(?: me)?|give me) '
    rf"(?:{GOOGLE_ADS} (?:campaign(?:['’]s)? )?(?:{DELIVERY_TOPIC}){CURRENT_SCOPE}"
    rf'|(?:the )?(?:{DELIVERY_TOPIC}){CURRENT_SCOPE} (?:in|from|on) google ads)'
    r'|(?:(?:tell me|check) )?how (?:is|are|did) '
    rf'(?:{GOOGLE_ADS}(?: campaign)? {PERFORMANCE_VERB}'
    rf'|{CURRENT_CAMPAIGN} {PERFORMANCE_VERB} (?:in|on) google ads)'
    r')(?:,? please)?[.!?]*',
    re.IGNORECASE,
)
DELIVERY_NEXT_TEST_REQUEST = re.compile(
    r'(?:(?:can|could|would) you (?:please )?|please )?'
    r'(?:(?:recommend|suggest) (?:the |a )?next test|what should (?:we|i) test next) '
    r'(?:from|using|based on) (?:(?:the|this) )?(?:saved )?(?:google ads )?delivery(?: (?:review|report))?[.!?]*',
    re.IGNORECASE,
)


class PlacementAgent:
    def __init__(self, owner, models=(), *, transport=None, simulator=None, classifier=None):
        self.owner, self.path, self.drafts = owner, owner.path, owner.drafts
        self.catalogs = PlacementDiscovery(self.drafts)
        self.remote = OpenRouterPlanner(models, transport=transport)
        self.simulator = simulator or SimulatedPlanner()
        self.classifier = classifier or SimulatedClassifier()
        self.review_tools = CampaignReviewTools(self)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS planner_sessions (
                    id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL, settings TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS planner_defaults (
                    client_id TEXT, brand_id TEXT, actor_id TEXT, model TEXT NOT NULL,
                    PRIMARY KEY(client_id,brand_id,actor_id));
                CREATE TABLE IF NOT EXISTS planner_jobs (
                    run_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, snapshot TEXT NOT NULL,
                    classification_state TEXT NOT NULL DEFAULT 'pending', classification TEXT, outcome TEXT);
                CREATE TABLE IF NOT EXISTS planner_turns (
                    run_id TEXT, position INTEGER, state TEXT NOT NULL, receipt TEXT, error TEXT,
                    PRIMARY KEY(run_id,position));
            ''')
        self.conversations = CampaignConversations(self)

    def options(self):
        self.owner.require("youtube:campaign.read")
        models = [{'id': 'simulated', 'label': 'Simulated agent', 'mode': 'simulated'},
                  {'id': 'simulated-inspect', 'label': 'Simulated agent · inspect first', 'mode': 'simulated'}]
        models += [{'id': item, 'label': item, 'mode': 'openrouter'} for item in self.remote.models]
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute('SELECT model FROM planner_defaults WHERE client_id=? AND brand_id=? AND actor_id=?',
                             (self.owner.drafts.scope.client_id, self.owner.drafts.scope.brand_id, self.owner.operator.id)).fetchone()
        default = row[0] if row and row[0] in {item['id'] for item in models} else 'simulated'
        return {'models': models, 'default': default, 'max_turns': MAX_TURNS,
                'specialist': 'simulated_decision', 'specialist_label': 'Automatic · simulated decision model'}

    def owns(self, run_id):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT 1 FROM planner_jobs WHERE run_id=?', (run_id,)).fetchone() is not None

    def start(self, request, model, session_id, run_id, catalog_id, after_message=None, draft_permission='none'):
        self.owner.require("youtube:agent.run")
        self.owner.require("youtube:campaign.read")
        if (any(not isinstance(value, str) or not ID.fullmatch(value) for value in (session_id, run_id, catalog_id))
                or not isinstance(request, str) or not request.strip() or len(request) > 1500):
            raise ValueError('Supply a request and valid session, run and catalog references.')
        if after_message is not None and (type(after_message) is not int or not 0 <= after_message < 2**63):
            raise ValueError('Supply a valid conversation message reference.')
        if not isinstance(draft_permission, str) or draft_permission not in DRAFT_PERMISSIONS:
            raise ValueError('Choose a valid draft permission for this request.')
        settings = ({'mode': 'simulated', 'model': model} if model in SIMULATED else self.remote.settings(model))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT snapshot FROM planner_jobs WHERE run_id=?', (run_id,)).fetchone()
            if existing:
                self.owner._owned_run(db, run_id)
                source = json.loads(existing[0])
                if (source['request'], source['settings'], source['session_id'], source['catalog_id']) != (
                        request, settings, session_id, catalog_id):
                    raise ValueError('This run ID belongs to a different request.')
                if source.get('after_message') != after_message:
                    raise ValueError('This run ID belongs to a different conversation turn.')
                if source.get('draft_permission', 'none') != draft_permission:
                    raise ValueError('This run ID has different draft authority. Send a new request to change it.')
                return run_id
            expected = (self.owner.drafts.scope.client_id, self.owner.drafts.scope.brand_id, self.owner.operator.id, json.dumps(settings))
            self.catalogs.read(db, catalog_id)
            current = self.drafts._read(db)
            previous, truncated = self.conversations.begin(db, session_id, settings, run_id, request,
                                                          catalog_id, current['revision'], after_message)
            context = {'request': request, 'session_id': session_id, 'catalog_id': catalog_id,
                       'revision': current['revision'], 'settings': settings,
                       'draft_permission': draft_permission,
                       'conversation': previous, 'conversation_truncated': truncated, 'after_message': after_message,
                       **self.review_tools.pin(db, current),
                       'routing': {'classifier': 'simulated_decision', 'max_classifier_calls': 1}, 'max_turns': MAX_TURNS}
            request_text = ' '.join(request.split())
            offline_request = request_text.casefold().rstrip('.!?')
            delivery_next_test = DELIVERY_NEXT_TEST_REQUEST.fullmatch(request_text) is not None
            demo_scenario = self.owner.delivery.demo_scenario
            if (delivery_next_test or DELIVERY_REQUEST.fullmatch(request_text)
                    or (self.owner.delivery.reporting is None and offline_request == 'review ad viewer activity')
                    or (demo_scenario and offline_request == 'review demo delivery')):
                try:
                    binding = self.owner.delivery.binding(db, self.drafts.campaign_id, current['revision'],
                                                          context['fingerprint'])
                except PackageConflict:
                    binding = None
                context.update(delivery_request=True, delivery_setup_id=binding['setup_id'] if binding else None)
                if demo_scenario:
                    context['delivery_demo_scenario'] = demo_scenario
                if delivery_next_test:
                    report = self.owner.delivery.saved_report(db, binding) if binding else None
                    context.update(delivery_next_test=True, delivery_report_id=report['id'] if report else None)
            db.execute('INSERT INTO planner_defaults VALUES(?,?,?,?) ON CONFLICT DO UPDATE SET model=excluded.model',
                       (*expected[:3], model))
            db.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?)',
                       (run_id, *expected[:3], request, 'running', self.owner.drafts.campaign_id))
            db.execute('INSERT INTO planner_jobs(run_id,session_id,snapshot) VALUES(?,?,?)',
                       (run_id, session_id, json.dumps(context)))
        return run_id

    def _context(self, db, run_id):
        self.owner.require("youtube:campaign.read")
        _, status = self.owner._owned_run(db, run_id)
        if status != 'running':
            raise PackageConflict('This request is no longer active. Read the latest conversation.')
        source = json.loads(db.execute('SELECT snapshot FROM planner_jobs WHERE run_id=?', (run_id,)).fetchone()[0])
        if self.conversations.session(db, source['session_id']) != source['settings']:
            raise PermissionError('The conversation scope or model has changed.')
        if self.drafts._read(db)['revision'] != source['revision']:
            raise PackageConflict('The campaign changed. Start a new request from the latest revision.')
        return source

    def _history(self, db, run_id):
        history = []
        for tool, result, receipt in db.execute(
                'SELECT s.tool,s.result,t.receipt FROM agent_steps s JOIN planner_turns t '
                'ON t.run_id=s.run_id AND t.position=s.position WHERE s.run_id=? ORDER BY s.position', (run_id,)):
            result, receipt = json.loads(result), json.loads(receipt)
            reply_status = {'respond': 'answered', 'ask_clarification': 'needs_input'}.get(tool)
            if reply_status and 'error' not in result:
                result = verified_result(result, reply_status)
            history.append({'tool': tool, 'result': result,
                            'call_id': receipt['call_id'], 'arguments': receipt['arguments']})
        return history

    def _classify(self, run_id):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            source = self._context(db, run_id)
            state, saved = db.execute('SELECT classification_state,classification FROM planner_jobs WHERE run_id=?',
                                      (run_id,)).fetchone()
            if state == 'received':
                return json.loads(saved)
            if state != 'pending':
                raise ReviewInferenceError('The specialist request outcome is unknown. Start a new run.')
            if self.classifier.route != source['routing']['classifier']:
                raise ValueError('The pinned specialist route is unavailable.')
            rows = self.catalogs.read(db, source['catalog_id'])
            contexts = self.drafts._read(db)['brief']['contexts']
            db.execute("UPDATE planner_jobs SET classification_state='requested' WHERE run_id=?", (run_id,))
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
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("UPDATE planner_jobs SET classification_state='failed' WHERE run_id=?", (run_id,))
            raise ReviewInferenceError('The specialist response failed validation. Start a new run.') from None
        result = {'assignments': assignments, 'route': source['routing']['classifier'],
                  'label': 'Simulated decision response; accuracy not evaluated'}
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE planner_jobs SET classification_state='received',classification=? WHERE run_id=?",
                       (json.dumps(result), run_id))
        return result

    def resume(self, run_id, max_steps=1):
        self.owner.require("youtube:agent.run")
        for _ in range(max_steps):
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                _, status = self.owner._owned_run(db, run_id)
                self.owner.require("youtube:campaign.read")
                if status != 'running':
                    return self.read(run_id)
                source = self._context(db, run_id)
                history = self._history(db, run_id)
                try:
                    self.review_tools.check_progress(db, source, history)
                except PackageConflict:
                    self._finish(db, run_id, self.review_tools.refresh_outcome(source, history), 'needs_input')
                    continue
                position = len(history)
                row = db.execute('SELECT state,receipt,error FROM planner_turns WHERE run_id=? AND position=?',
                                 (run_id, position)).fetchone()
                if row and row[0] != 'received':
                    raise ReviewInferenceError(row[2] or 'This model request is in progress or its outcome is unknown. Start a new run.')
                receipt = json.loads(row[1]) if row else None
                if not row:
                    if source['settings']['mode'] == 'openrouter' and not source.get('delivery_request'):
                        self.remote.require_available(source['settings'])
                        self.remote.prepare_turn(source, history, source['settings'])
                    db.execute("INSERT INTO planner_turns VALUES(?,?,'requested',NULL,NULL)", (run_id, position))
            if receipt is None:
                try:
                    if source.get('delivery_request'):
                        name = 'recommend_delivery_next_test' if source.get('delivery_next_test') else 'review_google_ads_delivery'
                        receipt = {'call_id': 'delivery', 'tool': name, 'arguments': {},
                                   'inference': {'mode': 'application', 'usage': None}}
                    else:
                        model = self.remote if source['settings']['mode'] == 'openrouter' else self.simulator
                        receipt = model.next_turn(source, history, source['settings'])
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
                    with closing(sqlite3.connect(self.path)) as db, db:
                        db.execute("UPDATE planner_turns SET state='failed',error=? WHERE run_id=? AND position=?",
                                   ('The main-model request failed or its outcome is unknown. Start a new run.', run_id, position))
                    raise ReviewInferenceError('The main-model request failed or its outcome is unknown. Start a new run.') from None
                with closing(sqlite3.connect(self.path)) as db, db:
                    db.execute("UPDATE planner_turns SET state='received',receipt=? WHERE run_id=? AND position=?",
                               (json.dumps(receipt), run_id, position))
            self.owner.require("youtube:agent.run")
            classified = None
            if receipt['tool'] == 'classify_catalog' and not receipt['arguments']:
                classified = self._classify(run_id)
            captured_review = None
            if receipt['tool'] == 'review_performance' and not receipt['arguments']:
                with closing(sqlite3.connect(self.path)) as db:
                    source = self._context(db, run_id)
                    approved = self.review_tools.approved(db, source)
                if approved is not None:
                    captured_review = self.review_tools.capture(source)
            if (receipt['tool'] == 'review_google_ads_delivery' and not receipt['arguments']
                    and source.get('delivery_request') and not source.get('delivery_next_test')
                    and source.get('delivery_setup_id')):
                try:
                    captured_review = self.owner.delivery.capture(
                        self.drafts.campaign_id, source['revision'], source['fingerprint'],
                        setup_id=source['delivery_setup_id'], demo_scenario=source.get('delivery_demo_scenario'))
                except PackageConflict:
                    pass
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                _, status = self.owner._owned_run(db, run_id)
                if status != 'running':
                    return self.read(run_id)
                source = self._context(db, run_id)
                if db.execute('SELECT 1 FROM agent_steps WHERE run_id=? AND position=?', (run_id, position)).fetchone():
                    continue
                history = self._history(db, run_id)
                self.owner.require("youtube:agent.run")
                db.execute('SAVEPOINT planner_tool')
                try:
                    result, status = self._tool(db, run_id, source, history, receipt, classified, captured_review)
                except PackageConflict:
                    db.execute('ROLLBACK TO planner_tool')
                    if receipt['tool'] not in {'review_performance', 'load_experiment_evidence',
                                               'assess_instruction_experiment', 'prepare_next_test', 'respond'}:
                        raise
                    result, status = self.review_tools.refresh_outcome(source, history, receipt['tool']), 'needs_input'
                except (ValueError, TypeError):
                    db.execute('ROLLBACK TO planner_tool')
                    result, status = {'error': 'Invalid tool arguments or unavailable capability; use the declared tool schemas.'}, 'running'
                db.execute('RELEASE planner_tool')
                db.execute('INSERT INTO agent_steps VALUES(?,?,?,?)',
                           (run_id, position, receipt['tool'], json.dumps(result)))
                if status == 'running' and position + 1 >= source['max_turns']:
                    result, status = {'revision': source['revision'], 'ambiguous': [],
                                      'message': 'The turn allowance is exhausted. Start a new request with more context.',
                                      'reply_version': REPLY_VERSION, 'reply_code': 'turn_limit'}, 'needs_input'
                if status != 'running':
                    self._finish(db, run_id, result, status)
        return self.read(run_id)

    def _finish(self, db, run_id, result, status):
        db.execute('UPDATE agent_runs SET status=? WHERE id=?', (status, run_id))
        db.execute('UPDATE planner_jobs SET outcome=? WHERE run_id=?', (json.dumps(result), run_id))
        self.conversations.finish(db, run_id, result, status)

    def _tool(self, db, run_id, source, history, call, classified, captured_review=None):
        name, args = call['tool'], call['arguments']
        if name in {'read_campaign', 'inspect_catalog', 'classify_catalog', 'review_performance', 'load_experiment_evidence'} and args:
            raise ValueError('Unexpected fields')
        if name == 'read_campaign':
            draft = self.drafts._read(db)
            package = self.drafts._package_review(db, self.drafts.campaign_id, draft['revision'])[0]['package']
            corrections = [self.owner.performance.correction_for_comparison(db, package, group['creative_version'])
                           for group in package['groups']]
            return {'brief': draft['brief'], 'policy': draft['policy'], 'revision': draft['revision'],
                    'draft_permission': source.get('draft_permission', 'none'),
                    'package_approved': self.drafts._package_review(db, self.drafts.campaign_id, draft['revision'])[0]['approval'] is not None,
                    'reporting_scenario': source.get('reporting_scenario', 'balanced'),
                    'instruction_test_id': source.get('instruction_test_id'),
                    'placements': [{key: row[key] for key in ('id', 'creative', 'source')} for row in draft['placements'][:30]],
                    'placement_count': len(draft['placements']), 'buyer_corrections': [item for item in corrections if item]}, 'running'
        if name == 'inspect_catalog':
            rows = self.catalogs.read(db, source['catalog_id'])
            return {'entries': [{**row, 'description': row['description'][:300], 'source_reference': row['source_reference'][:200]} for row in rows[:10]],
                    'total': len(rows), 'shown': min(10, len(rows))}, 'running'
        if name == 'validate_campaign_setup' and not args:
            revision = source['revision']
            try:
                setup = self.owner.setup.validate(self.drafts.campaign_id, revision,
                                                  source.get('fingerprint'), connection=db)
            except PackageConflict:
                return {'revision': revision, 'ambiguous': [], 'reply_version': REPLY_VERSION,
                        'reply_code': 'setup_package_required',
                        'message': 'Review and approve the current package before validating its setup.'}, 'needs_input'
            return {'revision': revision, 'ambiguous': [], 'reply_version': REPLY_VERSION,
                    'reply_code': 'setup_validated', 'setup_id': setup['id'],
                    'message': f'The simulated setup for revision {revision} is available in Campaign setup.'}, 'answered'
        if name == 'classify_catalog':
            return classified, 'running'
        if name == 'review_performance':
            return self.review_tools.review(db, source, captured_review)
        if (name == 'review_google_ads_delivery' and not args and source.get('delivery_request')
                and not source.get('delivery_next_test')):
            report = None
            if captured_review is not None:
                try:
                    report = self.owner.delivery.save(db, self.drafts.campaign_id, source['revision'],
                                                      source['fingerprint'], captured_review)
                except PackageConflict:
                    pass
            message = delivery_message(report) if report else (
                'Verify the current campaign setup in the workspace before reviewing delivery and tagged viewer activity.')
            return {'revision': source['revision'], 'ambiguous': [], 'message': message,
                    'reply_version': REPLY_VERSION, 'reply_code': 'google_ads_delivery',
                    'delivery_report_id': report['id'] if report else None}, 'answered' if report else 'needs_input'
        if name == 'recommend_delivery_next_test' and not args and source.get('delivery_next_test'):
            recommendation = None
            try:
                recommendation = self.owner.delivery.recommend(
                    self.drafts.campaign_id, source['revision'], source['fingerprint'],
                    source.get('delivery_report_id'), connection=db)
            except PackageConflict:
                pass
            message = recommendation_message(recommendation) if recommendation else (
                'Open the latest saved delivery review for this approved package and ask again.')
            return {'revision': source['revision'], 'ambiguous': [], 'message': message,
                    'reply_version': REPLY_VERSION, 'reply_code': 'delivery_next_test',
                    'delivery_report_id': recommendation['report_id'] if recommendation else None,
                    'delivery_recommendation_id': recommendation['id'] if recommendation else None}, (
                        'answered' if recommendation else 'needs_input')
        if name == 'load_experiment_evidence':
            return self.review_tools.load_experiment(db, source)
        if name == 'assess_instruction_experiment':
            return self.review_tools.assess_experiment(db, run_id, source, history, call)
        if name == 'prepare_next_test':
            return self.review_tools.prepare(db, run_id, source, history, call)
        if name == 'save_placement_draft' and set(args) in ({'video_ids'}, {'contexts'}):
            if not permits(source, name):
                return self.review_tools.outcome(source['revision'], None, 'placement_draft_not_authorized'), 'needs_input'
            classification = next((step['result'] for step in reversed(history)
                                   if step['tool'] == 'classify_catalog' and 'error' not in step['result']), None)
            if classification is None:
                raise ValueError('Classify catalog first')
            selected = args.get('video_ids')
            if 'contexts' in args:
                contexts = args['contexts']
                known = self.drafts._read(db)['brief']['contexts']
                if (not isinstance(contexts, list) or not contexts or any(not isinstance(item, str) or item not in known for item in contexts)
                        or len(contexts) != len(set(contexts))):
                    raise ValueError('Choose known campaign contexts')
                selected = [item['id'] for item in classification['assignments'] if item['context'] in contexts]
            saved = self.catalogs.save(db, source['catalog_id'], source['revision'],
                                       classification['assignments'], selected)
            rows = {row['video_id']: row for row in self.catalogs.read(db, source['catalog_id'])}
            ambiguous = [{'id': item['id'], 'title': rows[item['id']]['description'], 'creative': 'review',
                          'source': rows[item['id']]['source']} for item in classification['assignments'] if item['context'] == 'review']
            return {'revision': saved['revision'], 'ambiguous': ambiguous,
                    'message': 'Placement draft saved for package review. Classifications are simulated.'}, 'ready_for_review'
        if name == 'ask_clarification' and set(args) == {'reason'}:
            return clarification(args['reason'], source['revision']), 'needs_input'
        if name == 'respond' and set(args) == {'topic'}:
            if args['topic'] == 'performance_review':
                return self.review_tools.explain(db, source, history)
            if args['topic'] == 'experiment_review':
                return self.review_tools.explain_experiment(db, source, history)
            draft = self.drafts._read(db)
            approved = False
            if args['topic'] == 'approval_and_launch':
                approved = self.drafts._package_review(db, self.drafts.campaign_id, draft['revision'])[0]['approval'] is not None
            capabilities = self.owner.capabilities() if args['topic'] == 'capabilities' else None
            return reply(args['topic'], draft, approved=approved, capabilities=capabilities), 'answered'
        raise ValueError('Unknown tool')

    def read(self, run_id):
        self.owner.require("youtube:campaign.read")
        with closing(sqlite3.connect(self.path)) as db:
            request, status = self.owner._owned_run(db, run_id)
            snapshot, outcome = db.execute('SELECT snapshot,outcome FROM planner_jobs WHERE run_id=?', (run_id,)).fetchone()
            source = json.loads(snapshot)
            turns = [{'position': position, 'state': state, 'inference': json.loads(receipt).get('inference') if receipt else None}
                     for position, state, receipt in db.execute('SELECT position,state,receipt FROM planner_turns WHERE run_id=? ORDER BY position', (run_id,))]
            return {'run_id': run_id, 'request': request, 'status': status, 'steps': self._history(db, run_id),
                    'result': verified_result(json.loads(outcome), status) if outcome else None,
                    'planner': {'session_id': source['session_id'], 'settings': source['settings'],
                                'draft_permission': source.get('draft_permission', 'none'),
                                'execution': 'application' if source.get('delivery_request') else 'model',
                                'delivery_demo_scenario': source.get('delivery_demo_scenario'),
                                'routing': source['routing'], 'max_turns': source['max_turns'], 'turns': turns}}
