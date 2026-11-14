"""Foreground connection/catalogue commands; stores verifiers, never provider credentials."""
from contextlib import closing
from dataclasses import dataclass, field
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
from time import time

from .access import WorkspaceContext
from .migrations import migrate_path
from .model_catalogue import CatalogueCache, fingerprint, normalize, select_endpoint, model_id, price
from .ports.access import AccessRequest, AccessUnavailable
from .ports.inference import ForegroundCredential, ProviderError

SHORT_ID=re.compile(r'[0-9a-f]{32}')
LONG_ID=re.compile(r'[0-9a-f]{64}')
FIELDS={
    'connect':({'operation_id','tab_id'},{'resume_connection_id'}),
    'models':({'connection_id','tab_id','search','cursor'},set()),
    'select':({'operation_id','connection_id','tab_id','model_id','catalogue_revision','profile','max_run_cost_usd'},set()),
    'disconnect':({'connection_id','tab_id'},set()),
    'reconcile':({'run_id','inference_position'},set()),
}


@dataclass(frozen=True)
class ProviderContext:
    actor_id: str
    native: WorkspaceContext
    campaign_id: str
    session_digest: str
    expires_at: float
    command: dict
    local_validate: object = field(repr=False,compare=False)


def validate_fields(action, data):
    if action not in FIELDS or not isinstance(data,dict):
        raise ProviderError('invalid_request')
    required,optional=FIELDS[action]
    if not required<=data.keys() or data.keys()-required-optional:
        raise ProviderError('invalid_request')
    for name in ('operation_id','tab_id'):
        if name in data and (not isinstance(data[name],str) or not SHORT_ID.fullmatch(data[name])):
            raise ProviderError('invalid_request')
    if action=='reconcile' and (not isinstance(data['run_id'],str) or not SHORT_ID.fullmatch(data['run_id'])
            or type(data['inference_position']) is not int or not 0<=data['inference_position']<8):
        raise ProviderError('invalid_request')


    for name in ('connection_id','resume_connection_id','catalogue_revision'):
        if name in data and (not isinstance(data[name],str) or not LONG_ID.fullmatch(data[name])):
            raise ProviderError('invalid_request')
    if action=='models' and (not isinstance(data['search'],str) or len(data['search'])>100
            or data['cursor'] is not None and (not isinstance(data['cursor'],str) or not LONG_ID.fullmatch(data['cursor']))):
        raise ProviderError('invalid_request')
    if action=='select':
        model_id(data['model_id'])
        if data['profile'] not in ('planner','structured_review') or data['max_run_cost_usd'] not in ('0','0.25','1.00'):
            raise ProviderError('invalid_request')


def parse_command(raw):
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:
                raise ProviderError('invalid_request')
            result[k]=v
        return result
    try:
        value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value,dict):
            raise ValueError()
        return value
    except (ValueError,TypeError,UnicodeError,RecursionError):
        raise ProviderError('invalid_request') from None


