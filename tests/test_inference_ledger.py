"""Observable cost and duplicate-dispatch invariants against real SQLite transactions."""
from contextlib import closing
from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from campaign_agent.inference_ledger import InferenceLedger,actual_cost
from campaign_agent.migrations import migrate_path
from campaign_agent.ports.inference import ProviderError


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'product.sqlite';migrate_path(self.path)
        self.now=1_790_000_000
        self.ledger=InferenceLedger(clock=lambda:self.now)
        self.binding=dict(actor_id='a',client_id='tenant',brand_id='brand',workspace_id='workspace',installation_id='install',campaign_id='campaign',connection_id='c',selection_id='s')
        self.settings=dict(max_calls=8,max_run_cost_usd='1.00',prices={'prompt':'0','completion':'0','request':'0.25'},max_input_tokens=32000,max_output_tokens=512)

    def reserve(self,run='run',position=0,binding=None,settings=None):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            return self.ledger.reserve(db,run,position,binding or self.binding,settings or self.settings,'request')

    def dispatch(self,run='run',position=0):
        with closing(sqlite3.connect(self.path)) as db,db:
            self.ledger.dispatch(db,run,position)

    def receive(self,cost,run='run',position=0):
        with closing(sqlite3.connect(self.path)) as db,db:
            self.ledger.receive(db,run,position,{'inference':{'request_id':'generation','usage':{'cost_usd':cost}}})

    def test_exact_decimal_reservation_and_actual_round_up(self):
        self.assertEqual(actual_cost(Decimal('0.000000001000000001')),(2,'0.000000001000000001'))
        row=self.reserve();self.assertEqual(row['reserved_nanos'],250_000_000)
        self.dispatch();self.receive('0.000000001000000001')
        with closing(sqlite3.connect(self.path)) as db:
            row=self.ledger.row(db,'run',0)
        self.assertEqual((row['actual_nanos'],row['actual_cost'],row['state']),(2,'0.000000001000000001','settled'))

    def test_unique_concurrent_claim_and_no_uncertain_replay(self):
        barrier=threading.Barrier(2);results=[]
        def claim():
            barrier.wait()
            try: results.append(self.reserve()['state'])
            except ProviderError as e: results.append(e.code)
        threads=[threading.Thread(target=claim) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertCountEqual(results,['reserved','inference_outcome_unknown'])
        self.dispatch()
        with closing(sqlite3.connect(self.path)) as db,db:self.ledger.unknown(db,'run',0)
        self.now+=86400
        with self.assertRaises(ProviderError):self.reserve()
        # Reconnection/new run cannot bypass original lost-call concurrency.
        with self.assertRaises(ProviderError):self.reserve('other',binding={**self.binding,'connection_id':'new'})

    def test_unknown_cost_carries_days_and_actor_budget_across_new_connections(self):
        for index in range(4):
            self.reserve(str(index),binding={**self.binding,'connection_id':str(index)})
            self.ledger=InferenceLedger(clock=lambda:self.now)
            self.dispatch(str(index));self.receive(None,str(index))
        self.now+=86400
        with self.assertRaisesRegex(ProviderError,'budget'):self.reserve('new')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT SUM(reserved_nanos) FROM inference_ledger').fetchone()[0],1_000_000_000)

    def test_unsent_release_and_lost_call_reconcile_do_not_invent_terminal_proof(self):
        self.reserve()
        with closing(sqlite3.connect(self.path)) as db,db:self.ledger.release_unsent(db,'run',0)
        self.reserve();self.dispatch()
        with closing(sqlite3.connect(self.path)) as db,db:
            self.ledger.unknown(db,'run',0)
            self.ledger.settle(db,'run',0,0,'0')
            row=self.ledger.row(db,'run',0)
        self.assertEqual((row['state'],row['in_flight']),('settled',1))
        with self.assertRaises(ProviderError):self.reserve('next')

    def test_anomaly_retains_provider_value_and_freezes_shared_admission(self):
        self.reserve();self.dispatch();self.receive('0.250000001')
        with closing(sqlite3.connect(self.path)) as db:row=self.ledger.row(db,'run',0)
        self.assertEqual((row['actual_cost'],row['anomaly']),('0.250000001',1))
        with self.assertRaises(ProviderError):self.reserve('next',binding={**self.binding,'actor_id':'different'})

    def test_free_calls_still_have_actor_tenant_concurrency_and_rate_limits(self):
        free={**self.settings,'prices':{'prompt':'0','completion':'0'},'max_run_cost_usd':'0'}
        self.reserve('one',settings=free)
        with self.assertRaises(ProviderError):self.reserve('two',settings=free)
        self.reserve('two',binding={**self.binding,'actor_id':'b'},settings=free)
        with self.assertRaises(ProviderError):self.reserve('three',binding={**self.binding,'actor_id':'c'},settings=free)
        for run in ('one','two'):
            self.dispatch(run);self.receive('0',run)
        for index in range(9):
            run='free'+str(index);self.reserve(run,settings=free);self.dispatch(run);self.receive('0',run)
        with self.assertRaises(ProviderError):self.reserve('eleventh',settings=free)
        self.now+=61;self.reserve('after-window',settings=free)

    def test_large_actual_value_survives_sqlite_integer_range_and_freezes(self):
        self.reserve();self.dispatch();self.receive('999999999999.000000001')
        with closing(sqlite3.connect(self.path)) as db:row=self.ledger.row(db,'run',0)
        self.assertEqual(row['actual_cost'],'999999999999.000000001')
        self.assertEqual(row['actual_nanos'],999999999999000000001)
        self.assertEqual(row['anomaly'],1)
        with self.assertRaises(ProviderError):self.reserve('later')

    def test_settled_old_history_is_not_current_daily_budget_or_rate(self):
        self.reserve();self.dispatch();self.receive('0.25')
        self.now+=86400
        with closing(sqlite3.connect(self.path)) as db,db:
            columns=[r[1] for r in db.execute('PRAGMA table_info(inference_ledger)')]
            row=list(db.execute('SELECT * FROM inference_ledger').fetchone())
            for i in range(100):
                clone=list(row);clone[columns.index('run_id')]='historical'+str(i)
                db.execute('INSERT INTO inference_ledger VALUES('+','.join('?' for _ in columns)+')',clone)
        self.reserve('current')

    def test_huge_exponents_remain_unknown_without_fixed_decimal_expansion(self):
        self.assertIsNone(actual_cost(Decimal('1e1000000000')))
        self.assertIsNone(actual_cost(Decimal('1e-1000000000')))
