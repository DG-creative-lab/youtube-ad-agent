"""Durable, bounded main-model loop over the placement application commands."""
from contextlib import closing
import json
import re
import sqlite3

from campaign_agent.access import LOCAL_BRAND
from campaign_agent.adapters.openrouter_reviews import ReviewInferenceError
from campaign_agent.handoff import package_fingerprint
from campaign_agent.placement_discovery import PlacementDiscovery, SimulatedClassifier
from scripts.campaign_drafts import PackageConflict
from .planning_models import OpenRouterPlanner, SimulatedPlanner
from .conversations import CampaignConversations
from .replies import REPLY_VERSION, clarification, reply, verified_result


ID = re.compile(r'[0-9a-f]{32}')
MAX_TURNS = 8
SIMULATED = ('simulated', 'simulated-inspect')


class PlacementAgent:
    def __init__(self, owner, models=(), *, transport=None, simulator=None, classifier=None):
        self.owner, self.path, self.drafts = owner, owner.path, owner.drafts
        self.catalogs = PlacementDiscovery(self.drafts)
        self.remote = OpenRouterPlanner(models, transport=transport)
        self.simulator = simulator or SimulatedPlanner()
        self.classifier = classifier or SimulatedClassifier()
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
        self.owner.operator.require_brand(LOCAL_BRAND)
        models = [{'id': 'simulated', 'label': 'Simulated agent', 'mode': 'simulated'},
                  {'id': 'simulated-inspect', 'label': 'Simulated agent · inspect first', 'mode': 'simulated'}]
        models += [{'id': item, 'label': item, 'mode': 'openrouter'} for item in self.remote.models]
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute('SELECT model FROM planner_defaults WHERE client_id=? AND brand_id=? AND actor_id=?',
                             (LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, self.owner.operator.id)).fetchone()
        default = row[0] if row and row[0] in {item['id'] for item in models} else 'simulated'
        return {'models': models, 'default': default, 'max_turns': MAX_TURNS,
                'specialist': 'simulated_decision', 'specialist_label': 'Automatic · simulated decision model'}

    def owns(self, run_id):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT 1 FROM planner_jobs WHERE run_id=?', (run_id,)).fetchone() is not None

    def start(self, request, model, session_id, run_id, catalog_id, after_message=None):
        self.owner.operator.require_brand(LOCAL_BRAND)
        if (any(not isinstance(value, str) or not ID.fullmatch(value) for value in (session_id, run_id, catalog_id))
                or not isinstance(request, str) or not request.strip() or len(request) > 1500):
            raise ValueError('Supply a request and valid session, run and catalog references.')
        if after_message is not None and (type(after_message) is not int or not 0 <= after_message < 2**63):
            raise ValueError('Supply a valid conversation message reference.')
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
                return run_id
            expected = (LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, self.owner.operator.id, json.dumps(settings))
            self.catalogs.read(db, catalog_id)
            current = self.drafts._read(db)
            previous, truncated = self.conversations.begin(db, session_id, settings, run_id, request,
                                                          catalog_id, current['revision'], after_message)
            context = {'request': request, 'session_id': session_id, 'catalog_id': catalog_id,
                       'revision': current['revision'], 'settings': settings,
                       'conversation': previous, 'conversation_truncated': truncated, 'after_message': after_message,
                       'routing': {'classifier': 'simulated_decision', 'max_classifier_calls': 1}, 'max_turns': MAX_TURNS}
            db.execute('INSERT INTO planner_defaults VALUES(?,?,?,?) ON CONFLICT DO UPDATE SET model=excluded.model',
                       (*expected[:3], model))
            db.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?)',
                       (run_id, *expected[:3], request, 'running'))
            db.execute('INSERT INTO planner_jobs(run_id,session_id,snapshot) VALUES(?,?,?)',
                       (run_id, session_id, json.dumps(context)))
        return run_id

    def _context(self, db, run_id):
        self.owner.operator.require_brand(LOCAL_BRAND)
        _, status = self.owner._owned_run(db, run_id)
        if status != 'running':
            raise PackageConflict('This request is no longer active. Read the latest conversation.')
        source = json.loads(db.execute('SELECT snapshot FROM planner_jobs WHERE run_id=?', (run_id,)).fetchone()[0])
        if self.conversations.session(db, source['session_id']) != source['settings']:
            raise PermissionError('The conversation scope or model has changed.')
        if self.drafts._read(db)['revision'] != source['revision']:
            raise PackageConflict('The campaign changed. Start a new placement request from the latest revision.')
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
        for _ in range(max_steps):
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                _, status = self.owner._owned_run(db, run_id)
                self.owner.operator.require_brand(LOCAL_BRAND)
                if status != 'running':
                    return self.read(run_id)
                source = self._context(db, run_id)
                history = self._history(db, run_id)
                position = len(history)
                row = db.execute('SELECT state,receipt,error FROM planner_turns WHERE run_id=? AND position=?',
                                 (run_id, position)).fetchone()
                if row and row[0] != 'received':
                    raise ReviewInferenceError(row[2] or 'This model request is in progress or its outcome is unknown. Start a new run.')
                receipt = json.loads(row[1]) if row else None
                if not row:
                    if source['settings']['mode'] == 'openrouter':
                        self.remote.require_available(source['settings'])
                        self.remote.prepare_turn(source, history, source['settings'])
                    db.execute("INSERT INTO planner_turns VALUES(?,?,'requested',NULL,NULL)", (run_id, position))
            if receipt is None:
                try:
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
            classified = None
            if receipt['tool'] == 'classify_catalog' and not receipt['arguments']:
                classified = self._classify(run_id)
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                _, status = self.owner._owned_run(db, run_id)
                if status != 'running':
                    return self.read(run_id)
                source = self._context(db, run_id)
                if db.execute('SELECT 1 FROM agent_steps WHERE run_id=? AND position=?', (run_id, position)).fetchone():
                    continue
                history = self._history(db, run_id)
                db.execute('SAVEPOINT planner_tool')
                try:
                    result, status = self._tool(db, run_id, source, history, receipt, classified)
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
                    db.execute('UPDATE agent_runs SET status=? WHERE id=?', (status, run_id))
                    db.execute('UPDATE planner_jobs SET outcome=? WHERE run_id=?', (json.dumps(result), run_id))
                    self.conversations.finish(db, run_id, result, status)
        return self.read(run_id)

    def _tool(self, db, run_id, source, history, call, classified):
        name, args = call['tool'], call['arguments']
        if name in {'read_campaign', 'inspect_catalog', 'classify_catalog'} and args:
            raise ValueError('Unexpected fields')
        if name == 'read_campaign':
            draft = self.drafts._read(db)
            package = self.drafts._package_review(db, self.drafts.campaign_id, draft['revision'])[0]['package']
            corrections = [self.owner.performance.correction_for_comparison(db, package, group['creative_version'])
                           for group in package['groups']]
            return {'brief': draft['brief'], 'policy': draft['policy'], 'revision': draft['revision'],
                    'placements': [{key: row[key] for key in ('id', 'creative', 'source')} for row in draft['placements'][:30]],
                    'placement_count': len(draft['placements']), 'buyer_corrections': [item for item in corrections if item]}, 'running'
        if name == 'inspect_catalog':
            rows = self.catalogs.read(db, source['catalog_id'])
            return {'entries': [{**row, 'description': row['description'][:300], 'source_reference': row['source_reference'][:200]} for row in rows[:10]],
                    'total': len(rows), 'shown': min(10, len(rows))}, 'running'
        if name == 'classify_catalog':
            return classified, 'running'
        if name == 'save_placement_draft' and set(args) in ({'video_ids'}, {'contexts'}):
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
            draft = self.drafts._read(db)
            approved = False
            if args['topic'] == 'approval_and_launch':
                approved = self.drafts._package_review(db, self.drafts.campaign_id, draft['revision'])[0]['approval'] is not None
            return reply(args['topic'], draft, approved=approved), 'answered'
        raise ValueError('Unknown tool')

    def read(self, run_id):
        self.owner.operator.require_brand(LOCAL_BRAND)
        with closing(sqlite3.connect(self.path)) as db:
            request, status = self.owner._owned_run(db, run_id)
            snapshot, outcome = db.execute('SELECT snapshot,outcome FROM planner_jobs WHERE run_id=?', (run_id,)).fetchone()
            source = json.loads(snapshot)
            turns = [{'position': position, 'state': state, 'inference': json.loads(receipt).get('inference') if receipt else None}
                     for position, state, receipt in db.execute('SELECT position,state,receipt FROM planner_turns WHERE run_id=? ORDER BY position', (run_id,))]
            return {'run_id': run_id, 'request': request, 'status': status, 'steps': self._history(db, run_id),
                    'result': verified_result(json.loads(outcome), status) if outcome else None,
                    'planner': {'session_id': source['session_id'], 'settings': source['settings'],
                                'routing': source['routing'], 'max_turns': source['max_turns'], 'turns': turns}}
