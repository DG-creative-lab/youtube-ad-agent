"""Request-local connection proof and one shared foreground inference admission path."""
from contextlib import closing, contextmanager
from dataclasses import replace
import hashlib
import json
import re
import sqlite3

from .access import CommandAccess
from .inference_ledger import InferenceLedger, actual_cost
from .application.catalogue_policy import compatible_model, fingerprint, select_endpoint
from .ports.inference import ForegroundCredential, ProviderError

class ForegroundInference:
    def __init__(self,providers,context,access,key_values,*,completion_transport=None):
        self.providers,self.path,self.context,self.access=providers,providers.path,context,access
        self.credential=ForegroundCredential.from_values(key_values,required=False)
        self.policy = CommandAccess(self.path, context, access, read_scope=self._read_access)
        self.ledger=InferenceLedger(clock=providers.clock)
        self.run_id=None;self.runtime=None;self.settings_bound=None
        self.completion_transport=completion_transport
        self.guard_data(context.command.get('body',{}))

    def guard_data(self,value):
        if self.credential is not None:
            try: self.providers._safe(value,self.credential)
            except ProviderError:
                raise ProviderError('invalid_request') from None

    def guard_receipt(self,value):
        if self.credential is not None:
            try: self.providers._safe(value,self.credential)
            except ProviderError:
                raise ProviderError('inference_outcome_unknown') from None

    def qualified_for_dispatch(self,settings):
        # Local-only original deadline fence. Historical receipt recovery does
        # not call this new-effect check and cannot extend the qualification.
        if settings['charging_profile_expires_at']<=self.providers.clock():
            raise ProviderError('route_unqualified')

    def attach(self,runtime):
        if not runtime.planner.foreground_compatible or not runtime.structured_foreground_compatible:
            self.close()
            raise ProviderError('route_unqualified')
        self.runtime=runtime
        runtime.foreground=self
        runtime.drafts.access=self.policy
        for adapter in (runtime.openrouter,runtime.openrouter_drafts,runtime.planner.remote):
            adapter.foreground=self
            if self.completion_transport is not None: adapter.transport=self.completion_transport
        try: self.policy.refresh()
        except BaseException:
            self.close();raise
        return self

    def close(self):
        self.credential=None
        self.settings_bound = None
        if self.runtime is not None:
            self.runtime.drafts.access=self.access
            self.runtime.foreground=None
            for adapter in (self.runtime.openrouter,self.runtime.openrouter_drafts,self.runtime.planner.remote): adapter.foreground=None
            self.runtime=None

    def owned(self,db,selection,*,key=False,active=True,reconcile=False):
        if not isinstance(selection,str) or not re.fullmatch('[0-9a-f]{64}',selection): raise ProviderError('invalid_request')
        row=db.execute('SELECT snapshot FROM provider_selections WHERE id=?',(selection,)).fetchone()
        if row is None: raise ProviderError('credential_mismatch')
        settings=json.loads(row[0]);connection=self.providers._row(db,settings['connection_id'])
        if connection is None: raise ProviderError('credential_mismatch')
        context=self.context
        if reconcile:
            # Accounting-only exception: current actor/native scope, original key,
            # original verifier; old staff session/connection expiry never grants inference.
            if (connection[1],*connection[3:8])!=(context.actor_id,context.native.scope.client_id,context.native.scope.brand_id,
                context.native.workspace_id,context.native.installation_id,context.campaign_id): raise ProviderError('credential_mismatch')
            context=replace(context,session_digest=connection[2])
        if key and self.credential is None: raise ProviderError('waiting_for_credentials')
        self.providers._owned(db,connection[0],connection[8],context,self.credential if key or self.credential else None,active=active)
        return settings

    def settings(self,selection,model,task,prompt_version):
        with closing(sqlite3.connect(self.path)) as db:
            saved=self.owned(db,selection,key=True)
        if saved['profile']!=task or model is not None and model!=saved['model']:
            raise ProviderError('invalid_request')
        settings={**saved,'mode':'openrouter','foreground':True,'prompt_version':prompt_version}
        self.settings_bound=settings
        return settings

    def use_run(self,run_id):
        self.run_id=run_id
        with closing(sqlite3.connect(self.path)) as db:
            runs = self.runtime.borrow_run_unit(db).runs
            self.runtime._owned_run_from(runs, run_id)
            row = db.execute('SELECT snapshot FROM planner_jobs WHERE run_id=?', (run_id,)).fetchone()
            if row:
                settings = json.loads(row[0])['settings']
            else:
                row = runs.structured_settings_row(run_id)
                settings = json.loads(row[0]) if row else {}
            if settings.get('foreground'):
                self.owned(db,settings['selection_id'],active=False)
                self.settings_bound=settings

    def check_connection(self,db,settings,*,active=True,key=False):
        saved=self.owned(db,settings['selection_id'],key=key,active=active)
        expected={k:v for k,v in settings.items() if k not in ('mode','foreground','prompt_version')}
        if saved!=expected: raise ProviderError('selection_stale')

    @contextmanager
    def _read_access(self):
        with closing(sqlite3.connect(self.path)) as db:
            yield self.providers.access_reader(db)
            self.local_commit_guard(db)

    def local_commit_guard(self,db):
        if self.settings_bound:
            self.check_connection(db,self.settings_bound,active=False)
            if self.providers._row(db,self.settings_bound['connection_id'])[14] is not None:
                raise ProviderError('connection_expired')

    def before_commit(self,settings=None):
        self.policy.refresh()
        if settings and settings.get('foreground'):
            with closing(sqlite3.connect(self.path)) as db:
                self.check_connection(db,settings,active=False)
                connection=self.providers._row(db,settings['connection_id'])
                if connection[14] is not None: raise ProviderError('connection_expired')

    def preflight(self,settings):
        with closing(sqlite3.connect(self.path)) as db:
            self.check_connection(db,settings,key=True)
        if self.providers.metadata is None: raise ProviderError('catalogue_unavailable')
        credential=self.credential
        self.providers.cache.begin(settings['connection_id'])
        try:
            self.providers.metadata.validate_key(credential)
            rows=self.providers.metadata.models(credential)
        finally: self.providers.cache.finish(settings['connection_id'])
        raw=next((r for r in rows if isinstance(r,dict) and r.get('id')==settings['model']),None)
        if raw is None or not compatible_model(raw,settings['profile']):
            self.providers.cache.invalidate(settings['connection_id']);raise ProviderError('route_unqualified')
        selected=select_endpoint(settings['model'],settings['profile'],
            self.providers.metadata.endpoints(credential,settings['model']),self.providers.profiles,self.providers.clock())
        if any(settings.get(k)!=v for k,v in selected.items()):
            self.providers.cache.invalidate(settings['connection_id']);raise ProviderError('selection_stale')
        self.before_commit(settings)

    def chat(self,adapter,context,settings,body):
        if self.run_id is None: raise ProviderError('invalid_request')
        # Preparation and exact full-wire bounds happen before any reservation.
        encoded=adapter.encode_request(settings,body)
        if len(encoded)>settings['max_input_tokens']:
            raise ProviderError('route_unqualified')
        request_hash=hashlib.sha256(encoded).hexdigest()
        with closing(sqlite3.connect(self.path)) as db:
            if self.runtime.planner.owns(self.run_id):
                position = self.runtime.borrow_run_unit(db).runs.step_count(self.run_id)
            else: position=0
            row=self.ledger.row(db,self.run_id,position)
            if row and row['state']!='released_unsent':
                if row['selection_id']!=settings['selection_id'] or row['settings_hash']!=fingerprint(settings) or row['request_hash']!=request_hash:
                    raise ProviderError('operation_conflict')
                self.check_connection(db,settings,active=False)
                if row['anomaly']: raise ProviderError('budget_exhausted')
                if row['receipt'] is not None: return json.loads(row['receipt'])
                raise ProviderError('inference_outcome_unknown')
        if self.completion_transport is None: raise ProviderError('route_unqualified')
        self.preflight(settings)
        self.providers._safe(json.loads(encoded),self.credential)
        n=self.context.native
        binding={'actor_id':self.context.actor_id,'client_id':n.scope.client_id,'brand_id':n.scope.brand_id,
                 'workspace_id':n.workspace_id,'installation_id':n.installation_id,'campaign_id':self.context.campaign_id,
                 'connection_id':settings['connection_id'],'selection_id':settings['selection_id']}
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            self.policy.check(self.providers.access_reader(db))
            self.check_connection(db, settings, key=True)
            self.current_run(db);self.qualified_for_dispatch(settings)
            self.ledger.reserve(db,self.run_id,position,binding,settings,request_hash)
            self.qualified_for_dispatch(settings)
        # Separate committed marker; any crash after this point is possibly sent.
        try:
            with closing(sqlite3.connect(self.path)) as db,db:
                db.execute('BEGIN IMMEDIATE')
                self.policy.check(self.providers.access_reader(db))
                self.check_connection(db, settings, key=True)
                self.current_run(db);self.qualified_for_dispatch(settings)
                self.ledger.dispatch(db,self.run_id,position)
                self.qualified_for_dispatch(settings)
        except BaseException:
            with closing(sqlite3.connect(self.path)) as db,db: self.ledger.release_unsent(db,self.run_id,position)
            raise
        try:
            receipt=adapter._chat_wire(context,settings,encoded,self.credential)
            echoed=False
            try: self.providers._safe(receipt,self.credential)
            except ProviderError:
                safe={'message':None,'finish_reason':None,'inference':receipt.get('inference',{})}
                self.providers._safe(safe,self.credential)
                receipt=safe;echoed=True
        except BaseException as error:
            with closing(sqlite3.connect(self.path)) as db,db: self.ledger.unknown(db,self.run_id,position)
            if isinstance(error,Exception): raise ProviderError('inference_outcome_unknown') from None
            raise
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self.ledger.receive(db,self.run_id,position,receipt)
            usage=receipt.get('inference',{}).get('usage',{})
            if any(type(usage.get(field)) is int and usage[field]>settings[limit]
                   for field,limit in (('input_tokens','max_input_tokens'),('output_tokens','max_output_tokens'))):
                db.execute('UPDATE inference_ledger SET anomaly=1 WHERE run_id=? AND position=?',(self.run_id,position))
            anomaly=self.ledger.row(db,self.run_id,position)['anomaly']
        # Accounting precedes semantic validation. The runtime refreshes the
        # permit set before any domain/tool commit, including receipt recovery.
        if anomaly: raise ProviderError('budget_exhausted')
        if echoed: raise ProviderError('inference_outcome_unknown')
        return receipt

    def current_run(self, db):
        unit = self.runtime.borrow_run_unit(db)
        request, status = self.runtime._owned_run_from(unit.runs, self.run_id)
        if status != 'running':
            raise ProviderError('operation_conflict')
        if self.runtime.planner.owns(self.run_id):
            self.runtime.planner._context(db, self.run_id)
        else:
            source = self.runtime._structured_source(unit.runs, self.run_id)
            self.runtime._inference_context_from(unit.evidence, request, source)

    def reconcile(self,data):
        if self.credential is None: raise ProviderError('waiting_for_credentials')
        self.policy.refresh()
        with closing(sqlite3.connect(self.path)) as db:
            row=self.ledger.row(db,data['run_id'],data['inference_position'])
            if not row: raise ProviderError('credential_mismatch')
            self.owned(db,row['selection_id'],key=True,active=False,reconcile=True)
            if row['actual_nanos'] is not None: return self.ledger.projection(row)
            if not row['generation_id']: raise ProviderError('inference_outcome_unknown')
        metadata=self.providers.metadata
        if metadata is None or not hasattr(metadata,'generation'): raise ProviderError('catalogue_unavailable')
        metadata.validate_key(self.credential)
        result=metadata.generation(self.credential,row['generation_id'])
        if not isinstance(result,dict) or result.get('id')!=row['generation_id']: raise ProviderError('catalogue_unavailable')
        cost=actual_cost(result.get('total_cost'))
        if cost is None: raise ProviderError('inference_outcome_unknown')
        self.policy.refresh()
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            self.policy.check(self.providers.access_reader(db))
            self.owned(db,row['selection_id'],key=True,active=False,reconcile=True)
            self.ledger.settle(db,row['run_id'],row['position'],*cost)
            return self.ledger.projection(self.ledger.row(db,row['run_id'],row['position']))


