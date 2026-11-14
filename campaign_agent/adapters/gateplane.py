"""Product mapping for accepted wire v1, with no Gateplane implementation imports.

The client is injected. Offline fixtures implement this boundary; the private SDK
and real upstream verification remain explicit composition dependencies.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from time import monotonic, time
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker
from rfc3986_validator import validate_rfc3986

from campaign_agent.access import BrandScope, CAPABILITIES, WorkspaceContext
from campaign_agent.ports.access import AccessUnavailable, GateplaneClient, CommandPermit
from campaign_agent.access import validate_permit

SCHEMA_PATH = Path(__file__).resolve().parents[1] / 'contracts/gateplane-v1.json'
SCHEMA = json.loads(SCHEMA_PATH.read_text())
FORMATS = FormatChecker()


@FORMATS.checks('uri')
def complete_uri(value):
    return isinstance(value, str) and bool((match := validate_rfc3986(value, rule='URI')) and match.end() == len(value))


def validate_record(name, value):
    Draft202012Validator({**SCHEMA, '$ref': '#/$defs/' + name}, format_checker=FORMATS).validate(value)
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def hash_value(value):
    return 'sha256:' + hashlib.sha256(canonical(value)).hexdigest()


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def seconds(value):
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()


def native_campaign(path, campaign_id):
    with closing(sqlite3.connect(path)) as db:
        row = db.execute('''SELECT b.client_id,b.brand_id,b.workspace_id,b.installation_id,
            r.revision,r.snapshot FROM campaign_owners c JOIN brand_workspaces b
            ON b.client_id=c.client_id AND b.brand_id=c.brand_id
            JOIN campaign_revisions r ON r.campaign_id=c.campaign_id WHERE c.campaign_id=?
            ORDER BY r.revision DESC LIMIT 1''', (campaign_id,)).fetchone()
    if row is None:
        raise PermissionError('Campaign unavailable in this workspace.')
    return WorkspaceContext(BrandScope(*row[:2]), *row[2:4]), str(row[4]), hash_value(json.loads(row[5]))


class GateplaneAccess:
    def __init__(self, path, sessions, session_token, client: GateplaneClient, *, application_id, command,
                 clock=time, monotonic_clock=monotonic):
        self.path, self.sessions, self.session_token, self.client = path, sessions, session_token, client
        self.application_id, self.command = application_id, command
        self.clock, self.monotonic = clock, monotonic_clock

    def principal(self, campaign_id):
        identity, _, _ = self.sessions.current(self.session_token)
        context, _, _ = native_campaign(self.path, campaign_id)
        try:
            result = validate_record('PrincipalContext', self.client.context(identity.subject_token, context))
            actor = result['actor']
            if (result['application_id'] != self.application_id
                    or result['installation_id'] != context.installation_id or result['tenant_id'] != context.scope.client_id
                    or result['workspace_id'] != context.workspace_id or actor['kind'] != 'human'
                    or actor['grant_id'] is not None or actor['delegator_id'] is not None
                    or result['external_identity'] != {'issuer': identity.issuer, 'subject': identity.subject}
                    or result['session_id'] != identity.session_id
                    or not self.clock() < seconds(result['credential_expires_at']) <= identity.expires_at):
                raise ValueError('Unbound principal context')
        except PermissionError:
            raise
        except Exception:
            raise AccessUnavailable('Current staff context is unavailable.') from None
        return identity, context, result

    def decide(self, request):
        return self._decision(request)

    def permit(self, request, *, command, session_digest, expires_at, path):
        if (Path(path) != Path(self.path) or command != self.command or session_digest != hashlib.sha256(self.session_token.encode()).hexdigest()):
            raise PermissionError('The command binding changed.')
        result = self._decision(request, permit=True)
        if result == 'unavailable':
            raise AccessUnavailable('Current access decision unavailable.')
        if result == 'deny':
            raise PermissionError('Current access denied.')
        return result

    def validate_permit(self, db, permit, request, command, session_digest):
        self.sessions.local(self.session_token)
        if command != self.command or session_digest != hashlib.sha256(self.session_token.encode()).hexdigest():
            raise PermissionError('The command binding changed.')
        validate_permit(db,permit,request,command,session_digest,clock=self.clock,monotonic_clock=self.monotonic)

    def _decision(self, request, permit=False):
        identity, context, principal = self.principal(request.campaign_id)
        if (request.capability not in CAPABILITIES or request.actor_id != principal['actor']['principal_id']
                or (request.client_id, request.brand_id, request.workspace_id, request.installation_id) !=
                   (context.scope.client_id, context.scope.brand_id, context.workspace_id, context.installation_id)):
            return 'deny'
        _, revision, snapshot_hash = native_campaign(self.path, request.campaign_id)
        target = {'namespace': 'youtube', 'type': 'campaign', 'id': request.campaign_id}
        effect = 'read' if request.capability == 'youtube:campaign.read' else (
            'external' if request.capability == 'youtube:setup.manage' else 'write')
        input_hash = hash_value({'profile': 'youtube-command-v1', 'command': self.command})
        subject_hash = hash_value({'profile': 'youtube-subject-v1', 'context': vars(context.scope),
            'workspace': context.workspace_id, 'installation': context.installation_id,
            'actor': principal['actor'], 'target': target, 'capability': request.capability,
            'effect': effect, 'input_hash': input_hash, 'revision': revision, 'snapshot_hash': snapshot_hash})
        wire = {'schema_version': 1, 'application_id': self.application_id,
            'installation_id': context.installation_id, 'tenant_id': context.scope.client_id,
            'workspace_id': context.workspace_id, 'request_id': uuid4().hex, 'correlation_id': uuid4().hex,
            'idempotency_key': subject_hash.removeprefix('sha256:'),
            'actor_evidence': {'kind': 'human', 'subject_token': identity.subject_token},
            'capability': request.capability + '.v1', 'target': target,
            'facts': {'attester_id': self.application_id, 'source': 'youtube-sqlite-v1', 'resource_version': revision,
                'observed_at': timestamp(self.clock()), 'owner_tenant_id': context.scope.client_id,
                'workspace_id': context.workspace_id,
                'attributes': {'youtube:brand_id': context.scope.brand_id, 'youtube:snapshot_hash': snapshot_hash}},
            'input_hash': input_hash, 'subject_hash': subject_hash, 'effect': effect, 'run_id': None}
        start = self.monotonic()
        try:
            validate_record('DecisionRequest', wire)
            result = validate_record('DecisionResult', self.client.decide(wire))
            for name in ('application_id', 'installation_id', 'tenant_id', 'workspace_id', 'request_id',
                         'correlation_id', 'target', 'input_hash', 'subject_hash'):
                if result[name] != wire[name]:
                    raise ValueError('Unbound access decision')
            if result['actor'] != principal['actor']:
                raise ValueError('Unbound access actor')
            supported = {'product.verify_current_resource.v1'}
            if request.capability in {'youtube:campaign.export', 'youtube:setup.manage'}:
                supported.add('product.enforce_business_approval.v1')
            checked, expiry, now = seconds(result['checked_at']), seconds(result['valid_until']), self.clock()
            if result['outcome'] == 'unavailable':
                return 'unavailable'
            if result['outcome'] != 'allow':
                return 'deny'
            if set(result['obligations']) - supported:
                raise ValueError('Unsupported access obligations')
            versions = result['authority_versions']
            if (versions['tenant_membership'] is None or versions['workspace_membership'] is None
                    or versions['grant'] is not None or versions['parent_grants']):
                raise ValueError('Incomplete human workspace authority')
            if (abs(now - checked) > 60 or not checked < expiry <= checked + 5
                    or not now < expiry <= identity.expires_at
                    or self.monotonic() - start >= min(5000, result['valid_for_ms']) / 1000):
                raise ValueError('Expired access decision')
            # Local logout/expiry is a separate fence from the upstream credential.
            session = self.sessions.local(self.session_token)
            if native_campaign(self.path, request.campaign_id) != (context, revision, snapshot_hash):
                return 'deny'
            if (self.monotonic() - start >= min(5000, result['valid_for_ms']) / 1000
                    or self.clock() >= min(expiry, identity.expires_at, session[6])):
                raise ValueError('Access expired during native verification')
        except Exception:
            raise AccessUnavailable('Current access decision is unavailable.') from None
        if permit:
            wall_expiry = min(expiry, identity.expires_at, session[6])
            deadline = min(start+min(5000,result['valid_for_ms'])/1000,
                           self.monotonic()+max(0,wall_expiry-self.clock()))
            return CommandPermit(request, hash_value(self.command), hashlib.sha256(self.session_token.encode()).hexdigest(),
                                 revision, snapshot_hash, result['decision_id'], deadline, wall_expiry)
        return 'allow'
