"""Fixed native run/step records on a caller-owned SQLite connection.

Raw rows and text pass through. Borrowing commands retain authorization, JSON,
policy and their transaction lifecycle. SQLiteRunStorage owns native startup and
scoped legacy campaign backfill.
"""

import sqlite3
from contextlib import closing


class SQLiteRunStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def scoped_run_row(self, run_id, client_id, brand_id, actor_id, campaign_id):
        return self.connection.execute(
            'SELECT request, status FROM agent_runs WHERE id=? AND client_id=? '
            'AND brand_id=? AND actor_id=? AND campaign_id=?',
            (run_id, client_id, brand_id, actor_id, campaign_id),
        ).fetchone()

    def create_run(self, run_id, client_id, brand_id, actor_id, request, status, campaign_id):
        self.connection.execute(
            'INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?)',
            (run_id, client_id, brand_id, actor_id, request, status, campaign_id),
        )

    def create_run_if_id_absent(self, run_id, client_id, brand_id, actor_id, request, status, campaign_id):
        self.connection.execute(
            'INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
            (run_id, client_id, brand_id, actor_id, request, status, campaign_id),
        )

    def create_run_if_no_conflict(self, run_id, client_id, brand_id, actor_id, request, status, campaign_id):
        self.connection.execute(
            'INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',
            (run_id, client_id, brand_id, actor_id, request, status, campaign_id),
        )

    def update_status(self, run_id, status):
        self.connection.execute('UPDATE agent_runs SET status=? WHERE id=?', (status, run_id))

    def step_rows(self, run_id):
        return self.connection.execute(
            'SELECT tool, result FROM agent_steps WHERE run_id=? ORDER BY position', (run_id,),
        ).fetchall()

    def append_step(self, run_id, position, tool, result):
        self.connection.execute('INSERT INTO agent_steps VALUES(?,?,?,?)', (run_id, position, tool, result))

    def step_count(self, run_id):
        return self.connection.execute('SELECT COUNT(*) FROM agent_steps WHERE run_id=?', (run_id,)).fetchone()[0]

    def step_exists_row(self, run_id, position):
        return self.connection.execute(
            'SELECT 1 FROM agent_steps WHERE run_id=? AND position=?', (run_id, position),
        ).fetchone()


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
