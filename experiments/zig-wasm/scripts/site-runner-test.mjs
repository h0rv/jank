// AI-assisted tests for the live demo runner's input, result and error states.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../site/runner.js', import.meta.url), 'utf8');
function runner({ wasm = true } = {}) {
  const elements = Object.fromEntries(['input', 'result', 'status', 'stats', 'stdout'].map(id =>
    [id, { textContent: '', value: '1 2 3', disabled: true,
      addEventListener(name, callback) { this[`on${name}`] = callback; } }]));
  const listeners = {};
  const scripts = [];
  const document = {
    documentElement: { dataset: { status: 'running' } },
    getElementById: id => elements[id],
    createElement: () => ({}),
    body: { appendChild: script => scripts.push(script) }
  };
  const created = [];
  const context = vm.createContext({ document, performance: { now: () => 0 },
    WebAssembly: wasm ? {} : undefined,
    createLive: options => { const instance = {}; created.push({ options, instance });
      return Promise.resolve(instance); },
    window: { addEventListener: (name, callback) => { listeners[name] = callback; } } });
  vm.runInContext(source, context);
  return { document, elements, listeners, scripts, created };
}

test('starts the module, sends input and shows its result', async () => {
  const page = runner();
  assert.equal(page.scripts[0].src, 'live.js');
  page.scripts[0].onload();
  await new Promise(resolve => setImmediate(resolve));
  const { options, instance } = page.created[0];
  assert.equal(options.arguments[0], 'static-roots');
  assert.equal(page.elements.input.disabled, false);
  assert.equal(instance.liveInput, '1 2 3');
  page.elements.input.value = '4 5';
  page.elements.input.oninput();
  assert.equal(instance.liveInput, '4 5');
  options.onLiveResult('{:count 2}');
  assert.equal(page.elements.result.textContent, '{:count 2}');
  assert.equal(page.document.documentElement.dataset.status, 'pass');
  options.onJankFrame({ frames: 9, collections: 2, used: 1048576, heap: 2097152 });
  assert.match(page.elements.stats.textContent, /frame 9, 2 garbage collections/);
});

test('missing WebAssembly and load errors give visible diagnostics', () => {
  const missing = runner({ wasm: false });
  assert.equal(missing.scripts.length, 0);
  assert.match(missing.elements.stdout.textContent, /WebAssembly is unavailable/);
  assert.equal(missing.document.documentElement.dataset.status, 'fail');
  const page = runner();
  page.scripts[0].onerror();
  assert.match(page.elements.stdout.textContent, /Could not load live.js/);
});

test('abort, runtime errors and rejected promises fail visibly', () => {
  for (const trigger of [page => { page.scripts[0].onload(); page.created[0].options.onAbort('abort'); },
    page => page.listeners.error({ message: 'runtime error' }),
    page => page.listeners.unhandledrejection({ reason: 'rejection' })]) {
    const page = runner();
    trigger(page);
    assert.equal(page.document.documentElement.dataset.status, 'fail');
    assert.notEqual(page.elements.stdout.textContent, '');
  }
});
