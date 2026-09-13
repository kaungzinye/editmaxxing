const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { createRequire } = require('node:module');
const ts = require('typescript');

// Compile only this pure module in memory, leaving Expo's module settings intact.
const filename = resolve(__dirname, '../workflow.ts');
const compiled = ts.transpileModule(readFileSync(filename, 'utf8'), {
  fileName: filename,
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const workflowModule = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputText)(
  createRequire(filename), workflowModule, workflowModule.exports,
);
const { buildVersions, takeFingerprint, demoProgress, EMPTY_PROGRESS } = workflowModule.exports;

const hook = (id, line = id) => ({ id, line, mechanism: '', reason: '', source: '', evidence: '' });
const spoken = (id, line = id) => ({ ...hook(id, line), movement: 'Wave once', movementReason: '' });
const clip = { id: 'take-1', uri: 'blob:recorded-hook', duration: 3, demo: false, name: 'Hook take' };
const takeFor = (verbal, physical = true) => ({
  hookId: verbal.id, fingerprint: takeFingerprint(verbal, physical), clip,
});

test('two verbal and three text hooks produce six unique, stable combinations', () => {
  const verbal = [spoken('v1'), spoken('v2')];
  const text = [hook('t1'), hook('t2'), hook('t3')];
  const versions = buildVersions(verbal, text, true, []);
  assert.equal(versions.length, 6);
  assert.deepEqual(versions.map(({ id }) => id), ['v1--t1', 'v1--t2', 'v1--t3', 'v2--t1', 'v2--t2', 'v2--t3']);
  const reordered = buildVersions([...verbal].reverse(), [...text].reverse(), true, []);
  assert.deepEqual(reordered.map(({ id }) => id).sort(), versions.map(({ id }) => id).sort());
  assert.equal(buildVersions([], text, true, []).length, 0);
  assert.equal(buildVersions(verbal, [], true, []).length, 0);
});

test('physical movement is included only while enabled', () => {
  const verbal = spoken('v1');
  assert.equal(buildVersions([verbal], [hook('t1')], true, [])[0].movement, verbal.movement);
  assert.equal(Object.hasOwn(buildVersions([verbal], [hook('t1')], false, [])[0], 'movement'), false);
});

test('takes must match both hook identity and the current fingerprint', () => {
  const verbal = spoken('v1');
  const stale = { ...takeFor(verbal), fingerprint: 'old', clip: { ...clip, id: 'stale' } };
  const wrongHook = { ...takeFor(verbal), hookId: 'other', clip: { ...clip, id: 'other' } };
  const versions = buildVersions([verbal], [hook('t1'), hook('t2')], true, [stale, wrongHook, takeFor(verbal)]);
  assert.ok(versions.every((version) => version.take === clip));
  assert.equal(buildVersions([verbal], [hook('t1')], true, [stale, wrongHook])[0].take, undefined);
});

test('editing spoken words or enabled movement invalidates a recorded take', () => {
  const verbal = spoken('v1');
  const takes = [takeFor(verbal)];
  for (const edited of [{ ...verbal, line: 'New words' }, { ...verbal, movement: 'Nod once' }]) {
    assert.equal(buildVersions([edited], [hook('t1')], true, takes)[0].take, undefined);
  }
});

test('editing disabled movement keeps the spoken take valid', () => {
  const verbal = spoken('v1');
  const edited = { ...verbal, movement: 'Nod once' };
  assert.equal(buildVersions([edited], [hook('t1')], false, [takeFor(verbal, false)])[0].take, clip);
});

test('editing overlay text preserves the take and combination identity', () => {
  const verbal = spoken('v1');
  const before = buildVersions([verbal], [hook('t1')], true, [takeFor(verbal)])[0];
  const after = buildVersions([verbal], [hook('t1', 'Changed overlay')], true, [takeFor(verbal)])[0];
  assert.equal(after.id, before.id);
  assert.equal(after.take, before.take);
  assert.equal(after.onScreen.line, 'Changed overlay');
});

test('changing physical-hook mode invalidates takes recorded under the other mode', () => {
  const verbal = spoken('v1');
  assert.equal(buildVersions([verbal], [hook('t1')], false, [takeFor(verbal, true)])[0].take, undefined);
  assert.equal(buildVersions([verbal], [hook('t1')], true, [takeFor(verbal, false)])[0].take, undefined);
});

test('demo progress stays bounded, advances monotonically, and completes at 65 seconds', () => {
  assert.equal(EMPTY_PROGRESS.percent, 0);
  assert.equal(EMPTY_PROGRESS.status, 'idle');
  let previous = 0;
  for (const elapsed of [-1000, 0, 649, 650, 10000, 30000, 50000, 64999, 65000, 999999]) {
    const progress = demoProgress(elapsed);
    assert.ok(progress.percent >= 0 && progress.percent <= 100);
    assert.ok(progress.percent >= previous);
    assert.equal(progress.mode, 'demo');
    assert.equal(progress.status, elapsed >= 65000 ? 'complete' : 'running');
    previous = progress.percent;
  }
  assert.equal(demoProgress(64999).percent, 99);
  assert.equal(demoProgress(65000).percent, 100);
  assert.equal(demoProgress(65000).label, 'Body edit complete');
});