class ProviderSessions:
    def __init__(self,path,*,metadata=None,profiles=(),clock=time):
        self.path=Path(path);self.metadata=metadata;self.profiles=tuple(profiles);self.clock=clock
        self.cache=CatalogueCache()
        migrate_path(self.path)

    def _requests(self, context):
        c=context.native
        return tuple(AccessRequest(context.actor_id,c.scope.client_id,c.scope.brand_id,c.workspace_id,c.installation_id,
                                   capability,context.campaign_id) for capability in ('youtube:campaign.read','youtube:agent.run'))

    def _authorize(self, context, access):
        context.local_validate()
        if context.expires_at<=self.clock() or not hasattr(access,'permit'):
            raise ProviderError('authority_unavailable')
        permits=tuple(access.permit(r,command=context.command,session_digest=context.session_digest,
                      expires_at=context.expires_at,path=self.path) for r in self._requests(context))
        with closing(sqlite3.connect(self.path)) as db:
            self._check(db,context,access,permits)
        return permits

    def _check(self,db,context,access,permits):
        context.local_validate()
        if context.expires_at<=self.clock():
            raise ProviderError('authority_unavailable')
        for request,permit in zip(self._requests(context),permits,strict=True):
            access.validate_permit(db,permit,request,context.command,context.session_digest)
        if any(access.monotonic()>=p.valid_until or access.clock()>=p.wall_expires_at for p in permits):
            raise ProviderError('authority_unavailable')

    def _identity(self, context):
        n=context.native
        return (context.actor_id,context.session_digest,n.scope.client_id,n.scope.brand_id,n.workspace_id,n.installation_id,context.campaign_id)

    def _row(self,db,ident):
        return db.execute('''SELECT id,actor_id,session_digest,client_id,brand_id,workspace_id,installation_id,campaign_id,
            tab_id,operation_id,salt,key_verifier,created_at,expires_at,revoked_at FROM provider_connections WHERE id=?''',(ident,)).fetchone()

    def _owned(self,db,ident,tab,context,credential=None,*,active=True):
        row=self._row(db,ident)
        if row is None or tuple(row[1:8])!=self._identity(context) or row[8]!=tab:
            raise ProviderError('credential_mismatch')
        if credential is not None:
            verifier=hashlib.sha256(bytes.fromhex(row[10])+credential.key.encode()).hexdigest()
            if not hmac.compare_digest(row[11],verifier):
                self.cache.invalidate(ident)
                raise ProviderError('credential_mismatch')
        if active and (row[14] is not None or row[13]<=self.clock()):
            self.cache.invalidate(ident)
            raise ProviderError('connection_expired')
        return row

    def _safe(self,value,credential):
        def contains(v):
            if isinstance(v,str):
                return credential.key in v
            if isinstance(v,dict):
                return any(contains(k) or contains(item) for k,item in v.items())
            if isinstance(v,(list,tuple)):
                return any(contains(item) for item in v)
            return False
        if contains(value):
            raise ProviderError('catalogue_unavailable')
        return value

    def command(self,action,data,key_values,context,access):
        validate_fields(action,data)
        credential=ForegroundCredential.from_values(key_values,required=action!='disconnect')
        if action=='disconnect' and credential is not None:
            raise ProviderError('invalid_request')
        try:
            if action=='disconnect':
                return self.disconnect(data,context)
            permits=self._authorize(context,access)
            if action=='reconcile':
                raise ProviderError('route_unqualified')
            if self.metadata is None:
                raise ProviderError('catalogue_unavailable')
            return getattr(self,action)(data,credential,context,access,permits)
        except AccessUnavailable:
            raise ProviderError('authority_unavailable') from None
        except PermissionError:
            raise ProviderError('access_denied') from None

    def connect(self,data,credential,context,access,permits):
        request_hash=fingerprint(data)
        with closing(sqlite3.connect(self.path)) as db:
            existing=db.execute('SELECT connection_id,request_hash FROM provider_connection_operations WHERE session_digest=? AND operation_id=?',
                                (context.session_digest,data['operation_id'])).fetchone()
            ident=data.get('resume_connection_id')
            if existing:
                if existing[1]!=request_hash:
                    raise ProviderError('operation_conflict')
                ident=existing[0]
            if ident:
                self._owned(db,ident,data['tab_id'],context,credential)
        self.metadata.validate_key(credential)
        permits=self._authorize(context,access)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self._check(db,context,access,permits)
            existing=db.execute('SELECT connection_id,request_hash FROM provider_connection_operations WHERE session_digest=? AND operation_id=?',
                                (context.session_digest,data['operation_id'])).fetchone()
            if existing:
                if existing[1]!=request_hash:
                    raise ProviderError('operation_conflict')
                ident=existing[0]
            if ident:
                row=self._owned(db,ident,data['tab_id'],context,credential)
                if not existing:
                    db.execute('INSERT INTO provider_connection_operations VALUES(?,?,?,?)',
                               (context.session_digest,data['operation_id'],ident,request_hash))
                return {'schema_version':1,'connection_id':row[0],'expires_at':row[13],'state':'connected'}
            now=self.clock();salt=secrets.token_bytes(32);ident=secrets.token_hex(32)
            expiry=min(context.expires_at,now+3600)
            verifier=hashlib.sha256(salt+credential.key.encode()).hexdigest()
            db.execute('INSERT INTO provider_connections VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)',
                       (ident,*self._identity(context),data['tab_id'],data['operation_id'],salt.hex(),verifier,now,expiry))
            db.execute('INSERT INTO provider_connection_operations VALUES(?,?,?,?)',
                       (context.session_digest,data['operation_id'],ident,request_hash))
        return {'schema_version':1,'connection_id':ident,'expires_at':expiry,'state':'connected'}

    def models(self,data,credential,context,access,permits):
        ident=data['connection_id']
        with closing(sqlite3.connect(self.path)) as db:
            row=self._owned(db,ident,data['tab_id'],context,credential)
        entry=self.cache.get(ident,self.clock())
        if entry is None:
            if data['cursor'] is not None:
                raise ProviderError('selection_stale')
            self.cache.begin(ident)
            try:
                self.metadata.validate_key(credential)
                rows=self._safe(normalize(self.metadata.models(credential),self.profiles,now=self.clock()),credential)
                now=self.clock()
                entry={'models':rows,'observed_at':now,'expires_at':min(now+300,row[13]),
                       'catalogue_revision':fingerprint({'connection':ident,'models':rows,'observed_at':now}),'cursors':{}}
                permits=self._authorize(context,access)
                with closing(sqlite3.connect(self.path)) as db:
                    self._check(db,context,access,permits);self._owned(db,ident,data['tab_id'],context,credential)
                self.cache.finish(ident,entry)
            except BaseException:
                self.cache.finish(ident);raise
        # A cache hit still got fresh authority and local ownership/key proof above.
        with closing(sqlite3.connect(self.path)) as db:
            self._check(db,context,access,permits);self._owned(db,ident,data['tab_id'],context,credential)
        rows,cursor=self.cache.page(entry,data['search'],data['cursor'])
        return self._safe({'schema_version':1,'catalogue_revision':entry['catalogue_revision'],
            'observed_at':entry['observed_at'],'expires_at':entry['expires_at'],'models':rows,'next_cursor':cursor},credential)

    def select(self,data,credential,context,access,permits):
        ident=data['connection_id'];request_hash=fingerprint(data)
        with closing(sqlite3.connect(self.path)) as db:
            self._owned(db,ident,data['tab_id'],context,credential)
            existing=db.execute('SELECT request_hash,snapshot FROM provider_selections WHERE connection_id=? AND operation_id=?',
                                (ident,data['operation_id'])).fetchone()
        if existing and existing[0]!=request_hash:
            raise ProviderError('operation_conflict')
        entry=self.cache.get(ident,self.clock())
        if entry is None or entry['catalogue_revision']!=data['catalogue_revision'] or not any(r['id']==data['model_id'] for r in entry['models']):
            raise ProviderError('selection_stale')
        self.metadata.validate_key(credential)
        selected=select_endpoint(data['model_id'],data['profile'],self.metadata.endpoints(credential,data['model_id']),self.profiles,self.clock())
        rates=selected['prices']
        maximum=price(rates['prompt'])*selected['max_input_tokens']+price(rates['completion'])*selected['max_output_tokens']+price(rates.get('request','0'))
        if maximum>price(data['max_run_cost_usd']):
            raise ProviderError('budget_exhausted')
        selected.update(connection_id=ident,max_run_cost_usd=data['max_run_cost_usd'],catalogue_revision=data['catalogue_revision'])
        self._safe(selected,credential)
        if existing:
            old=json.loads(existing[1])
            if {k:v for k,v in old.items() if k!='selection_id'}!=selected:
                raise ProviderError('selection_stale')
        permits=self._authorize(context,access)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self._check(db,context,access,permits)
            self._owned(db,ident,data['tab_id'],context,credential)
            found=db.execute('SELECT request_hash,snapshot FROM provider_selections WHERE connection_id=? AND operation_id=?',
                             (ident,data['operation_id'])).fetchone()
            if entry['expires_at']<=self.clock():
                raise ProviderError('selection_stale')
            if selected['charging_profile_expires_at']<=self.clock():
                raise ProviderError('route_unqualified')
            if found:
                if found[0]!=request_hash:
                    raise ProviderError('operation_conflict')
                saved=json.loads(found[1])
                if {k:v for k,v in saved.items() if k!='selection_id'}!=selected:
                    raise ProviderError('selection_stale')
                return saved
            selected={'selection_id':secrets.token_hex(32),**selected}
            db.execute('INSERT INTO provider_selections VALUES(?,?,?,?,?,?)',
                (selected['selection_id'],ident,data['operation_id'],request_hash,json.dumps(selected,sort_keys=True),self.clock()))
        return selected

    def disconnect(self,data,context):
        # No access/provider client: local session proof can only revoke its original connection.
        context.local_validate()
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            row=self._row(db,data['connection_id'])
            if row is None or row[2]!=context.session_digest or row[8]!=data['tab_id']:
                raise ProviderError('credential_mismatch')
            context.local_validate()
            db.execute('UPDATE provider_connections SET revoked_at=COALESCE(revoked_at,?) WHERE id=?',(self.clock(),row[0]))
        self.cache.invalidate(data['connection_id'])
        return {'disconnected':True}
