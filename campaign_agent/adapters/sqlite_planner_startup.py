"""Explicit schema and legacy adoption for the native SQLite runtime.

Each phase preserves the legacy constructor's commit boundary. The caller
provides the authored seed, exact context/examples, and a capability check.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from .sqlite_workspace_admission import LOCAL_CONTEXT, initialize, admit_demo_campaign, verify
from .sqlite_drafts import SQLiteDraftStore
from .sqlite_runs import SQLiteRunStorage
from .sqlite_planner import SQLiteCatalogStorage, SQLitePlannerLifecycleStorage
from .sqlite_conversations import SQLiteConversationStorage


def package_fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def comparison_group(package, creative):
    return next(group for group in package["groups"] if group["creative_version"] == creative)


def comparison_identity(group, *, keep_takes=False):
    excluded = {"preview_sha256"}
    if keep_takes:
        excluded.add("instruction")
    content = {key: value for key, value in group["content"].items() if key not in excluded}
    return package_fingerprint({"comparison_version": group["comparison_version"], "content": content})


def _viewer_connect(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys = ON")
    return db


def _catalog_schema(db):
    columns = {row[1] for row in db.execute("PRAGMA table_info(catalog_entries)")}
    legacy = bool(columns) and "client_id" not in columns
    if legacy:
        db.execute("ALTER TABLE catalog_entries RENAME TO catalog_entries_legacy")
    db.execute('''CREATE TABLE IF NOT EXISTS catalog_entries (
        ref TEXT PRIMARY KEY, video_id TEXT NOT NULL, title TEXT NOT NULL,
        source TEXT NOT NULL, source_reference TEXT NOT NULL,
        client_id TEXT NOT NULL, brand_id TEXT NOT NULL, campaign_id TEXT NOT NULL,
        UNIQUE(client_id,brand_id,campaign_id,video_id,title,source,source_reference))''')
    if legacy:
        db.execute('''INSERT INTO catalog_entries
            SELECT ref,video_id,title,source,source_reference,?,?,'tts-catalog' FROM catalog_entries_legacy''',
                   (LOCAL_CONTEXT.scope.client_id, LOCAL_CONTEXT.scope.brand_id))
        db.execute("DROP TABLE catalog_entries_legacy")


def initialize_drafts(path, *, context=None, campaign_id=None, seed_snapshot=None, authorize=None, live=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        initialize(db)
        if context is not None:
            if context == LOCAL_CONTEXT and campaign_id in {"tts-sample", "tts-catalog"}:
                admit_demo_campaign(db, campaign_id)
            verify(db, context, campaign_id)
        db.execute("""
                CREATE TABLE IF NOT EXISTS campaign_revisions (
                    campaign_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    snapshot TEXT NOT NULL,
                    PRIMARY KEY (campaign_id, revision)
                )
            """)
        if live:
            _catalog_schema(db)
        else:
            db.execute("""
                        CREATE TABLE IF NOT EXISTS comparison_instruction_versions (
                            client_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                            creative_version TEXT NOT NULL, comparison_version TEXT NOT NULL,
                            instruction_id TEXT NOT NULL, instruction TEXT NOT NULL,
                            PRIMARY KEY (client_id, brand_id, creative_version, comparison_version, instruction_id)
                        )
                    """)
            db.execute("""
                        CREATE TABLE IF NOT EXISTS campaign_package_approvals (
                            client_id TEXT NOT NULL,
                            brand_id TEXT NOT NULL,
                            campaign_id TEXT NOT NULL,
                            revision INTEGER NOT NULL,
                            fingerprint TEXT NOT NULL,
                            actor_id TEXT NOT NULL,
                            approved_at TEXT NOT NULL,
                            snapshot TEXT,
                            PRIMARY KEY (client_id, brand_id, campaign_id, revision, fingerprint)
                        )
                    """)
            columns = db.execute("PRAGMA table_info(campaign_package_approvals)").fetchall()
            if "snapshot" not in {column[1] for column in columns}:
                db.execute("ALTER TABLE campaign_package_approvals ADD COLUMN snapshot TEXT")
        db.execute("""CREATE TABLE IF NOT EXISTS placement_catalog_entries (
                ref TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                campaign_id TEXT NOT NULL, video_id TEXT NOT NULL, title TEXT NOT NULL, source TEXT NOT NULL,
                source_reference TEXT)
            """)
        columns = {column[1] for column in db.execute("PRAGMA table_info(placement_catalog_entries)")}
        if "source_reference" not in columns:
            db.execute("ALTER TABLE placement_catalog_entries ADD COLUMN source_reference TEXT")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='placement_catalogs'").fetchone():
                # Recover only from the original immutable scoped catalog, never from a model or title match.
                for client, brand, campaign, snapshot in db.execute(
                        "SELECT client_id,brand_id,campaign_id,snapshot FROM placement_catalogs"):
                    rows = json.loads(snapshot)
                    identity = {"scope": {"client_id": client, "brand_id": brand}, "campaign": campaign, "rows": rows}
                    for row in rows:
                        ref = package_fingerprint({**identity, "video": row["video_id"]})[:32]
                        db.execute("UPDATE placement_catalog_entries SET source_reference=? WHERE ref=? "
                                   "AND client_id=? AND brand_id=? AND campaign_id=? AND video_id=? AND title=? AND source=?",
                                   (row["source_reference"], ref, client, brand, campaign,
                                    row["video_id"], row["description"], row["source"]))
        if context is not None:
            _seed_campaign(db, campaign_id, seed_snapshot, authorize)


def _seed_campaign(db, campaign_id, seed_snapshot, authorize):
    store = SQLiteDraftStore(db)
    if not store.has_revisions(campaign_id):
        authorize("youtube:campaign.draft")
        store.append_snapshot(campaign_id, 1, seed_snapshot)


def bind_campaign(path, *, context, campaign_id, seed_snapshot, authorize):
    """Verify current ownership and seed a provisioned campaign when needed."""
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("BEGIN")
        verify(db, context, campaign_id)
        if SQLiteDraftStore(db).has_revisions(campaign_id):
            return
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        verify(db, context, campaign_id)
        _seed_campaign(db, campaign_id, seed_snapshot, authorize)


def initialize_simulated_setup(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS simulated_campaigns (
                account_id TEXT NOT NULL, operation_id TEXT NOT NULL, snapshot TEXT NOT NULL,
                PRIMARY KEY (account_id, operation_id)
            )""")


