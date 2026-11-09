"""A local provider with independently persisted resources for read-back."""
from contextlib import closing
import json
import sqlite3


class SimulatedCampaignSetup:
    name = 'simulated'
    account_id = 'offline-demo'

    def __init__(self, path):
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS simulated_campaigns (
                account_id TEXT NOT NULL, operation_id TEXT NOT NULL, snapshot TEXT NOT NULL,
                PRIMARY KEY (account_id, operation_id)
            )''')

    def validate(self, plan):
        if (plan['provider'] != self.name or plan['account_id'] != self.account_id
                or plan['action'] != 'create_paused' or plan['status'] != 'PAUSED' or plan['budget_micros'] != 0):
            raise ValueError('The simulator accepts paused, zero-budget setups for the offline demo account.')
        if not plan['groups'] or any(not group['placement_ids'] for group in plan['groups']):
            raise ValueError('Each creative group needs a placement list.')

    def create_paused(self, operation_id, plan):
        self.validate(plan)
        campaign_id = 'sim-' + operation_id
        observed = {'operation_id': operation_id, 'campaign_id': campaign_id, 'configuration': plan,
                    'groups': [{'context': group['context'], 'ad_group_id': f'{campaign_id}-group-{index}',
                                'ad_id': f'{campaign_id}-ad-{index}'} for index, group in enumerate(plan['groups'], 1)]}
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO simulated_campaigns VALUES (?, ?, ?) ON CONFLICT DO NOTHING',
                       (self.account_id, operation_id, json.dumps(observed)))
        return {'campaign_id': campaign_id}

    def readback(self, operation_id, account_id):
        if account_id != self.account_id:
            raise ValueError('The simulated account is unavailable.')
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute('SELECT snapshot FROM simulated_campaigns WHERE account_id=? AND operation_id=?',
                             (account_id, operation_id)).fetchone()
        return json.loads(row[0]) if row else None
