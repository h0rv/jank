// AI-assisted tests for the static AOT demo's completion and error states.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../site/runner.js', import.meta.url), 'utf8');
function runner({ output = '', wasm = true } = {}) {
  const elements = Object.fromEntries(['stdout', 'status', 'app'].map(id => [id, { textContent: '' }]));
  elements.app.textContent = output;
  const listeners = {};
  const scripts = [];
  const document = {
    documentElement: { dataset: { status: 'running' } },
    getElementById: id => elements[id],
    createElement: () => ({}),
    body: { appendChild: script => scripts.push(script) }
  };
  const context = vm.createContext({ document, WebAssembly: wasm ? {} : undefined,
    window: { addEventListener: (name, callback) => { listeners[name] = callback; } } });
  vm.runInContext(source, context);
  return { context, document, elements, listeners, scripts };
}

test('requires successful exit and all live example output', () => {
  const page = runner({ output: 'platform: browser\nweighted buffer: 30\nhello: checks passed\n' });
  assert.equal(page.scripts[0].src, 'hello.js');
  assert.equal(page.context.Module.arguments[0], 'static-roots');
  page.context.Module.onExit(0);
  assert.equal(page.document.documentElement.dataset.status, 'pass');
});

test('empty or incomplete output and nonzero exit fail', () => {
  for (const [output, exit] of [['', 0], ['hello: checks passed', 0],
    ['platform: browser\nweighted buffer: 30\nhello: checks passed', 1]]) {
    const page = runner({ output });
    page.context.Module.onExit(exit);
    assert.equal(page.document.documentElement.dataset.status, 'fail');
  }
});

test('missing WebAssembly and load errors give visible diagnostics', () => {
  const missing = runner({ wasm: false });
  assert.equal(missing.scripts.length, 0);
  assert.match(missing.elements.stdout.textContent, /WebAssembly is unavailable/);
  assert.equal(missing.document.documentElement.dataset.status, 'fail');
  const page = runner();
  page.scripts[0].onerror();
  assert.match(page.elements.stdout.textContent, /Could not load hello.js/);
});

test('abort, runtime errors and rejected promises fail visibly', () => {
  for (const trigger of [page => page.context.Module.onAbort('abort'),
    page => page.listeners.error({ message: 'runtime error' }),
    page => page.listeners.unhandledrejection({ reason: 'rejection' })]) {
    const page = runner();
    trigger(page);
    assert.equal(page.document.documentElement.dataset.status, 'fail');
    assert.notEqual(page.elements.stdout.textContent, '');
  }
});
