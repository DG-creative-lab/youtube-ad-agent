"""Fixed native run/step records on a caller-owned SQLite connection.

Raw rows and text pass through. Borrowing commands retain authorization, JSON,
policy and their transaction lifecycle. SQLiteRunStorage owns native startup and
scoped legacy campaign backfill.
"""

import sqlite3
from contextlib import closing

from campaign_agent.ports.agent_runs import StructuredInferenceRow


class SQLiteRunStore:
    def __init__(self, connection: sqlite3.Connection):
        self._db = connection

    @property
    def _connection(self):
        return self._db

    def scoped_run_row(self, run_id, client_id, brand_id, actor_id, campaign_id):
        return self._connection.execute(
            'SELECT request, status FROM agent_runs WHERE id=? AND client_id=? '
            'AND brand_id=? AND actor_id=? AND campaign_id=?',
            (run_id, client_id, brand_id, actor_id, campaign_id),
        ).fetchone()

    def create_run(self, run_id, client_id, brand_id, actor_id, request, status, campaign_id):
        self._connection.execute(
            'INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?)',
            (run_id, client_id, brand_id, actor_id, request, status, campaign_id),
        )

    def create_run_if_id_absent(self, run_id, client_id, brand_id, actor_id, request, status, campaign_id):
        self._connection.execute(
            'INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
            (run_id, client_id, brand_id, actor_id, request, status, campaign_id),
        )

    def create_run_if_no_conflict(self, run_id, client_id, brand_id, actor_id, request, status, campaign_id):
        self._connection.execute(
            'INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',
            (run_id, client_id, brand_id, actor_id, request, status, campaign_id),
        )

    def update_status(self, run_id, status):
        self._connection.execute('UPDATE agent_runs SET status=? WHERE id=?', (status, run_id))

    def step_rows(self, run_id):
        return self._connection.execute(
            'SELECT tool, result FROM agent_steps WHERE run_id=? ORDER BY position', (run_id,),
        ).fetchall()

    def append_step(self, run_id, position, tool, result):
        self._connection.execute('INSERT INTO agent_steps VALUES(?,?,?,?)', (run_id, position, tool, result))

    def step_count(self, run_id):
        return self._connection.execute('SELECT COUNT(*) FROM agent_steps WHERE run_id=?', (run_id,)).fetchone()[0]

    def step_exists_row(self, run_id, position):
        return self._connection.execute(
            'SELECT 1 FROM agent_steps WHERE run_id=? AND position=?', (run_id, position),
        ).fetchone()


    def structured_source_row(self, run_id):
        return self._connection.execute(
            'SELECT source FROM agent_test_sources WHERE run_id=?', (run_id,),
        ).fetchone()

    def structured_settings_row(self, run_id):
        return self._connection.execute(
            'SELECT settings FROM agent_review_inference WHERE run_id=?', (run_id,),
        ).fetchone()

    def structured_start_row(self, run_id):
        return self._connection.execute(
            'SELECT s.source, i.settings FROM agent_test_sources s JOIN agent_review_inference i '
            'ON i.run_id=s.run_id WHERE s.run_id=?', (run_id,),
        ).fetchone()

    def structured_inference_row(self, run_id):
        row = self._connection.execute(
            'SELECT settings,state,receipt,error FROM agent_review_inference WHERE run_id=?', (run_id,),
        ).fetchone()
        return StructuredInferenceRow(*row) if row is not None else None

    def add_structured_source(self, run_id, source, *, ignore_existing=False):
        sql = 'INSERT INTO agent_test_sources (run_id, source) VALUES (?, ?)'
        if ignore_existing:
            sql += ' ON CONFLICT DO NOTHING'
        self._connection.execute(sql, (run_id, source))

    def add_structured_settings(self, run_id, settings, *, ignore_existing=False):
        sql = 'INSERT INTO agent_review_inference (run_id, settings) VALUES (?, ?)'
        if ignore_existing:
            sql += ' ON CONFLICT DO NOTHING'
        self._connection.execute(sql, (run_id, settings))

    def request_structured_inference(self, run_id):
        self._connection.execute("UPDATE agent_review_inference SET state='requested' WHERE run_id=?", (run_id,))

    def fail_structured_inference(self, run_id, error):
        self._connection.execute(
            "UPDATE agent_review_inference SET state='failed', error=? WHERE run_id=?", (error, run_id),
        )

    def receive_structured_inference(self, run_id, receipt):
        self._connection.execute(
            "UPDATE agent_review_inference SET state='received', receipt=? WHERE run_id=?", (receipt, run_id),
        )


class SQLiteRunStorage:
    """Explicit native startup; only the authored local scope adopts legacy runs."""
    @staticmethod
    def initialize(path, *, legacy_client_id, legacy_brand_id):
        with closing(sqlite3.connect(path)) as db, db:
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
                           (legacy_client_id, legacy_brand_id))
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
