"""Campaign-scoped buyer/agent transcripts; messages confer no execution authority."""
from contextlib import closing
import json
import sqlite3

from campaign_agent.access import LOCAL_BRAND
from scripts.campaign_drafts import PackageConflict
from .replies import verified_result

MAX_CONTEXT_MESSAGES = 20
MAX_CONTEXT_BYTES = 8_000


def bounded_context(messages):
    """Keep a whole-message suffix, accounting for JSON nested in the provider's JSON body."""
    kept = []
    for saved in reversed(messages):
        # Transcript inspectors retain full evidence; dialogue carries its reference and reloads current facts through tools.
        message = {key: value for key, value in saved.items() if key not in {'review', 'experiment_review'}}
        if message.pop('delivery_report_id', None):
            message['content'] = 'A campaign delivery review was saved in the workspace.'
        for evidence in ('review', 'experiment_review'):
            if saved.get(evidence):
                message[evidence + '_id'] = saved[evidence]['id']
        candidate = [message, *kept]
        if len(json.dumps(json.dumps(candidate)).encode()) > MAX_CONTEXT_BYTES:
            break
        kept = candidate
    return kept


class CampaignConversations:
    def __init__(self, planner):
        self.planner = planner
        self.path, self.operator = planner.path, planner.owner.operator
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            columns = {row[1] for row in db.execute('PRAGMA table_info(planner_sessions)')}
            if 'campaign_id' not in columns:
                db.execute("ALTER TABLE planner_sessions ADD COLUMN campaign_id TEXT NOT NULL DEFAULT 'tts-sample'")
            existed = db.execute("SELECT 1 FROM sqlite_master WHERE name='planner_messages' AND type='table'").fetchone()
            db.execute('''CREATE TABLE IF NOT EXISTS planner_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, run_id TEXT NOT NULL,
                role TEXT NOT NULL, content TEXT NOT NULL, revision INTEGER NOT NULL,
                catalog_id TEXT NOT NULL, kind TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE(run_id,role))''')
            if not existed:
                for run_id, session_id, snapshot, outcome, status in db.execute(
                        'SELECT j.run_id,j.session_id,j.snapshot,j.outcome,r.status FROM planner_jobs j '
                        'JOIN agent_runs r ON r.id=j.run_id ORDER BY j.rowid'):
                    source = json.loads(snapshot)
                    self.append(db, session_id, run_id, 'user', source['request'], source['revision'], source['catalog_id'], 'request')
                    if outcome:
                        result = json.loads(outcome)
                        self.finish(db, run_id, result, status)

    def session(self, db, session_id):
        self.operator.require_brand(LOCAL_BRAND)
        row = db.execute('SELECT client_id,brand_id,actor_id,settings,campaign_id FROM planner_sessions WHERE id=?',
                         (session_id,)).fetchone()
        if row is None:
            return None
        if row[:3] != (LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, self.operator.id) or row[4] != self.planner.drafts.campaign_id:
            raise PermissionError('Conversation unavailable in this campaign.')
        return json.loads(row[3])

    def messages(self, db, session_id, limit=None):
        rows = db.execute('''SELECT m.id,m.role,m.content,m.run_id,m.revision,m.catalog_id,m.kind,m.created_at,j.outcome
                             FROM planner_messages m JOIN planner_jobs j ON j.run_id=m.run_id
                             WHERE m.session_id=? ORDER BY m.id DESC LIMIT ?''',
                          (session_id, limit or -1)).fetchall()
        keys = ('id', 'role', 'content', 'run_id', 'revision', 'catalog_id', 'kind', 'created_at')
        messages = []
        for row in reversed(rows):
            message = dict(zip(keys, row[:8]))
            if message['role'] == 'assistant':
                result = verified_result(json.loads(row[8] or '{}'), message['kind'])
                if message['kind'] in {'answered', 'needs_input'}:
                    message['content'] = result['message']
                    if result.get('needs_verification'):
                        message['kind'] = 'needs_verification'
                if result.get('reply_version') == 1 and not result.get('needs_verification'):
                    if result.get('delivery_report_id'):
                        message['delivery_report_id'] = result['delivery_report_id']
                    for source, field in (('performance_review', 'review'), ('experiment_review', 'experiment_review')):
                        if result.get(source):
                            message[field] = result[source]
                            message['review_needs_refresh'] = result.get('review_needs_refresh', False)
            messages.append(message)
        return messages

    def append(self, db, session_id, run_id, role, content, revision, catalog_id, kind):
        db.execute('''INSERT INTO planner_messages(session_id,run_id,role,content,revision,catalog_id,kind)
                      VALUES(?,?,?,?,?,?,?) ON CONFLICT(run_id,role) DO NOTHING''',
                   (session_id, run_id, role, content, revision, catalog_id, kind))

    def finish(self, db, run_id, result, kind):
        session_id, snapshot = db.execute('SELECT session_id,snapshot FROM planner_jobs WHERE run_id=?', (run_id,)).fetchone()
        source = json.loads(snapshot)
        self.append(db, session_id, run_id, 'assistant', result.get('message') or 'Request completed.',
                    result.get('revision', source['revision']), source['catalog_id'], kind)

    def begin(self, db, session_id, settings, run_id, request, catalog_id, revision, after_message):
        saved_settings = self.session(db, session_id)
        if (saved_settings is not None and
                {key: value for key, value in saved_settings.items() if key != 'prompt_version'} !=
                {key: value for key, value in settings.items() if key != 'prompt_version'}):
            raise PermissionError('Start a new conversation to change its model.')
        latest = db.execute('SELECT COALESCE(MAX(id),0) FROM planner_messages WHERE session_id=?', (session_id,)).fetchone()[0]
        if after_message is not None and after_message != latest:
            raise PackageConflict('The conversation changed. Read the latest messages before sending your follow-up.')
        # A deliberate follow-up supersedes unfinished work. Late receipts cannot commit a tool result.
        for previous, in db.execute('''SELECT j.run_id FROM planner_jobs j JOIN agent_runs r ON r.id=j.run_id
                                      WHERE j.session_id=? AND r.status='running' ''', (session_id,)).fetchall():
            outcome = {'revision': revision, 'ambiguous': [], 'message': 'This unfinished request was superseded by your follow-up.'}
            db.execute("UPDATE agent_runs SET status='superseded' WHERE id=?", (previous,))
            db.execute('UPDATE planner_jobs SET outcome=? WHERE run_id=?', (json.dumps(outcome), previous))
            self.finish(db, previous, outcome, 'superseded')
        memory = bounded_context(self.messages(db, session_id, limit=MAX_CONTEXT_MESSAGES))
        count = db.execute('SELECT COUNT(*) FROM planner_messages WHERE session_id=?', (session_id,)).fetchone()[0]
        db.execute('''INSERT INTO planner_sessions(id,client_id,brand_id,actor_id,settings,campaign_id)
                      VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING''',
                   (session_id, LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, self.operator.id,
                    json.dumps(settings), self.planner.drafts.campaign_id))
        db.execute('UPDATE planner_sessions SET settings=? WHERE id=?', (json.dumps(settings), session_id))
        self.append(db, session_id, run_id, 'user', request, revision, catalog_id, 'request')
        return memory, count > len(memory)

    def read(self, session_id):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN')
            settings = self.session(db, session_id)
            if settings is None:
                raise LookupError('Conversation unavailable.')
            messages = self.messages(db, session_id)
            return {'id': session_id, 'campaign_id': self.planner.drafts.campaign_id, 'settings': settings,
                    'messages': messages, 'latest_message': messages[-1]['id'] if messages else 0,
                    'latest_run_id': messages[-1]['run_id'] if messages else None}

    def list(self):
        self.operator.require_brand(LOCAL_BRAND)
        with closing(sqlite3.connect(self.path)) as db:
            return [{'id': key, 'model': json.loads(settings)['model'], 'title': title[:80]}
                    for key, settings, title in db.execute('''
                        SELECT s.id,s.settings,(SELECT content FROM planner_messages WHERE session_id=s.id ORDER BY id LIMIT 1)
                        FROM planner_sessions s WHERE client_id=? AND brand_id=? AND actor_id=? AND campaign_id=?
                        ORDER BY (SELECT MAX(id) FROM planner_messages WHERE session_id=s.id) DESC''',
                        (LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, self.operator.id, self.planner.drafts.campaign_id))
                    if title]
