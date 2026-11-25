"""Native conversation records on a caller-owned SQLite connection.

Application commands retain authorization, JSON projection, schema initialization
and transaction ownership. Rows and text pass through unchanged.
"""

import sqlite3
from contextlib import closing, contextmanager
from campaign_agent.ports.conversations import SessionRecord, MessageRecord, JobContext, LegacyTranscript



class SQLiteConversationStore:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        self._adopting = False

    def session_row(self, session_id):
        row = self._connection.execute(
            'SELECT client_id,brand_id,actor_id,settings,campaign_id FROM planner_sessions WHERE id=?',
            (session_id,),
        ).fetchone()
        return SessionRecord(*row) if row is not None else None

    def message_rows(self, session_id, limit=-1):
        rows = self._connection.execute(
            '''SELECT m.id,m.role,m.content,m.run_id,m.revision,m.catalog_id,m.kind,m.created_at,j.outcome
               FROM planner_messages m JOIN planner_jobs j ON j.run_id=m.run_id
               WHERE m.session_id=? ORDER BY m.id DESC LIMIT ?''',
            (session_id, limit),
        ).fetchall()
        return [MessageRecord(*row) for row in rows]

    def append_message(self, session_id, run_id, role, content, revision, catalog_id, kind):
        self._connection.execute(
            '''INSERT INTO planner_messages(session_id,run_id,role,content,revision,catalog_id,kind)
               VALUES(?,?,?,?,?,?,?) ON CONFLICT(run_id,role) DO NOTHING''',
            (session_id, run_id, role, content, revision, catalog_id, kind),
        )

    def job_context_row(self, run_id):
        row = self._connection.execute(
            'SELECT session_id,snapshot FROM planner_jobs WHERE run_id=?', (run_id,),
        ).fetchone()
        return JobContext(*row) if row is not None else None

    def latest_message_id(self, session_id):
        return self._connection.execute(
            'SELECT COALESCE(MAX(id),0) FROM planner_messages WHERE session_id=?', (session_id,),
        ).fetchone()[0]

    def message_count(self, session_id):
        return self._connection.execute(
            'SELECT COUNT(*) FROM planner_messages WHERE session_id=?', (session_id,),
        ).fetchone()[0]

    def create_session(self, session_id, client_id, brand_id, actor_id, settings, campaign_id):
        self._connection.execute(
            '''INSERT INTO planner_sessions(id,client_id,brand_id,actor_id,settings,campaign_id)
               VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING''',
            (session_id, client_id, brand_id, actor_id, settings, campaign_id),
        )

    def update_settings(self, session_id, settings):
        self._connection.execute('UPDATE planner_sessions SET settings=? WHERE id=?', (settings, session_id))

    def list_rows(self, client_id, brand_id, actor_id, campaign_id):
        return self._connection.execute(
            '''SELECT s.id,s.settings,(SELECT content FROM planner_messages WHERE session_id=s.id ORDER BY id LIMIT 1)
               FROM planner_sessions s WHERE client_id=? AND brand_id=? AND actor_id=? AND campaign_id=?
               ORDER BY (SELECT MAX(id) FROM planner_messages WHERE session_id=s.id) DESC''',
            (client_id, brand_id, actor_id, campaign_id),
        ).fetchall()

    def running_runs(self, session_id):
        return tuple(row[0] for row in self._connection.execute(
            "SELECT j.run_id FROM planner_jobs j JOIN agent_runs r ON r.id=j.run_id "
            "WHERE j.session_id=? AND r.status='running' ", (session_id,)))

    def supersede(self, run_id, outcome):
        self._connection.execute("UPDATE agent_runs SET status='superseded' WHERE id=?", (run_id,))
        self._connection.execute('UPDATE planner_jobs SET outcome=? WHERE run_id=?', (outcome, run_id))

    def legacy_transcripts(self):
        if not self._adopting:
            return ()
        return (LegacyTranscript(*row) for row in self._connection.execute(
            'SELECT j.run_id,j.session_id,j.snapshot,j.outcome,r.status FROM planner_jobs j '
            'JOIN agent_runs r ON r.id=j.run_id ORDER BY j.rowid'))


class SQLiteConversationStorage:
    """Standalone readers and atomic native transcript adoption; planner borrows its own repo."""
    def __init__(self, path):
        self.path = path

    @contextmanager
    def initialize(self):
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
            store = SQLiteConversationStore(db)
            store._adopting = not existed
            yield store

    @contextmanager
    def read(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN')
            yield SQLiteConversationStore(db)
