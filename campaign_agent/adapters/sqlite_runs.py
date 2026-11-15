"""Fixed native run/step records on a caller-owned SQLite connection.

Raw rows and text pass through. Application commands retain authorization,
JSON, schema initialization, policy and the complete transaction lifecycle.
"""

import sqlite3


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
