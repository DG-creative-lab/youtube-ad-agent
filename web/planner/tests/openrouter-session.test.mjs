import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
class MemoryStorage {
  values = new Map();
  getItem(key) {return this.values.get(key) ?? null;}
  setItem(key,value) {this.values.set(key,String(value));}
  removeItem(key) {this.values.delete(key);}
}
globalThis.sessionStorage = new MemoryStorage();
globalThis.window = new EventTarget();
globalThis.location = {protocol:'http:',hostname:'127.0.0.1'};
const source = await readFile(new URL('../src/openrouter-session.ts',import.meta.url),'utf8');
const output = ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {OpenRouterSession} = await import('data:text/javascript;base64,'+Buffer.from(output).toString('base64'));
const sentinel = 'authored-memory-only-sentinel';
const connection = 'a'.repeat(64), revision='catalogue-current';
const result = (data,csrf) => new Response(JSON.stringify(data),{headers:csrf?{'X-CSRF-Token':csrf}:{}});
const connectResult = () => ({connection_id:connection,expires_at:Date.now()/1000+3600});
const modelRows = () => ({catalogue_revision:revision,observed_at:Date.now()/1000,expires_at:Date.now()/1000+300,models:[{id:'fixture/model',name:'Authored model',input_usd_per_million:'0',output_usd_per_million:'0',state:'eligible',reason_codes:[]}],next_cursor:null});
const selection = (body) => ({selection_id:'b'.repeat(64),connection_id:connection,model:body.model_id,profile:body.profile,max_run_cost_usd:body.max_run_cost_usd,catalogue_revision:body.catalogue_revision});
function rig(handler) {
  const storage = new MemoryStorage(), calls=[];
  const session = new OpenRouterSession(storage,async(path,init)=>{
    calls.push({path,...init});
    if(handler) return handler(path,init);
    const body=init.body&&JSON.parse(init.body);
    return result(path.endsWith('/connect')?connectResult():path.endsWith('/models')?modelRows():path.endsWith('/select')?selection(body):{disconnected:true});
  });
  return {session,storage,calls};
}
const connect = async session => {const input={value:sentinel}; const pending=session.connect(input); assert.equal(input.value,''); await pending;};
test('input immediately clears, metadata only persists, keys only on allowed explicit POSTs',async()=>{
  const {session,storage,calls}=rig(); await connect(session);
  await session.models('fixture');await session.select('fixture/model',revision,'0.25');
  await session.request('/api/campaign');
  await assert.rejects(session.request('/api/campaign',{},true),/not allowed/);
  await assert.rejects(session.request('/api/openrouter/connect',undefined,true),/not allowed/);
  for(const call of calls) {
    assert.equal(call.cache,'no-store');assert.equal(call.credentials,'same-origin');
    assert.equal((call.body??'').includes(sentinel),false);
    if(call.headers['X-OpenRouter-Key']) assert.ok(call.method==='POST'&&['/api/openrouter/connect','/api/openrouter/models','/api/openrouter/select'].includes(call.path));
  }
  assert.deepEqual([...storage.values.keys()].sort(),['campaign-openrouter:connection_id','campaign-openrouter:display_model','campaign-openrouter:tab_id']);
  assert.equal(JSON.stringify([...storage.values]).includes(sentinel),false);
  await session.disconnect();assert.equal(calls.at(-1).headers['X-OpenRouter-Key'],undefined);
  await assert.rejects(session.models(''),/Reconnect/);
});
test('invalid input and connection failures synchronously empty DOM and never echo provider/parser/network errors',async()=>{
  for (const failure of ['invalid','network','json','provider']) {
    const {session,calls}=rig(async()=>{
      if(failure==='network')throw Error(sentinel);
      if(failure==='json')return new Response('{"'+sentinel);
      return new Response(JSON.stringify({code:'unrecognized',error:sentinel}),{status:503});
    });
    const input={value:failure==='invalid'?'bad\nvalue':sentinel};
    const pending=session.connect(input);assert.equal(input.value,'');
    await assert.rejects(pending,error=>!error.message.includes(sentinel));
    assert.equal(session.snapshot().state,'disconnected');
    if(failure==='invalid')assert.equal(calls.length,0);
    await assert.rejects(session.models(''),/Reconnect/);
  }
});
test('late connect cannot restore disconnected, scope-changed or page-hidden credential',async()=>{
  for(const clear of [s=>s.disconnect(),s=>{s.bindScope('old');s.bindScope('new');},s=>s.clear(),s=>s.logout()]) {
    let release;const {session}=rig(()=>new Promise(resolve=>release=resolve));
    const input={value:sentinel};const pending=session.connect(input);assert.equal(input.value,'');
    // Disconnect issues a non-key command only when a connection already exists; pending connect has none.
    await clear(session);release(result(connectResult()));await assert.rejects(pending);
    assert.notEqual(session.snapshot().state,'connected');await assert.rejects(session.models(''),/Reconnect/);
  }
});
test('clear retains a harmless reconnect handle; reloaded service cannot send without original key',async()=>{
  const {session,storage,calls}=rig();await connect(session);session.clear();
  assert.equal(session.snapshot().state,'reconnect');
  const reloaded = new OpenRouterSession(storage,()=>{throw Error('must not dispatch');});
  assert.equal(reloaded.snapshot().state,'reconnect');await assert.rejects(reloaded.models(''),/Reconnect/);
  await connect(session);assert.equal(JSON.parse(calls.filter(x=>x.path.endsWith('/connect')).at(-1).body).resume_connection_id,connection);
  await session.disconnect();
});
test('replacement clears old key even if disconnect fails and never dispatches a replacement connect',async()=>{
  let deny=false;const {session,calls}=rig(async path=>path.endsWith('/disconnect')&&deny?new Response('{}',{status:503}):result(connectResult()));
  await connect(session);deny=true;const input={value:'replacement-sentinel'};const pending=session.connect(input,true);assert.equal(input.value,'');await assert.rejects(pending);
  assert.equal(calls.filter(x=>x.path.endsWith('/connect')).length,1);await assert.rejects(session.models(''),/Reconnect/);
});
test('stale catalogue, selection and expiry cannot overwrite newer settings or regain a key',async()=>{
  let hold=false,release;const {session}=rig(async(path,init)=>{
    if(hold)return new Promise(resolve=>release=resolve);
    return result(path.endsWith('/connect')?connectResult():modelRows());
  });
  await connect(session);hold=true;
  const models=session.models('old');session.clear();release(result(modelRows()));await assert.rejects(models);
  hold=false;await connect(session);hold=true;
  const selected=session.select('fixture/model',revision,'0');session.resetSelection();release(result(selection({model_id:'fixture/model',profile:'planner',max_run_cost_usd:'0',catalogue_revision:revision})));await assert.rejects(selected);
  assert.equal(session.snapshot().selection,null);hold=false;await session.disconnect();
  const expired=rig(()=>result({connection_id:connection,expires_at:Date.now()/1000+.01}));await connect(expired.session);
  await new Promise(resolve=>setTimeout(resolve,30));assert.equal(expired.session.snapshot().state,'expired');await assert.rejects(expired.session.models(''),/Reconnect/);
});
test('structured profile selection uses same original model and budget, with no offline fallback',async()=>{
  const {session,calls}=rig();await connect(session);await session.select('fixture/model',revision,'1.00');
  const original=session.snapshot().selection;
  const structured=await session.structured('fixture/model');assert.equal(structured.profile,'structured_review');assert.equal(structured.max_run_cost_usd,'1.00');
  assert.equal(session.snapshot().selection,original);
  const body=JSON.parse(calls.at(-1).body);assert.equal(body.profile,'structured_review');assert.equal(body.model_id,'fixture/model');
  await assert.rejects(session.structured('other/model'),/Reconnect/);await session.disconnect();
});
test('known current secret cannot enter command bodies, offline requests or safe-data persistence',async()=>{
  const {session,calls}=rig();await connect(session);const before=calls.length;
  for(const data of [sentinel,{request:'prefix '+sentinel}, {[sentinel]:'value'}, {nested:[sentinel]}]) {
    assert.throws(()=>session.assertSafe(data),/account field/);
    await assert.rejects(session.request('/api/agent/placements',{request:data}),/account field/);
  }
  assert.equal(calls.length,before);await session.disconnect();
});

