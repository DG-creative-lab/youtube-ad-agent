"""Explicit synthetic issuer/access fixture. Never wired by a hosted default."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
from time import time
from uuid import uuid4

from campaign_agent.access import BrandScope, Operator, WorkspaceContext
from campaign_agent.assets import AssetStore
from campaign_agent.adapters.gateplane import timestamp, validate_record
from campaign_agent.agent.run import AgentRuntime
from campaign_agent.creatives import EXAMPLES
from campaign_agent.handoff import DEMO_MEDIA_DIR
from campaign_agent.hosted import HostedApplication
from campaign_agent.ports.access import AccessUnavailable
from campaign_agent.staff import StaffSessions, VerifiedIdentity, SignInRequired
from campaign_agent.workspaces import provision_workspace
from campaign_agent.ports.inference import ProviderError, ChargingProfile
from campaign_agent.model_catalogue import endpoint_fingerprint

ISSUER = 'https://fixture-issuer.test/realm'
AUDIENCES = frozenset({'youtube-api', 'gateplane-verifier'})
CLIENT_ID = 'youtube-web'


class AuthoredProviderMetadata:
    """Synthetic-only metadata/key responses; no live provider transport is held."""
    synthetic = True
    keys = ('fixture-openrouter-a-key-not-a-real-secret', 'fixture-openrouter-b-key-not-a-real-secret')

    def __init__(self):
        self.requests=[]
        self.rows=[{'id':'fixture/tool-model','name':'Authored tool model','architecture':{'input_modalities':['text'],'output_modalities':['text']},
                    'supported_parameters':['tools','tool_choice'],'pricing':{'prompt':'0','completion':'0','request':'0'}}]
        self.endpoint={'tag':'fixture/qualified','model_id':'fixture/tool-model','context_length':32000,
            'supported_parameters':['tools','tool_choice','parallel_tool_calls','max_completion_tokens','response_format','structured_outputs'],
            'supports_tool_choice':{'required':True},'pricing':{'prompt':'0','completion':'0','request':'0'}}
        self.profiles=(ChargingProfile('fixture/tool-model','fixture/qualified','authored-free-v1',
            endpoint_fingerprint(self.endpoint),time()+3600,evidence='Authored offline fixture; no live qualification'),)

    def validate_key(self, credential):
        self.requests.append('key')
        if credential.key not in self.keys:
            raise ProviderError('credential_mismatch')

    def models(self, credential):
        self.requests.append('models')
        return self.rows

    def endpoints(self, credential, model):
        self.requests.append('endpoints')
        return [self.endpoint] if model=='fixture/tool-model' else []


class FixtureAuthority:
    def __init__(self):
        self.identities, self.permissions, self.campaigns, self.references = {}, {}, {}, {}
        self.unavailable = False
        self.revoked = set()
        self.requests = []
        self.result_filter = lambda result: result
        self.context_filter = lambda result: result
        self.profiles = ['buyer-a', 'reviewer-a', 'admin-a', 'buyer-b']
        for subject in self.profiles:
            token = 'synthetic-subject-token:' + subject
            tenant = 'tenant-b' if subject.endswith('-b') else 'tenant-a'
            self.identities[token] = VerifiedIdentity(ISSUER, subject, AUDIENCES, CLIENT_ID,
                    'upstream-' + subject, int(time()) + 3600, token)
            self.references['credential-' + subject] = token
            self.campaigns[subject] = {'campaign-b'} if tenant == 'tenant-b' else {'campaign-a', 'campaign-a-sibling', 'campaign-a-brand2'}
            allowed = {'youtube:campaign.read'}
            if subject.startswith('buyer'):
                allowed |= {'youtube:campaign.draft', 'youtube:agent.run', 'youtube:catalog.write', 'youtube:review.write'}
            if subject.startswith('reviewer'):
                allowed |= {'youtube:campaign.approve', 'youtube:campaign.export', 'youtube:setup.manage'}
            # Platform admin is a separate role and supplies no product capabilities.
            self.permissions[subject] = allowed

    def profile(self, name):
        if name not in self.profiles:
            raise ValueError('Choose a synthetic fixture person.')
        return 'credential-' + name, 'campaign-b' if name.endswith('-b') else 'campaign-a'

    def verify_current(self, reference):
        if self.unavailable:
            raise AccessUnavailable('Synthetic authority unavailable')
        try:
            identity = self.identities[self.references[reference]]
        except KeyError:
            raise SignInRequired() from None
        return replace(identity, active=identity.active and identity.subject not in self.revoked)

    def context(self, subject_token, context):
        if self.unavailable:
            raise AccessUnavailable()
        identity = self.identities[subject_token]
        tenant = 'tenant-b' if identity.subject.endswith('-b') else 'tenant-a'
        if identity.subject in self.revoked or context.scope.client_id != tenant:
            raise PermissionError('Fixture membership denied')
        result = {'schema_version': 1, 'application_id': 'youtube', 'installation_id': context.installation_id,
            'tenant_id': tenant, 'workspace_id': context.workspace_id,
            'actor': {'kind': 'human', 'principal_id': 'gp-' + identity.subject, 'delegator_id': None, 'grant_id': None},
            'external_identity': {'issuer': identity.issuer, 'subject': identity.subject},
            'session_id': identity.session_id, 'credential_expires_at': timestamp(identity.expires_at)}
        return self.context_filter(result)

    def decide(self, wire):
        validate_record('DecisionRequest', wire)
        if self.unavailable:
            raise AccessUnavailable()
        identity = self.identities[wire['actor_evidence']['subject_token']]
        allowed = (identity.subject not in self.revoked and wire['application_id'] == 'youtube'
                   and wire['target']['id'] in self.campaigns[identity.subject]
                   and wire['capability'].removesuffix('.v1') in self.permissions[identity.subject])
        self.requests.append(wire)
        checked = int(time())
        result = {key: wire[key] for key in ('schema_version', 'application_id', 'installation_id', 'tenant_id',
                  'workspace_id', 'request_id', 'correlation_id', 'target', 'input_hash', 'subject_hash')}
        result.update(decision_id=uuid4().hex, actor={'kind': 'human', 'principal_id': 'gp-' + identity.subject,
                'delegator_id': None, 'grant_id': None}, outcome='allow' if allowed else 'deny',
            reason='allowed' if allowed else 'access_denied', checked_at=timestamp(checked),
            valid_until=timestamp(min(checked + 5, identity.expires_at)), valid_for_ms=4000 if allowed else 0,
            authority_versions={'principal': '1', 'tenant_membership': '1', 'installation': '1',
                'workspace_membership': '1', 'policy': '1', 'configuration': '1', 'grant': None, 'parent_grants': {}},
            obligations=['product.verify_current_resource.v1'])
        return self.result_filter(result)


class _SeedAccess:
    def decide(self, request):
        return 'allow'


def offline_fixture(path, *, staff_origin='http://127.0.0.1:18985', viewer_origin='http://127.0.0.1:18986', asset_root=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables and 'offline_access_fixture' not in tables:
            raise ValueError('Use a fresh database for the offline staff fixture; existing product data is not admitted.')
        db.execute('CREATE TABLE IF NOT EXISTS offline_access_fixture(version INTEGER PRIMARY KEY CHECK(version=1))')
        db.execute('INSERT OR IGNORE INTO offline_access_fixture VALUES(1)')
        db.execute('''CREATE TABLE IF NOT EXISTS offline_fixture_asset_bindings (
            client_id TEXT NOT NULL, brand_id TEXT NOT NULL, catalog_id TEXT NOT NULL,
            PRIMARY KEY(client_id,brand_id))''')
    contexts = {
        'campaign-a': WorkspaceContext(BrandScope('tenant-a', 'brand'), 'workspace-a', 'install-a'),
        'campaign-a-sibling': WorkspaceContext(BrandScope('tenant-a', 'brand'), 'workspace-a', 'install-a'),
        'campaign-a-brand2': WorkspaceContext(BrandScope('tenant-a', 'brand2'), 'workspace-a2', 'install-a'),
        'campaign-b': WorkspaceContext(BrandScope('tenant-b', 'brand'), 'workspace-b', 'install-b'),
    }
    seed = _SeedAccess()
    operator = Operator('fixture-provisioner', frozenset(context.scope for context in contexts.values()))
    store = AssetStore(path, asset_root if asset_root is not None else path.with_suffix('.assets'))
    catalogs = {}
    def assets(client, brand):
        scope = BrandScope(client, brand)
        if scope not in operator.grants:
            raise PermissionError('Unknown fixture assets')
        return store.catalog(scope, catalogs[scope])
    for campaign, context in contexts.items():
        provision_workspace(path, context, campaign, operator=operator, access=seed)
        if context.scope not in catalogs:
            with closing(sqlite3.connect(path)) as db:
                binding = db.execute('SELECT catalog_id FROM offline_fixture_asset_bindings WHERE client_id=? AND brand_id=?',
                                     (context.scope.client_id, context.scope.brand_id)).fetchone()
            if binding:
                catalogs[context.scope] = binding[0]
            else:
                catalog = store.import_catalog(context, campaign, tuple(replace(e, scope=context.scope) for e in EXAMPLES),
                                               DEMO_MEDIA_DIR, operator=operator, access=seed)
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute('INSERT INTO offline_fixture_asset_bindings VALUES(?,?,?)',
                               (context.scope.client_id, context.scope.brand_id, catalog))
                catalogs[context.scope] = catalog
        examples, media_dir = assets(context.scope.client_id, context.scope.brand_id)
        r = AgentRuntime(path, operator, context=context, campaign_id=campaign, access=seed, examples=examples, media_dir=media_dir)
        r.planner.catalogs.register('Authored fixture catalog', [
            {'video_id': 'SAMPLE00001', 'description': 'Video editing tutorial', 'source': 'synthetic'},
            {'video_id': 'SAMPLE00002', 'description': 'Audiobook narration tutorial', 'source': 'synthetic'}])
    authority = FixtureAuthority()
    sessions = StaffSessions(path, authority, issuer=ISSUER, audiences=AUDIENCES, client_id=CLIENT_ID)
    # Fixture authority is in-memory, so a restart requires explicit synthetic sign-in.
    # The fixture-owned database retains campaigns, approvals and viewer evidence.
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('DELETE FROM staff_sessions')
    metadata=AuthoredProviderMetadata()
    return HostedApplication(path, sessions, authority, assets, staff_origin=staff_origin, viewer_origin=viewer_origin,
                             fixture_login=authority,provider_metadata=metadata,provider_profiles=metadata.profiles)
