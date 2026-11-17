// AI-assisted tests for the static AOT demo's completion and error states.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../site/runner.js', import.meta.url), 'utf8');
const gameSource = readFileSync(new URL('../site/pacman-runner.js', import.meta.url), 'utf8');
function runner({ output = '', wasm = true, game = false } = {}) {
  const elements = Object.fromEntries(['stdout', 'status', 'app', 'canvas', 'game-message'].map(id => [id, { textContent: '' }]));
  const canvasListeners = {};
  elements.canvas.addEventListener = (name, callback) => { canvasListeners[name] = callback; };
  elements.canvas.focus = () => { elements.canvas.focused = true; };
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
  vm.runInContext(game ? gameSource : source, context);
  return { context, document, elements, listeners, scripts, canvasListeners };
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

test('Pac-Man requires both markers and a rendered frame', () => {
  const page = runner({ game: true });
  assert.equal(page.scripts[0].src, 'pacman.js');
  assert.equal(page.context.Module.canvas, page.elements.canvas);
  page.context.Module.print('pacman: rules passed');
  page.context.Module.print('pacman: initialized');
  assert.equal(page.document.documentElement.dataset.status, 'running');
  page.context.Module.onJankFrame({ frames: 1 });
  assert.equal(page.document.documentElement.dataset.status, 'pass');
  assert.equal(page.elements.status.textContent, 'running · wasm64 · frame 1');
  assert.equal(page.elements['game-message'].hidden, true);
  page.context.Module.onJankFrame({ frames: 60 });
  assert.equal(page.elements.status.textContent, 'running · wasm64 · frame 60');
});

test('Pac-Man missing markers, unavailable Wasm and load failures fail visibly', () => {
  for (const lines of [[], ['pacman: initialized']]) {
    const page = runner({ game: true });
    lines.forEach(page.context.Module.print);
    page.context.Module.onJankFrame({ frames: 1 });
    assert.equal(page.document.documentElement.dataset.status, 'fail');
    assert.match(page.elements.stdout.textContent, /Missing game initialization markers/);
  }
  const missing = runner({ game: true, wasm: false });
  assert.equal(missing.scripts.length, 0);
  assert.match(missing.elements.stdout.textContent, /WebAssembly is unavailable/);
  assert.equal(missing.elements['game-message'].hidden, false);
  assert.match(missing.elements['game-message'].textContent, /Could not run the game/);
  const page = runner({ game: true });
  page.scripts[0].onerror();
  assert.match(page.elements.stdout.textContent, /Could not load pacman.js/);
});

test('Pac-Man runtime failures stay failed after subsequent frames', () => {
  for (const trigger of [page => page.context.Module.onAbort('abort'),
    page => page.context.Module.onExit(0),
    page => page.listeners.error({ message: 'runtime error' }),
    page => page.listeners.unhandledrejection({ reason: 'rejection' })]) {
    const page = runner({ game: true });
    trigger(page);
    page.context.Module.print('pacman: rules passed');
    page.context.Module.print('pacman: initialized');
    page.context.Module.onJankFrame({ frames: 60 });
    assert.equal(page.document.documentElement.dataset.status, 'fail');
    assert.notEqual(page.elements.stdout.textContent, '');
  }
});

test('Pac-Man click focuses canvas and only arrow keys prevent page scrolling', () => {
  const page = runner({ game: true });
  page.canvasListeners.click();
  assert.equal(page.elements.canvas.focused, true);
  for (const code of ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Tab']) {
    let prevented = false;
    page.canvasListeners.keydown({ code, preventDefault: () => { prevented = true; } });
    assert.equal(prevented, code !== 'Tab');
  }
});