def initialize_campaign_setup(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        columns = {row[1] for row in db.execute('PRAGMA table_info(campaign_setups)')}
        legacy = bool(columns) and 'provider' not in columns
        if legacy:
            db.execute('ALTER TABLE campaign_setups RENAME TO campaign_setups_legacy')
        db.execute("""CREATE TABLE IF NOT EXISTS campaign_setups (
                client_id TEXT NOT NULL, brand_id TEXT NOT NULL, campaign_id TEXT NOT NULL,
                revision INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                provider TEXT NOT NULL, account_id TEXT NOT NULL, snapshot TEXT NOT NULL,
                PRIMARY KEY (client_id, brand_id, campaign_id, revision, fingerprint, provider, account_id)
            )""")
        if legacy:
            db.execute("INSERT INTO campaign_setups\n                              SELECT client_id, brand_id, campaign_id, revision, fingerprint,\n                                     json_extract(snapshot, '$.plan.provider'),\n                                     json_extract(snapshot, '$.plan.account_id'), snapshot\n                              FROM campaign_setups_legacy")
            db.execute('DROP TABLE campaign_setups_legacy')


def initialize_viewer(path):
    with closing(_viewer_connect(path)) as db, db:
        db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS viewer_visits (
                    id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                    creative_ref TEXT NOT NULL, content_fingerprint TEXT, ad_link_id TEXT,
                    arrived_ms INTEGER, rehearsal INTEGER
                );
                CREATE TABLE IF NOT EXISTS viewer_events (
                    seq INTEGER PRIMARY KEY, visit_id TEXT NOT NULL REFERENCES viewer_visits(id),
                    event_id TEXT NOT NULL, example_ref TEXT NOT NULL, kind TEXT NOT NULL,
                    take TEXT NOT NULL, UNIQUE (visit_id, event_id)
                );
                CREATE TABLE IF NOT EXISTS viewer_completions (
                    visit_id TEXT NOT NULL REFERENCES viewer_visits(id),
                    example_ref TEXT NOT NULL, first_choice TEXT NOT NULL, completed_ms INTEGER,
                    PRIMARY KEY (visit_id, example_ref)
                );
            """)
        columns = {column[1] for column in db.execute("PRAGMA table_info(viewer_visits)")}
        if "content_fingerprint" not in columns:
            db.execute("ALTER TABLE viewer_visits ADD COLUMN content_fingerprint TEXT")
        if "ad_link_id" not in columns:
            db.execute("ALTER TABLE viewer_visits ADD COLUMN ad_link_id TEXT")
        if "campaign_id" not in columns:
            db.execute("ALTER TABLE viewer_visits ADD COLUMN campaign_id TEXT")
            # Admit the original demo only if no sibling campaign makes that legacy
            # attribution ambiguous. Other unbound history stays quarantined.
            has_owners = db.execute("SELECT 1 FROM sqlite_master WHERE name='campaign_owners' AND type='table'").fetchone()
            ambiguous_demo = has_owners and db.execute(
                "SELECT 1 FROM campaign_owners WHERE client_id=? AND brand_id=? "
                "AND campaign_id NOT IN ('tts-sample','tts-catalog')",
                (LOCAL_CONTEXT.scope.client_id, LOCAL_CONTEXT.scope.brand_id)).fetchone()
            if not ambiguous_demo:
                db.execute("UPDATE viewer_visits SET campaign_id='tts-sample' WHERE client_id=? AND brand_id=?",
                           (LOCAL_CONTEXT.scope.client_id, LOCAL_CONTEXT.scope.brand_id))
        for column in ("arrived_ms", "rehearsal"):
            if column not in columns:
                db.execute(f"ALTER TABLE viewer_visits ADD COLUMN {column} INTEGER")
        if "completed_ms" not in {column[1] for column in db.execute("PRAGMA table_info(viewer_completions)")}:
            db.execute("ALTER TABLE viewer_completions ADD COLUMN completed_ms INTEGER")


def initialize_performance(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""
                CREATE TABLE IF NOT EXISTS campaign_performance_reviews (
                    id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL, last_requested_at TEXT NOT NULL, snapshot TEXT NOT NULL
                )
            """)
        db.execute("""
                CREATE TABLE IF NOT EXISTS campaign_buyer_corrections (
                    sequence INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE,
                    client_id TEXT NOT NULL, brand_id TEXT NOT NULL, campaign_id TEXT NOT NULL,
                    creative_version TEXT NOT NULL, comparison_fingerprint TEXT NOT NULL,
                    review_id TEXT NOT NULL, actor_id TEXT NOT NULL, kind TEXT NOT NULL,
                    note TEXT NOT NULL, created_at TEXT NOT NULL,
                    comparison_identity TEXT, takes_identity TEXT, comparison_version TEXT
                )
            """)
        columns = {column[1] for column in db.execute("PRAGMA table_info(campaign_buyer_corrections)")}
        missing = {"comparison_identity", "takes_identity", "comparison_version"} - columns
        for column in sorted(missing):
            db.execute(f"ALTER TABLE campaign_buyer_corrections ADD COLUMN {column} TEXT")
        _migrate_correction_identities(db)