test('embedded JSON Unicode escapes cannot persist a known key; harmless escapes remain usable',async()=>{
  const {session,calls}=rig();await connect(session);const before=calls.length;
  const escaped=[...sentinel].map(c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0')).join('');
  const embedded='{"key":"'+escaped+'"}';
  assert.throws(()=>session.assertSafe({request:embedded}),/account field/);
  await assert.rejects(session.request('/api/agent/placements',{request:embedded}),/account field/);
  assert.equal(calls.length,before);session.assertSafe('{"example":"\\u0041"}');
  let nested=escaped;for(let i=0;i<12;i++)nested=JSON.stringify(nested);
  assert.throws(()=>session.assertSafe(nested),/inspection limit/);
  await session.disconnect();
});

test('provider pending-start storage retains only original operation locator, never selection, budget or command body',async()=>{
  const {session}=rig();await connect(session);
  for(const start of [
    {path:'/api/agent/placements',body:{run_id:'c'.repeat(32),session_id:'d'.repeat(32),request:'Authored request',provider_selection_id:'b'.repeat(64),max_run_cost_usd:'1.00'}},
    {path:'/api/agent/instruction-review',body:{operation_id:'e'.repeat(32),mode:'openrouter',test_id:'f'.repeat(32),provider_selection_id:'b'.repeat(64)}}
  ]){
    const serialized=session.serializeStart(start), marker=JSON.parse(serialized);
    assert.equal(marker.provider,true);assert.equal(marker.path,start.path);assert.equal(marker.operation_id,start.body.operation_id??start.body.run_id);
    for(const value of ['provider_selection_id','max_run_cost_usd','Authored request','test_id','session_id'])assert.equal(serialized.includes(value),false);
  }
  const offline={path:'/api/agent/placements',body:{request:'Authored offline request',model:'simulated'}};
  assert.deepEqual(JSON.parse(session.serializeStart(offline)),offline);
  assert.throws(()=>session.serializeStart({path:'/api/agent/placements',body:{request:sentinel}}),/account field/);
  await session.disconnect();
});

test('default browser transport preserves the native global receiver for workspace bootstrap',async()=>{
  const originalFetch=globalThis.fetch;
  let calls=0;
  try {
    globalThis.fetch=function(){assert.equal(this,globalThis);calls++;return Promise.resolve(result({workspace:'authored'}));};
    const session=new OpenRouterSession(new MemoryStorage());
    assert.deepEqual(await session.request('/api/mode'),{workspace:'authored'});assert.equal(calls,1);
  } finally {globalThis.fetch=originalFetch;}
});

test('native logout clears synchronously before response, denial or network failure; subsequent provider commands send no key',async()=>{
  for(const outcome of ['pending','network','denied']) {
    let release;const {session,calls}=rig(async path=>{
      if(path.endsWith('/connect'))return result(connectResult());
      if(outcome==='pending')return new Promise(resolve=>release=resolve);
      if(outcome==='network')throw Error(sentinel);
      return new Response('{}',{status:503});
    });
    await connect(session);
    const logout=session.request('/api/session/end',{});
    const failure=assert.rejects(logout,error=>!error.message.includes(sentinel));
    assert.equal(session.snapshot().state,'disconnected');
    const before=calls.length;await assert.rejects(session.models(''),/Reconnect/);assert.equal(calls.length,before);
    if(outcome==='pending')release(new Response('{}',{status:503}));
    await failure;
    assert.equal(calls.find(call=>call.path==='/api/session/end').headers['X-OpenRouter-Key'],undefined);
  }
  const {session,calls}=rig();await connect(session);await session.request('/api/session/end',{});
  assert.equal(session.snapshot().state,'disconnected');const before=calls.length;await assert.rejects(session.models(''),/Reconnect/);assert.equal(calls.length,before);
});
test('logout rejects known secret in its body and still clears local memory without dispatch',async()=>{
  const {session,calls}=rig();await connect(session);const before=calls.length;
  await assert.rejects(session.request('/api/session/end',{secret:sentinel}),/account field/);
  assert.equal(session.snapshot().state,'disconnected');assert.equal(calls.length,before);await assert.rejects(session.models(''),/Reconnect/);
});
test('removed or substituted tab/connection metadata clears and refuses credentials before any transport',async()=>{
  for(const field of ['tab_id','connection_id'])for(const change of ['remove','replace']) {
    const {session,storage,calls}=rig();await connect(session);
    if(change==='remove')storage.removeItem('campaign-openrouter:'+field);else storage.setItem('campaign-openrouter:'+field,'c'.repeat(64));
    const before=calls.length;await assert.rejects(session.models(''),/metadata changed or was cleared/);
    assert.equal(session.snapshot().state,'disconnected');assert.equal(calls.length,before);
  }
});
test('storage clearing while connect is pending cannot restore key or connection metadata from the late response',async()=>{
  let release;const {session,storage}=rig(()=>new Promise(resolve=>release=resolve));
  const pending=session.connect({value:sentinel});storage.values.clear();release(result(connectResult()));
  await assert.rejects(pending,/metadata changed or was cleared/);assert.equal(session.snapshot().state,'disconnected');assert.equal(storage.getItem('campaign-openrouter:connection_id'),null);
});
test('offline denied-start recovery drops nonexistent operation while saved/provider/uncertain runs retain original identity',async()=>{
  const {forgetFailedOfflineRun,RequestError}=await import('data:text/javascript;base64,'+Buffer.from(output).toString('base64'));
  for(const status of [400,403,404,409])assert.equal(forgetFailedOfflineRun(new RequestError('denied',status),{kind:'offline',phase:'start',acknowledged:false}),true);
  assert.equal(forgetFailedOfflineRun(new RequestError('missing',404),{kind:'offline',phase:'read',acknowledged:false}),true);
  for(const attempt of [
    {kind:'offline',phase:'read',acknowledged:true},
    {kind:'offline',phase:'advance',acknowledged:true},
    {kind:'provider',phase:'start',acknowledged:false},
    {kind:'provider',phase:'read',acknowledged:false},
    {kind:'unknown',phase:'read',acknowledged:false}
  ])for(const status of [403,404,409])assert.equal(forgetFailedOfflineRun(new RequestError('retained',status),attempt),false);
  for(const code of ['waiting_for_credentials','inference_outcome_unknown','request_outcome_unavailable'])assert.equal(forgetFailedOfflineRun(new RequestError('retained',409,code),{kind:'offline',phase:'start',acknowledged:false}),false);
  assert.equal(forgetFailedOfflineRun(new RequestError('uncertain transport',503),{kind:'offline',phase:'start',acknowledged:false}),false);
});

const nativeBinding={actor_id:'authored-buyer',client_id:'authored-client',brand_id:'authored-brand',workspace_id:'authored-workspace',campaign_id:'authored-campaign'};
async function hostedRig() {
  const state={csrf:'native-session-a',binding:{...nativeBinding},status:200,error:null,hold:null};
  const {session,storage,calls}=rig(async(path,init)=>{
    if(path==='/api/mode')return result({workspace:'authored'},state.csrf);
    if(path==='/api/session') {
      if(state.hold)return state.hold();
      if(state.error==='network')throw Error(sentinel);
      if(state.error==='json')return new Response('{'+sentinel,{headers:{'X-CSRF-Token':state.csrf}});
      return new Response(JSON.stringify(state.binding),{status:state.status,headers:state.csrf?{'X-CSRF-Token':state.csrf}:{}});
    }
    const body=init.body&&JSON.parse(init.body);
    return result(path.endsWith('/connect')?connectResult():path.endsWith('/models')?modelRows():path.endsWith('/select')?selection(body):{ok:true},state.csrf);
  });
  await session.request('/api/mode');session.bindScope('authored-native-workspace',nativeBinding);
  return {session,storage,calls,state};
}
test('hosted credential commands perform exactly one fresh keyless native proof, local commands skip the absent session route',async()=>{
  const {session,calls}=await hostedRig();await connect(session);await session.models('');await session.select('fixture/model',revision,'0.25');
  const commands=calls.filter(call=>call.headers['X-OpenRouter-Key']);assert.equal(commands.length,3);
  const proofs=calls.filter(call=>call.path==='/api/session');assert.equal(proofs.length,3);
  for(const proof of proofs){assert.equal(proof.method,'GET');assert.equal(proof.cache,'no-store');assert.equal(proof.credentials,'same-origin');assert.equal(proof.headers['X-OpenRouter-Key'],undefined);assert.equal(proof.body,undefined);}
  for(const command of commands){const i=calls.indexOf(command);assert.equal(calls[i-1].path,'/api/session');assert.equal(command.headers['X-CSRF-Token'],'native-session-a');}
  await session.disconnect();
  const local=rig();await connect(local.session);await local.session.models('');assert.equal(local.calls.some(call=>call.path==='/api/session'),false);await local.session.disconnect();
});
test('native logout, rotated CSRF, substituted full native tuple and unavailable proof clear the key before any credential POST',async()=>{
  const changes=[s=>s.status=401,s=>s.status=403,s=>s.status=503,s=>s.csrf='',s=>s.csrf='native-session-b',s=>s.error='network',s=>s.error='json',
    ...Object.keys(nativeBinding).map(field=>s=>s.binding={...s.binding,[field]:'substituted'})];
  for(const change of changes){
    const {session,calls,state}=await hostedRig();await connect(session);change(state);const before=calls.length;
    await assert.rejects(session.models(''),error=>!error.message.includes(sentinel)&&/staff session changed or could not be verified/.test(error.message));
    assert.equal(session.snapshot().state,'reconnect');assert.deepEqual(calls.slice(before).map(call=>[call.path,!!call.headers['X-OpenRouter-Key']]),[['/api/session',false]]);
  }
});
test('an intervening rolling-CSRF read cannot bless an old key after same-actor same-scope relogin',async()=>{
  const {session,calls,state}=await hostedRig();await connect(session);state.csrf='native-session-b';
  await session.request('/api/mode'); // Updating the rolling request token must not update the key's immutable original proof.
  const before=calls.length;await assert.rejects(session.models(''),/staff session changed or could not be verified/);
  assert.deepEqual(calls.slice(before).map(call=>[call.path,!!call.headers['X-OpenRouter-Key']]),[['/api/session',false]]);
  // A new explicitly entered key may pin the new session; no old key is reused.
  session.bindScope('authored-native-workspace',nativeBinding);await connect(session);assert.equal(calls.at(-1).headers['X-CSRF-Token'],'native-session-b');await session.disconnect();
});
test('late native proof after clear or storage loss cannot dispatch a credential or resurrect a key',async()=>{
  for(const clear of [(s,storage)=>s.clear(),(s,storage)=>storage.values.clear(),(s,storage)=>storage.setItem('placement-review:operator','another-authored-operator')]){
    const {session,storage,calls,state}=await hostedRig();await connect(session);
    let release;state.hold=()=>new Promise(resolve=>release=resolve);const before=calls.length;
    const pending=session.models('');const rejected=assert.rejects(pending);clear(session,storage);release(result(nativeBinding,'native-session-a'));await rejected;
    assert.equal(calls.slice(before).some(call=>call.headers['X-OpenRouter-Key']),false);assert.notEqual(session.snapshot().state,'connected');
  }
});
test('a stale native proof cannot clear a newer explicitly reconnected key',async()=>{
  const {session,calls,state}=await hostedRig();await connect(session);let release;
  state.hold=()=>new Promise(resolve=>release=resolve);const old=session.models('old');const rejected=assert.rejects(old);
  session.clear();state.hold=null;await connect(session);release(result(nativeBinding,'native-session-a'));await rejected;
  assert.equal(session.snapshot().state,'connected');const before=calls.length;await session.models('current');assert.equal(calls.slice(before).filter(call=>call.headers['X-OpenRouter-Key']).length,1);await session.disconnect();
});

test('temporary native proof outage clears memory while retaining original reconnect locator and binding',async()=>{
  const {session,calls,state}=await hostedRig();await connect(session);state.status=503;
  await assert.rejects(session.models(''),/could not be verified/);state.status=200;
  await connect(session);const command=calls.filter(call=>call.path==='/api/openrouter/connect').at(-1);
  assert.equal(JSON.parse(command.body).resume_connection_id,connection);assert.equal(command.headers['X-CSRF-Token'],'native-session-a');await session.disconnect();
});
