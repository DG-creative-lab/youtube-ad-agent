"""Native planner records on a caller-owned SQLite connection.

Application commands retain JSON, authorization, inference/recovery decisions,
schema initialization and transaction ownership for those legacy records. Rows
and text pass through. SQLiteCatalogStorage separately owns the first adopted
catalogue transactions.
"""

import sqlite3
from contextlib import closing, contextmanager

from campaign_agent.ports.catalogs import (
    CatalogEntry, CatalogRecord, CatalogScope, CatalogStorageError, CatalogUnitClosed,
)


class SQLitePlannerStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def default_row(self, client_id, brand_id, actor_id):
        return self.connection.execute(
            'SELECT model FROM planner_defaults WHERE client_id=? AND brand_id=? AND actor_id=?',
            (client_id, brand_id, actor_id),
        ).fetchone()

    def job_exists_row(self, run_id):
        return self.connection.execute('SELECT 1 FROM planner_jobs WHERE run_id=?', (run_id,)).fetchone()

    def job_snapshot_row(self, run_id):
        return self.connection.execute('SELECT snapshot FROM planner_jobs WHERE run_id=?', (run_id,)).fetchone()

    def upsert_default(self, client_id, brand_id, actor_id, model):
        self.connection.execute(
            'INSERT INTO planner_defaults VALUES(?,?,?,?) ON CONFLICT DO UPDATE SET model=excluded.model',
            (client_id, brand_id, actor_id, model),
        )

    def create_job(self, run_id, session_id, snapshot):
        self.connection.execute(
            'INSERT INTO planner_jobs(run_id,session_id,snapshot) VALUES(?,?,?)',
            (run_id, session_id, snapshot),
        )

    def history_rows(self, run_id):
        return self.connection.execute(
            'SELECT s.tool,s.result,t.receipt FROM agent_steps s JOIN planner_turns t '
            'ON t.run_id=s.run_id AND t.position=s.position WHERE s.run_id=? ORDER BY s.position',
            (run_id,),
        ).fetchall()

    def classification_row(self, run_id):
        return self.connection.execute(
            'SELECT classification_state,classification FROM planner_jobs WHERE run_id=?', (run_id,),
        ).fetchone()

    def request_classification(self, run_id):
        self.connection.execute("UPDATE planner_jobs SET classification_state='requested' WHERE run_id=?", (run_id,))

    def fail_classification(self, run_id):
        self.connection.execute("UPDATE planner_jobs SET classification_state='failed' WHERE run_id=?", (run_id,))

    def receive_classification(self, run_id, classification):
        self.connection.execute(
            "UPDATE planner_jobs SET classification_state='received',classification=? WHERE run_id=?",
            (classification, run_id),
        )

    def turn_row(self, run_id, position):
        return self.connection.execute(
            'SELECT state,receipt,error FROM planner_turns WHERE run_id=? AND position=?', (run_id, position),
        ).fetchone()

    def request_turn(self, run_id, position):
        self.connection.execute(
            "INSERT INTO planner_turns VALUES(?,?,'requested',NULL,NULL) ON CONFLICT DO NOTHING", (run_id, position),
        )

    def fail_turn(self, run_id, position, error):
        self.connection.execute(
            "UPDATE planner_turns SET state='failed',error=? WHERE run_id=? AND position=?", (error, run_id, position),
        )

    def receive_turn(self, run_id, position, receipt):
        self.connection.execute(
            "UPDATE planner_turns SET state='received',receipt=? WHERE run_id=? AND position=?", (receipt, run_id, position),
        )

    def update_outcome(self, run_id, outcome):
        self.connection.execute('UPDATE planner_jobs SET outcome=? WHERE run_id=?', (outcome, run_id))

    def job_result_row(self, run_id):
        return self.connection.execute('SELECT snapshot,outcome FROM planner_jobs WHERE run_id=?', (run_id,)).fetchone()

    def turn_rows(self, run_id):
        return self.connection.execute(
            'SELECT position,state,receipt FROM planner_turns WHERE run_id=? ORDER BY position', (run_id,),
        ).fetchall()


# Catalogue commands are the first typed transaction adoption. The remaining
# planner stores above retain their existing caller-owned native connections.


class _CatalogRepository:
    def __init__(self, unit):
        self._unit = unit

    def list_catalogs(self, scope: CatalogScope) -> tuple[CatalogRecord, ...]:
        db = self._unit._connection()
        return tuple(CatalogRecord(key, scope, label, snapshot) for key, label, snapshot in db.execute(
            'SELECT id,label,snapshot FROM placement_catalogs WHERE client_id=? AND brand_id=? AND campaign_id=?',
            (scope.client_id, scope.brand_id, scope.campaign_id)))

    def add_catalog(self, record: CatalogRecord) -> None:
        db = self._unit._connection(write=True)
        db.execute('INSERT INTO placement_catalogs VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING',
                   (record.id, record.scope.client_id, record.scope.brand_id, record.scope.campaign_id,
                    record.label, record.snapshot))

    def add_entry(self, entry: CatalogEntry) -> None:
        db = self._unit._connection(write=True)
        db.execute('''INSERT INTO placement_catalog_entries
                   (ref,client_id,brand_id,campaign_id,video_id,title,source,source_reference)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING''',
                   (entry.ref, entry.scope.client_id, entry.scope.brand_id, entry.scope.campaign_id,
                    entry.video_id, entry.title, entry.source, entry.source_reference))


class _CatalogUnit:
    def __init__(self, db, *, writable):
        self._db, self._writable, self._active = db, writable, True
        self.catalogs = _CatalogRepository(self)

    def _connection(self, *, write=False):
        if not self._active:
            raise CatalogUnitClosed()
        if write and not self._writable:
            raise CatalogStorageError()
        return self._db

    def commit(self) -> None:
        self._connection(write=True).commit()
        self._active = False


class SQLiteCatalogStorage:
    """Own catalogue connections and atomic catalogue/provenance transactions."""
    def __init__(self, path):
        self._path = path

    def initialize(self):
        # CampaignDrafts has already initialized/adopted provenance entries.
        # Keep the original catalogue schema and startup ordering.
        try:
            with closing(sqlite3.connect(self._path)) as db, db:
                db.execute('''CREATE TABLE IF NOT EXISTS placement_catalogs (
                    id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL, label TEXT NOT NULL, snapshot TEXT NOT NULL)''')
        except sqlite3.Error:
            raise CatalogStorageError() from None

    @contextmanager
    def _unit(self, *, writable):
        try:
            with closing(sqlite3.connect(self._path)) as db:
                unit = _CatalogUnit(db, writable=writable)
                try:
                    db.execute('BEGIN')
                    yield unit
                finally:
                    unit._active = False
                    db.rollback()
        except sqlite3.Error:
            raise CatalogStorageError() from None

    @contextmanager
    def read(self):
        with self._unit(writable=False) as unit:
            yield unit.catalogs

    def write(self):
        return self._unit(writable=True)