def dispatch_agent(runtime,path,data):
    """Both HTTP surfaces use the same strict additive foreground field contract."""
    if not isinstance(data,dict): raise ProviderError('invalid_request')
    foreground=runtime.foreground
    if foreground is not None:
        foreground.guard_data(data)
    if path=='/api/agent/run':
        if set(data)!={'run_id'} or not isinstance(data['run_id'],str) or not re.fullmatch('[0-9a-f]{32}',data['run_id']): raise ProviderError('invalid_request')
        return runtime.resume(data['run_id'],max_steps=1)
    if path=='/api/agent/placements':
        required={'request','model','session_id','run_id','catalog_id'}
        if not required<=data.keys() or data.keys()-required-{'after_message','draft_permission','provider_selection_id'}:
            raise ProviderError('invalid_request')
        remote=data['model'] not in ('simulated','simulated-inspect')
        if remote!=(data.get('provider_selection_id') is not None) or not remote and foreground is not None and foreground.credential:
            raise ProviderError('invalid_request')
        return runtime.read(runtime.planner.start(**data))
    commands={
        '/api/agent/next-test':(runtime.start_next_test,{'campaign_id','revision','fingerprint','review_id'}),
        '/api/agent/instruction-review':(runtime.start_instruction_review,{'test_id'}),
        '/api/agent/experiment-next-test':(runtime.start_experiment_next_test,{'test_id','review_id'})}
    if path not in commands: raise ProviderError('invalid_request')
    command,required=commands[path]
    if not required<=data.keys() or data.keys()-required-{'mode','operation_id','model','provider_selection_id'}:
        raise ProviderError('invalid_request')
    mode=data.get('mode','offline')
    if mode not in ('offline','openrouter'): raise ProviderError('invalid_request')
    if mode=='offline':
        if data.keys()&{'model','provider_selection_id'} or foreground is not None and foreground.credential: raise ProviderError('invalid_request')
    elif not {'operation_id','provider_selection_id'}<=data.keys(): raise ProviderError('invalid_request')
    return runtime.read(command(**data))
