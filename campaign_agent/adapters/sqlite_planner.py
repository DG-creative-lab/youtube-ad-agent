"""Native planner records on a caller-owned SQLite connection.

Application commands retain JSON, authorization and inference/recovery decisions.
Borrowed stores keep the caller transaction; lifecycle helpers own native startup
and separate receipt writes. Rows and text pass through. Dedicated catalogue, read
snapshot and placement commit adapters own their adopted transactions.
"""

import sqlite3
from .sqlite_runs import SQLiteRunStore
from .sqlite_drafts import SQLiteDraftRepository
from .sqlite_planner_context import SQLitePlannerContext
from campaign_agent.ports.storage_errors import StorageError, StorageClosed
from campaign_agent.ports.planner_records import PlannerRunScope
from .sqlite_conversations import SQLiteConversationStore, SQLiteConversationStorage
from contextlib import closing, contextmanager

from campaign_agent.ports.catalogs import (
    CatalogEntry, CatalogRecord, CatalogScope, CatalogStorageError, CatalogUnitClosed,
)


class SQLitePlannerStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def scoped_run_row(self, run_id: str, scope: PlannerRunScope):
        return SQLiteRunStore(self.connection).scoped_run_row(
            run_id, scope.client_id, scope.brand_id, scope.actor_id, scope.campaign_id)

    @property
    def catalogs(self):
        return _CatalogRepository(_CatalogUnit(self.connection, writable=False))

    @property
    def placement_repositories(self):
        return SQLitePlacementRepositories(self.connection)

    @property
    def conversations(self):
        return SQLiteConversationStore(self.connection)

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

    def read_snapshot(self, scope: CatalogScope, catalog_id: str):
        return self._unit._connection().execute(
            'SELECT snapshot FROM placement_catalogs WHERE id=? AND client_id=? AND brand_id=? AND campaign_id=?',
            (catalog_id, scope.client_id, scope.brand_id, scope.campaign_id)).fetchone()

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


class _SQLitePlannerReader:
    """Expose only projection operations, keeping native handles inside the adapter."""
    def __init__(self, store):
        self._store = store

    def default_row(self, client_id, brand_id, actor_id):
        return self._store.default_row(client_id, brand_id, actor_id)

    def job_exists_row(self, run_id):
        return self._store.job_exists_row(run_id)

    def scoped_run_row(self, run_id, scope):
        return self._store.scoped_run_row(run_id, scope)

    def job_result_row(self, run_id):
        return self._store.job_result_row(run_id)

    def turn_rows(self, run_id):
        return self._store.turn_rows(run_id)

    def history_rows(self, run_id):
        return self._store.history_rows(run_id)


class SQLitePlannerReadStorage:
    """Keep the scoped status, outcome and receipt projection on one snapshot."""
    def __init__(self, path):
        self._path = path

    @contextmanager
    def read(self):
        with closing(sqlite3.connect(self._path)) as db, db:
            db.execute('BEGIN')
            yield _SQLitePlannerReader(SQLitePlannerStore(db))


class _PlacementRuns:
    def __init__(self, db):
        self._store = SQLiteRunStore(db)

    def create_run(self, run_id, scope, request, status):
        self._store.create_run(run_id, scope.client_id, scope.brand_id, scope.actor_id,
                               request, status, scope.campaign_id)

    def scoped_run_row(self, run_id, scope):
        return self._store.scoped_run_row(run_id, scope.client_id, scope.brand_id, scope.actor_id, scope.campaign_id)

    def step_exists_row(self, run_id, position):
        return self._store.step_exists_row(run_id, position)

    def append_step(self, run_id, position, tool, result):
        self._store.append_step(run_id, position, tool, result)

    def update_status(self, run_id, status):
        self._store.update_status(run_id, status)