def _migrate_correction_identities(db):
    rows = db.execute("""
            SELECT c.id, c.creative_version, a.snapshot
            FROM campaign_buyer_corrections c
            JOIN campaign_performance_reviews r ON r.id = c.review_id
                AND r.client_id = c.client_id AND r.brand_id = c.brand_id AND r.campaign_id = c.campaign_id
            JOIN campaign_package_approvals a ON a.client_id = r.client_id AND a.brand_id = r.brand_id
                AND a.campaign_id = r.campaign_id AND a.revision = r.revision AND a.fingerprint = r.fingerprint
            WHERE a.snapshot IS NOT NULL
                AND (c.comparison_identity IS NULL OR c.takes_identity IS NULL OR c.comparison_version IS NULL)
        """).fetchall()
    for correction_id, creative, snapshot in rows:
        group = comparison_group(json.loads(snapshot), creative)
        db.execute(
            "UPDATE campaign_buyer_corrections SET comparison_identity = ?, takes_identity = ?, "
            "comparison_version = ? WHERE id = ?",
            (comparison_identity(group), comparison_identity(group, keep_takes=True),
             group["comparison_version"], correction_id),
        )


def _delivery_schema(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS campaign_delivery_reports (
                id TEXT PRIMARY KEY, setup_id TEXT NOT NULL, snapshot TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS campaign_delivery_recommendations (
                id TEXT PRIMARY KEY, report_id TEXT NOT NULL, snapshot TEXT NOT NULL)""")


def _instruction_test_schema(path):
    with closing(_viewer_connect(path)) as db, db:
        db.executescript("""
                CREATE TABLE IF NOT EXISTS instruction_tests (
                    id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                    started_at TEXT NOT NULL, snapshot TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS instruction_test_assignments (
                    test_id TEXT NOT NULL REFERENCES instruction_tests(id),
                    participant_id TEXT NOT NULL, arm TEXT NOT NULL CHECK (arm IN ('original', 'revised')),
                    visit_id TEXT NOT NULL UNIQUE REFERENCES viewer_visits(id),
                    source TEXT CHECK (source IN ('participant', 'rehearsal', 'fixture')),
                    PRIMARY KEY (test_id, participant_id)
                );
                CREATE TABLE IF NOT EXISTS instruction_test_reviews (
                    id TEXT PRIMARY KEY, test_id TEXT NOT NULL REFERENCES instruction_tests(id),
                    actor_id TEXT NOT NULL, created_at TEXT NOT NULL, snapshot TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS instruction_test_evidence_snapshots (
                    id TEXT PRIMARY KEY, test_id TEXT NOT NULL REFERENCES instruction_tests(id),
                    operation_id TEXT NOT NULL, snapshot TEXT NOT NULL,
                    UNIQUE (test_id, operation_id)
                );
            """)
        db.execute("BEGIN IMMEDIATE")
        columns = {row[1] for row in db.execute("PRAGMA table_info(instruction_test_assignments)")}
        if "source" not in columns:
            db.execute("ALTER TABLE instruction_test_assignments ADD COLUMN source TEXT "
                       "CHECK (source IN ('participant', 'rehearsal', 'fixture'))")


def _instruction_findings_schema(path):
    with closing(_viewer_connect(path)) as db, db:
        db.execute("""
                CREATE TABLE IF NOT EXISTS instruction_findings (
                    id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                    comparison_key TEXT NOT NULL, snapshot TEXT NOT NULL,
                    retired INTEGER NOT NULL DEFAULT 0 CHECK (retired IN (0, 1))
                )
            """)
        db.execute("""
                CREATE INDEX IF NOT EXISTS instruction_findings_scope
                ON instruction_findings(client_id, brand_id, comparison_key)
            """)


def _conversation_adoption(path):
    with SQLiteConversationStorage(path).initialize() as store:
        for run_id, session_id, snapshot, outcome, status in store.legacy_transcripts():
            source = json.loads(snapshot)
            store.append_message(session_id, run_id, 'user', source['request'], source['revision'], source['catalog_id'], 'request')
            if outcome:
                result = json.loads(outcome)
                saved_session, saved_snapshot = store.job_context_row(run_id)
                saved_source = json.loads(saved_snapshot)
                store.append_message(saved_session, run_id, 'assistant', result.get('message') or 'Request completed.',
                                     result.get('revision', saved_source['revision']), saved_source['catalog_id'], status)


def initialize_local_planner(path, *, context, campaign_id, seed_snapshot: str, examples, authorize):
    """Initialize one explicitly selected local planner store and return its campaign ID.

    Authorization is a capability check, never a database-handle callback.
    Each schema phase commits as the corresponding legacy constructor did.
    """
    if campaign_id is None and context != LOCAL_CONTEXT:
        raise ValueError("Choose a provisioned campaign for this workspace.")
    campaign_id = campaign_id or "tts-sample"
    examples = tuple(examples)
    if (not examples or any(example.scope != context.scope for example in examples)
            or len({example.ref for example in examples}) != len(examples)
            or len({example.creative_ref for example in examples}) != len(examples)):
        raise PermissionError("Supply the brand's own comparison catalog.")
    authorize("youtube:campaign.read")
    initialize_drafts(path, context=context, campaign_id=campaign_id,
                      seed_snapshot=seed_snapshot, authorize=authorize)
    initialize_runtime_schema(path)
    return campaign_id


def initialize_runtime_schema(path, *, simulated_setup=True):
    if simulated_setup:
        initialize_simulated_setup(path)
    initialize_campaign_setup(path)
    initialize_viewer(path)
    initialize_performance(path)
    _delivery_schema(path)
    _instruction_test_schema(path)
    _instruction_findings_schema(path)
    SQLiteRunStorage.initialize(path, legacy_client_id=LOCAL_CONTEXT.scope.client_id,
                                legacy_brand_id=LOCAL_CONTEXT.scope.brand_id)
    SQLiteCatalogStorage(path).initialize()
    SQLitePlannerLifecycleStorage.initialize(path)
    _conversation_adoption(path)


class SQLiteLocalPlannerStartup:
    def __init__(self, path):
        self._path = path

    def initialize(self, *, context, campaign_id, seed_snapshot: str, examples, authorize):
        return initialize_local_planner(self._path, context=context, campaign_id=campaign_id,
                                        seed_snapshot=seed_snapshot, examples=examples, authorize=authorize)


def initialize_publications(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('''CREATE TABLE IF NOT EXISTS public_comparisons (
            id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL,
            campaign_id TEXT NOT NULL, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL,
            creative_ref TEXT NOT NULL, snapshot TEXT NOT NULL, expires_at REAL NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(campaign_id,revision,fingerprint,creative_ref))''')


def initialize_staff_sessions(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('''CREATE TABLE IF NOT EXISTS staff_sessions (
            token_hash TEXT PRIMARY KEY, credential_reference TEXT NOT NULL,
            issuer TEXT NOT NULL, subject TEXT NOT NULL, upstream_session TEXT NOT NULL,
            campaign_id TEXT NOT NULL, csrf TEXT NOT NULL, expires_at REAL NOT NULL)''')
