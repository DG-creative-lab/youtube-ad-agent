"""One atomic foreground call/cost journal. No credentials, clients or network I/O."""
from datetime import datetime, timezone
from decimal import Decimal
import json
from time import time

from .application.catalogue_policy import fingerprint, price, maximum_cost
from .ports.inference import ProviderError

NANOS=1_000_000_000
UNRESOLVED=('reserved','dispatching','unknown','received')


def nanos(value):
    number=price(value)
    sign,digits,exponent=number.as_tuple()
    coefficient=int(''.join(map(str,digits)))
    power=exponent+9
    if power>=0: return coefficient*10**power
    divisor=10**(-power)
    quotient,remainder=divmod(coefficient,divisor)
    return quotient+bool(remainder)


def money(value):
    return format(Decimal(value)/NANOS,'f')


def actual_cost(value):
    """Exact provider decimal, parsed before binary-float conversion."""
    if type(value) is int: value=str(value)
    if isinstance(value,Decimal):
        _,digits,exponent=value.as_tuple()
        if not value.is_finite() or value<0 or len(digits)>30 or exponent < -18 or value.adjusted()>11:
            return None
        value=format(value,'f')
    if not isinstance(value,str): return None
    try:
        return nanos(value),format(price(value),'f')
    except ProviderError:
        return None


class InferenceLedger:
    def __init__(self, *, clock=time):
        self.clock=clock

    def row(self,db,run_id,position):
        cursor=db.execute('SELECT * FROM inference_ledger WHERE run_id=? AND position=?',(run_id,position))
        row=cursor.fetchone()
        if row is None: return None
        result=dict(zip((d[0] for d in cursor.description),row))
        if result['actual_nanos'] is not None: result['actual_nanos']=int(result['actual_nanos'])
        return result

    def reserve(self,db,run_id,position,binding,settings,request_hash):
        """Caller holds BEGIN IMMEDIATE and has checked current authority/native state."""
        if not db.in_transaction: raise ValueError('Admission requires a transaction.')
        if type(position) is not int or not 0<=position<settings['max_calls']:
            raise ProviderError('budget_exhausted')
        old=self.row(db,run_id,position)
        identity={k:binding[k] for k in ('actor_id','client_id','brand_id','workspace_id','installation_id','campaign_id','connection_id','selection_id')}
        settings_hash=fingerprint(settings)
        if old:
            if any(old[k]!=v for k,v in identity.items()) or old['settings_hash']!=settings_hash or old['request_hash']!=request_hash:
                raise ProviderError('operation_conflict')
            if old['state']=='released_unsent':
                db.execute('DELETE FROM inference_ledger WHERE run_id=? AND position=?',(run_id,position))
            elif old['receipt'] is not None:
                return old
            else:
                raise ProviderError('inference_outcome_unknown')
        now=self.clock();day=datetime.fromtimestamp(now,timezone.utc).date().isoformat()
        amount=nanos(format(maximum_cost(settings),'f'))
        installation=identity['installation_id'];actor=identity['actor_id'];tenant=identity['client_id']
        if db.execute('SELECT 1 FROM inference_ledger WHERE installation_id=? AND (actor_id=? OR client_id=?) AND anomaly=1 LIMIT 1',
                      (installation,actor,tenant)).fetchone(): raise ProviderError('budget_exhausted')
        charge="CASE WHEN state='released_unsent' THEN 0 ELSE COALESCE(CAST(actual_nanos AS INTEGER),reserved_nanos) END"
        def total(where,args):
            return db.execute('SELECT COALESCE(SUM('+charge+'),0) FROM inference_ledger WHERE installation_id=? AND '+where,
                              (installation,*args)).fetchone()[0]
        def daily_total(column,identity):
            return (total(column+'=? AND utc_day=?',(identity,day))+
                    total(column+"=? AND utc_day<>? AND actual_nanos IS NULL AND state!='released_unsent'",(identity,day)))
        if (total('run_id=?',(run_id,))+amount>nanos(settings['max_run_cost_usd'])
                or daily_total('actor_id',actor)+amount>NANOS
                or daily_total('client_id',tenant)+amount>5*NANOS):
            raise ProviderError('budget_exhausted')
        def count(where,args):
            return db.execute('SELECT COUNT(*) FROM inference_ledger WHERE installation_id=? AND '+where,
                              (installation,*args)).fetchone()[0]
        if (count('actor_id=? AND in_flight=1',(actor,))>=1
                or count('client_id=? AND in_flight=1',(tenant,))>=2
                or count("actor_id=? AND created_at>? AND state!='released_unsent'",(actor,now-60))>=10):
            raise ProviderError('admission_busy')
        db.execute('''INSERT INTO inference_ledger(run_id,position,actor_id,client_id,brand_id,workspace_id,installation_id,
            campaign_id,connection_id,selection_id,settings_hash,request_hash,reserved_nanos,created_at,updated_at,utc_day,state,in_flight)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'reserved',1)''',
            (run_id,position,*(identity[k] for k in ('actor_id','client_id','brand_id','workspace_id','installation_id','campaign_id','connection_id','selection_id')),
             settings_hash,request_hash,amount,now,now,day))
        return self.row(db,run_id,position)

    def dispatch(self,db,run_id,position):
        cursor=db.execute("UPDATE inference_ledger SET state='dispatching',updated_at=? WHERE run_id=? AND position=? AND state='reserved'",(self.clock(),run_id,position))
        if cursor.rowcount!=1: raise ProviderError('inference_outcome_unknown')

    def release_unsent(self,db,run_id,position):
        db.execute("UPDATE inference_ledger SET state='released_unsent',in_flight=0,updated_at=? WHERE run_id=? AND position=? AND state='reserved'",(self.clock(),run_id,position))

    def unknown(self,db,run_id,position):
        db.execute("UPDATE inference_ledger SET state='unknown',updated_at=? WHERE run_id=? AND position=? AND state='dispatching'",(self.clock(),run_id,position))

    def receive(self,db,run_id,position,receipt):
        row=self.row(db,run_id,position)
        if not row or row['state'] not in ('dispatching','unknown'): raise ProviderError('operation_conflict')
        inference=receipt.get('inference',{})
        cost=actual_cost(inference.get('usage',{}).get('cost_usd'))
        generation=inference.get('request_id')
        db.execute("UPDATE inference_ledger SET receipt=?,generation_id=?,state='received',in_flight=0,updated_at=? WHERE run_id=? AND position=?",
            (json.dumps(receipt,allow_nan=False),generation,self.clock(),run_id,position))
        if cost is not None: self.settle(db,run_id,position,*cost)

    def settle(self,db,run_id,position,amount,text):
        row=self.row(db,run_id,position)
        if not row: raise ProviderError('operation_conflict')
        if row['actual_nanos'] is not None:
            if (row['actual_nanos'],row['actual_cost'])!=(amount,text): raise ProviderError('operation_conflict')
            return
        db.execute("UPDATE inference_ledger SET actual_nanos=?,actual_cost=?,state='settled',anomaly=?,updated_at=? WHERE run_id=? AND position=?",
            (str(amount),text,int(amount>row['reserved_nanos']),self.clock(),run_id,position))

    def projection(self,row):
        return {'state':row['state'],'reserved_cost_usd':money(row['reserved_nanos']), 'actual_cost_usd':row['actual_cost']}