class _PlacementPlanner:
    def __init__(self, db):
        self._store = SQLitePlannerStore(db)

    def default_row(self, client_id, brand_id, actor_id):
        return self._store.default_row(client_id, brand_id, actor_id)

    def create_job(self, run_id, session_id, snapshot):
        self._store.create_job(run_id, session_id, snapshot)

    def upsert_default(self, client_id, brand_id, actor_id, model):
        self._store.upsert_default(client_id, brand_id, actor_id, model)

    def job_result_row(self, run_id):
        return self._store.job_result_row(run_id)

    def turn_rows(self, run_id):
        return self._store.turn_rows(run_id)

    def turn_row(self, run_id, position):
        return self._store.turn_row(run_id, position)

    def request_turn(self, run_id, position):
        self._store.request_turn(run_id, position)

    def classification_row(self, run_id):
        return self._store.classification_row(run_id)

    def request_classification(self, run_id):
        self._store.request_classification(run_id)

    def job_snapshot_row(self, run_id):
        return self._store.job_snapshot_row(run_id)

    def history_rows(self, run_id):
        return self._store.history_rows(run_id)

    def update_outcome(self, run_id, outcome):
        self._store.update_outcome(run_id, outcome)


class SQLitePlacementRepositories:
    def __init__(self, db):
        self._db, self._active = db, True
        self.context = SQLitePlannerContext(db)
        self.runs = _PlacementRuns(db)
        self.planner = _PlacementPlanner(db)
        self.drafts = SQLiteDraftRepository(db)
        self.catalogs = _CatalogRepository(self)
        self.conversations = SQLiteConversationStore(db)

    def _connection(self, *, write=False):
        if not self._active:
            raise RuntimeError('Placement transaction is closed.')
        return self._db

class _PlacementCommitUnit(SQLitePlacementRepositories):
    @contextmanager
    def tool_attempt(self):
        db = self._connection()
        db.execute('SAVEPOINT planner_tool')
        try:
            yield
        except BaseException:
            db.execute('ROLLBACK TO planner_tool')
            raise
        finally:
            db.execute('RELEASE planner_tool')

    def commit(self):
        self._connection().commit()
        self._active = False


class SQLitePlacementCommitStorage:
    """The receipt was already saved; only the local placement effects commit here."""
    def __init__(self, path):
        self._path = path

    @contextmanager
    def write(self):
        with closing(sqlite3.connect(self._path)) as db:
            unit = _PlacementCommitUnit(db)
            try:
                db.execute('BEGIN IMMEDIATE')
                yield unit
            finally:
                unit._active = False
                db.rollback()


class SQLitePlannerLifecycleStorage:
    """Initialize native planner tables and persist each receipt phase separately."""
    def __init__(self, path):
        self._path = path

    @staticmethod
    def initialize(path):
        with closing(sqlite3.connect(path)) as db, db:
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

    def fail_classification(self, run_id):
        with closing(sqlite3.connect(self._path)) as db, db:
            SQLitePlannerStore(db).fail_classification(run_id)

    def receive_classification(self, run_id, classification):
        with closing(sqlite3.connect(self._path)) as db, db:
            SQLitePlannerStore(db).receive_classification(run_id, classification)

    def fail_turn(self, run_id, position, error):
        with closing(sqlite3.connect(self._path)) as db, db:
            SQLitePlannerStore(db).fail_turn(run_id, position, error)

    def receive_turn(self, run_id, position, receipt):
        with closing(sqlite3.connect(self._path)) as db, db:
            SQLitePlannerStore(db).receive_turn(run_id, position, receipt)


def _storage_failure(error, *, committing=False):
    if committing:
        return StorageError('commit_unknown', 'The placement commit could not be confirmed. Read the saved run before retrying.')
    if isinstance(error, sqlite3.IntegrityError):
        return StorageError('conflict', 'Placement storage rejected conflicting records.')
    if isinstance(error, sqlite3.OperationalError) and ('locked' in str(error).lower() or 'busy' in str(error).lower()):
        return StorageError('busy', 'Placement storage is busy. Retry the original command.')
    return StorageError('invalid', 'Placement storage is unavailable or contains invalid records.')


