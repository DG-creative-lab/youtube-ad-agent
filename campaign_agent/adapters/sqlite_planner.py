"""Native planner records on a caller-owned SQLite connection.

Application commands retain JSON, authorization, inference/recovery decisions,
schema initialization and transaction ownership. Rows and text pass through.
"""

import sqlite3


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
