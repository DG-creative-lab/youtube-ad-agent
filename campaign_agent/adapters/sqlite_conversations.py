"""Native conversation records on a caller-owned SQLite connection.

Application commands retain authorization, JSON projection, schema initialization
and transaction ownership. Rows and text pass through unchanged.
"""

import sqlite3


class SQLiteConversationStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def session_row(self, session_id):
        return self.connection.execute(
            'SELECT client_id,brand_id,actor_id,settings,campaign_id FROM planner_sessions WHERE id=?',
            (session_id,),
        ).fetchone()

    def message_rows(self, session_id, limit=-1):
        return self.connection.execute(
            '''SELECT m.id,m.role,m.content,m.run_id,m.revision,m.catalog_id,m.kind,m.created_at,j.outcome
               FROM planner_messages m JOIN planner_jobs j ON j.run_id=m.run_id
               WHERE m.session_id=? ORDER BY m.id DESC LIMIT ?''',
            (session_id, limit),
        ).fetchall()

    def append_message(self, session_id, run_id, role, content, revision, catalog_id, kind):
        self.connection.execute(
            '''INSERT INTO planner_messages(session_id,run_id,role,content,revision,catalog_id,kind)
               VALUES(?,?,?,?,?,?,?) ON CONFLICT(run_id,role) DO NOTHING''',
            (session_id, run_id, role, content, revision, catalog_id, kind),
        )

    def job_context_row(self, run_id):
        return self.connection.execute(
            'SELECT session_id,snapshot FROM planner_jobs WHERE run_id=?', (run_id,),
        ).fetchone()

    def latest_message_id(self, session_id):
        return self.connection.execute(
            'SELECT COALESCE(MAX(id),0) FROM planner_messages WHERE session_id=?', (session_id,),
        ).fetchone()[0]

    def message_count(self, session_id):
        return self.connection.execute(
            'SELECT COUNT(*) FROM planner_messages WHERE session_id=?', (session_id,),
        ).fetchone()[0]

    def create_session(self, session_id, client_id, brand_id, actor_id, settings, campaign_id):
        self.connection.execute(
            '''INSERT INTO planner_sessions(id,client_id,brand_id,actor_id,settings,campaign_id)
               VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING''',
            (session_id, client_id, brand_id, actor_id, settings, campaign_id),
        )

    def update_settings(self, session_id, settings):
        self.connection.execute('UPDATE planner_sessions SET settings=? WHERE id=?', (settings, session_id))

    def list_rows(self, client_id, brand_id, actor_id, campaign_id):
        return self.connection.execute(
            '''SELECT s.id,s.settings,(SELECT content FROM planner_messages WHERE session_id=s.id ORDER BY id LIMIT 1)
               FROM planner_sessions s WHERE client_id=? AND brand_id=? AND actor_id=? AND campaign_id=?
               ORDER BY (SELECT MAX(id) FROM planner_messages WHERE session_id=s.id) DESC''',
            (client_id, brand_id, actor_id, campaign_id),
        ).fetchall()
