import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../src/activity-status.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {activityFailureStatus}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
test('execution labels distinguish saved failure, uncertainty, rate limit, reconnect and a running request',()=>{
  assert.equal(activityFailureStatus(false,'failed'),'Request failed · inspect diagnostics');
  assert.equal(activityFailureStatus(false,'unknown','provider_unavailable'),'Provider outcome unknown · no automatic retry');
  assert.equal(activityFailureStatus(false,undefined,'inference_outcome_unknown'),'Provider outcome unknown · no automatic retry');
  assert.equal(activityFailureStatus(false,'running','waiting_for_credentials'),'Connection required · resume the original request');
  assert.equal(activityFailureStatus(false,'failed','provider_rate_limited'),'Rate limited · inspect diagnostics');
  assert.equal(activityFailureStatus(true,'failed','provider_rate_limited'),null);
  assert.equal(activityFailureStatus(false,'running'),null);
  assert.equal(activityFailureStatus(false,'completed'),null);
});