class _SafePlacementUnit(_PlacementCommitUnit):
    @contextmanager
    def tool_attempt(self):
        try:
            with super().tool_attempt():
                yield
        except sqlite3.Error as error:
            raise _storage_failure(error) from None

    def _connection(self, *, write=False):
        if not self._active:
            raise StorageClosed()
        return self._db

    def commit(self):
        try:
            super().commit()
        except sqlite3.Error as error:
            raise _storage_failure(error, committing=True) from None


class SQLitePlacementStorage:
    """A single selected native store for the entire bounded placement journey."""
    def __init__(self, path):
        self._path = path

    @contextmanager
    def _open(self, *, write):
        try:
            with closing(sqlite3.connect(self._path)) as db:
                unit = _scope_unit(_SafePlacementUnit(db))
                try:
                    if not write:
                        db.execute('PRAGMA query_only=ON')
                    db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                    yield unit
                finally:
                    unit._active = False
                    db.rollback()
        except sqlite3.Error as error:
            raise _storage_failure(error) from None

    def write(self):
        return self._open(write=True)

    def read(self):
        return self._open(write=False)


class SafePlannerReceipts:
    def __init__(self, path):
        self._native = SQLitePlannerLifecycleStorage(path)

    def fail_classification(self, run_id):
        try:
            self._native.fail_classification(run_id)
        except sqlite3.Error as error:
            raise _storage_failure(error) from None

    def receive_classification(self, run_id, classification):
        try:
            self._native.receive_classification(run_id, classification)
        except sqlite3.Error as error:
            raise _storage_failure(error) from None

    def fail_turn(self, run_id, position, error):
        try:
            self._native.fail_turn(run_id, position, error)
        except sqlite3.Error as error:
            raise _storage_failure(error) from None

    def receive_turn(self, run_id, position, receipt):
        try:
            self._native.receive_turn(run_id, position, receipt)
        except sqlite3.Error as error:
            raise _storage_failure(error) from None


class _ScopedRecords:
    """Adapter-only lifetime guard exposing a closed set of record operations."""
    def __init__(self, records, unit, methods):
        self._records, self._unit, self._methods = records, unit, frozenset(methods)

    def __getattr__(self, name):
        if name not in self._methods:
            raise AttributeError(name)

        def invoke(*args, **kwargs):
            self._unit._connection()
            try:
                return getattr(self._records, name)(*args, **kwargs)
            except sqlite3.Error as error:
                raise _storage_failure(error) from None
            except TypeError:
                raise StorageError('invalid', 'Placement storage contains invalid records.') from None
        return invoke


def _scope_unit(unit):
    methods = {
        'runs': ('create_run', 'scoped_run_row', 'step_exists_row', 'append_step', 'update_status'),
        'planner': ('default_row', 'create_job', 'upsert_default', 'job_result_row', 'turn_rows', 'turn_row',
                    'request_turn', 'classification_row', 'request_classification', 'job_snapshot_row',
                    'history_rows', 'update_outcome'),
        'drafts': ('owner_row', 'latest_revision_row', 'read_snapshot', 'append_snapshot', 'live_catalog_entry', 'placement_catalog_entry'),
        'catalogs': ('read_snapshot', 'list_catalogs', 'add_catalog', 'add_entry'),
        'conversations': ('session_row', 'message_rows', 'append_message', 'job_context_row', 'latest_message_id',
                          'message_count', 'create_session', 'update_settings', 'list_rows', 'running_runs',
                          'supersede', 'legacy_transcripts'),
        'context': ('approval_row', 'saved_review_row', 'started_test_exists', 'correction_row'),
    }
    for field, allowed in methods.items():
        setattr(unit, field, _ScopedRecords(getattr(unit, field), unit, allowed))
    return unit
