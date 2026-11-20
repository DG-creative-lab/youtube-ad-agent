import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../src/evidence-format.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {probabilityLabel}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
test('posterior tail probabilities never round into a claim of certainty or impossibility',()=>{
  assert.equal(probabilityLabel(.99999999),'>99.9%');
  assert.equal(probabilityLabel(.00000001),'<0.1%');
  assert.equal(probabilityLabel(.5),'50%');
  assert.equal(probabilityLabel(0),'0%');
  assert.equal(probabilityLabel(1),'100%');
});
