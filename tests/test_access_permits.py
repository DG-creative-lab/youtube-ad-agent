"""Command permits retain actual authority lifetime and can only fence native commits."""
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from starlette.testclient import TestClient

from campaign_agent.adapters.fixture_access import offline_fixture
from campaign_agent.adapters.gateplane import GateplaneAccess
from campaign_agent.adapters.local_access import LocalDemoAccess
from campaign_agent.adapters.sqlite_access import SQLiteCampaignAccessReader, SQLiteCampaignAccessStorage
from campaign_agent.bootstrap.runtime import create_runtime
from campaign_agent.domain.access_binding import LOCAL_CONTEXT, LOCAL_OPERATOR
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
            application_id='youtube',command=self.command,monotonic_clock=lambda:self.tick[0],
            campaign_access=SQLiteCampaignAccessStorage(self.path))
        self.request=AccessRequest('gp-buyer-a','tenant-a','brand','workspace-a','install-a','youtube:agent.run','campaign-a')

    def permit(self):
        return self.access.permit(self.request,command=self.command,session_digest=self.digest,
                                  expires_at=10**12,path=self.path)

    def validate(self,permit,**changes):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            self.access.validate_permit(SQLiteCampaignAccessReader(db),permit,changes.get('request',self.request),changes.get('command',self.command),changes.get('digest',self.digest))

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
            value=json.loads(old);value['revision']=2
            cols=db.execute('PRAGMA table_info(campaign_revisions)').fetchall()
            row=list(db.execute("SELECT * FROM campaign_revisions WHERE campaign_id='campaign-a' ORDER BY revision DESC LIMIT 1").fetchone())
            names=[c[1] for c in cols];row[names.index('revision')]=2;row[names.index('snapshot')]=json.dumps(value)
            db.execute('INSERT INTO campaign_revisions VALUES('+','.join('?' for _ in row)+')',row)
        with self.assertRaises(PermissionError):
            self.validate(permit)

    def test_commit_permit_uses_the_pending_snapshot_on_the_borrowed_transaction(self):
        permit = self.permit()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('BEGIN IMMEDIATE')
            current, = db.execute("SELECT snapshot FROM campaign_revisions WHERE campaign_id='campaign-a' AND revision=1").fetchone()
            changed = {**json.loads(current), 'policy': {'authored_pending_change': True}}
            db.execute("UPDATE campaign_revisions SET snapshot=? WHERE campaign_id='campaign-a' AND revision=1",
                       (json.dumps(changed),))
            with self.assertRaisesRegex(PermissionError, 'native campaign changed'):
                self.access.validate_permit(SQLiteCampaignAccessReader(db), permit, self.request, self.command, self.digest)
            db.rollback()
        self.validate(permit)

    def test_local_permit_requires_the_native_local_owner(self):
        create_runtime(self.path)
        scope = LOCAL_CONTEXT.scope
        request = AccessRequest(LOCAL_OPERATOR.id, scope.client_id, scope.brand_id, LOCAL_CONTEXT.workspace_id,
                                LOCAL_CONTEXT.installation_id, 'youtube:agent.run', 'tts-sample')
        access = LocalDemoAccess(monotonic_clock=lambda: self.tick[0])
        inputs = {'command': self.command, 'session_digest': self.digest, 'expires_at': 10**12, 'path': self.path}
        self.assertEqual(access.permit(request, **inputs).campaign_revision, '1')
        with self.assertRaisesRegex(PermissionError, 'Local command unavailable'):
            access.permit(replace(request, campaign_id='campaign-a'), **inputs)

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
        from campaign_agent.adapters import sqlite_access as native
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
