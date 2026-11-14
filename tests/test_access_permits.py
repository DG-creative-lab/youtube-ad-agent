"""Command permits retain actual authority lifetime and can only fence native commits."""
from contextlib import closing
from dataclasses import replace
import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from starlette.testclient import TestClient

from campaign_agent.adapters.fixture_access import offline_fixture
from campaign_agent.adapters.gateplane import GateplaneAccess
from campaign_agent.ports.access import AccessRequest,AccessUnavailable


class AccessPermitTests(unittest.TestCase):
    def setUp(self):
        self.path=Path(self.enterContext(TemporaryDirectory()))/'permit.sqlite3'
        self.app=offline_fixture(self.path)
        self.client=self.enterContext(TestClient(self.app.staff,base_url=self.app.staff_origin))
        self.client.post('/fixture',json={'profile':'buyer-a'},headers={'Origin':self.app.staff_origin})
        self.token=self.client.cookies.get(self.app.cookie)
        self.digest=hashlib.sha256(self.token.encode()).hexdigest()
        self.command={'method':'POST','path':'/api/openrouter/connect','body':{'operation_id':'a'*32,'tab_id':'b'*32}}
        self.tick=[10.0]
        self.access=GateplaneAccess(self.path,self.app.sessions,self.token,self.app.client,
            application_id='youtube',command=self.command,monotonic_clock=lambda:self.tick[0])
        self.request=AccessRequest('gp-buyer-a','tenant-a','brand','workspace-a','install-a','youtube:agent.run','campaign-a')

    def permit(self):
        return self.access.permit(self.request,command=self.command,session_digest=self.digest,
                                  expires_at=10**12,path=self.path)

    def validate(self,permit,**changes):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            self.access.validate_permit(db,permit,changes.get('request',self.request),changes.get('command',self.command),changes.get('digest',self.digest))

    def test_commit_validation_has_no_remote_callbacks_and_rejects_changed_command_or_native_snapshot(self):
        permit=self.permit()
        with patch.object(self.app.client,'decide',side_effect=AssertionError('remote decide')),\
             patch.object(self.app.client,'context',side_effect=AssertionError('remote context')),\
             patch.object(self.app.client,'verify_current',side_effect=AssertionError('remote identity')):
            self.validate(permit)
        with self.assertRaises(PermissionError):
            self.validate(permit,command={**self.command,'path':'/api/openrouter/select'})
        with self.assertRaises(PermissionError):
            self.validate(permit,request=replace(self.request,campaign_id='campaign-b'))
        with closing(sqlite3.connect(self.path)) as db,db:
            # Authored native edit after authority preflight, before write admission.
            old=db.execute("SELECT snapshot FROM campaign_revisions WHERE campaign_id='campaign-a' ORDER BY revision DESC LIMIT 1").fetchone()[0]
            import json
            value=json.loads(old);value['revision']=2
            cols=db.execute('PRAGMA table_info(campaign_revisions)').fetchall()
            row=list(db.execute("SELECT * FROM campaign_revisions WHERE campaign_id='campaign-a' ORDER BY revision DESC LIMIT 1").fetchone())
            names=[c[1] for c in cols];row[names.index('revision')]=2;row[names.index('snapshot')]=json.dumps(value)
            db.execute('INSERT INTO campaign_revisions VALUES('+','.join('?' for _ in row)+')',row)
        with self.assertRaises(PermissionError):
            self.validate(permit)

    def test_lifetime_is_measured_from_original_decision_not_permit_return_or_metadata_completion(self):
        decide=self.app.client.decide
        def delayed(wire):
            result=decide(wire);self.tick[0]+=3.0;return result
        with patch.object(self.app.client,'decide',side_effect=delayed):
            permit=self.permit()
        self.assertLessEqual(permit.valid_until,14.0)
        self.tick[0]=permit.valid_until
        with self.assertRaises(AccessUnavailable):
            self.validate(permit)

    def test_logout_rejects_an_otherwise_unexpired_permit_without_upstream_request(self):
        permit=self.permit();self.app.sessions.end(self.token)
        with patch.object(self.app.client,'decide',side_effect=AssertionError('remote')):
            with self.assertRaises(PermissionError):
                self.validate(permit)

    def test_permit_expiring_during_native_verification_is_rejected(self):
        permit=self.permit()
        from campaign_agent import access as native
        original=native.command_hash;calls=[0]
        def slow_hash(value):
            calls[0]+=1
            result=original(value)
            if calls[0]==2:self.tick[0]=permit.valid_until
            return result
        with patch.object(native,'command_hash',side_effect=slow_hash):
            with self.assertRaises(AccessUnavailable):self.validate(permit)

    def test_denied_unavailable_and_wrong_actor_never_produce_a_permit(self):
        self.app.client.permissions['buyer-a'].remove('youtube:agent.run')
        with self.assertRaises(PermissionError):self.permit()
        self.app.client.unavailable=True
        with self.assertRaises(AccessUnavailable):self.permit()
