// AI-assisted tests for the live demo and Flappy Bird runners' output and error states.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../site/runner.js', import.meta.url), 'utf8');
const gameSource = readFileSync(new URL('../site/flappy-bird-runner.js', import.meta.url), 'utf8');
function runner({ wasm = true, currentScript, deferred = false } = {}) {
  const elements = Object.fromEntries(['run-form', 'input', 'run', 'result', 'status', 'stats', 'stdout'].map(id =>
    [id, { textContent: '', value: ' 100 ', disabled: true, scrollTop: 0, scrollHeight: 0,
      addEventListener(name, callback) { this[`on${name}`] = callback; } }]));
  const listeners = {};
  const scripts = [];
  const document = {
    currentScript,
    documentElement: { dataset: { status: 'running' } },
    getElementById: id => elements[id],
    createElement: () => ({}),
    body: { appendChild: script => scripts.push(script) }
  };
  const created = [];
  const observers = [];
  const context = vm.createContext({ document, URL, performance: { now: () => 0 },
    IntersectionObserver: deferred ? class {
      constructor(callback, options) { this.callback = callback; this.options = options; observers.push(this); }
      observe(element) { this.element = element; }
      disconnect() { this.disconnected = true; }
    } : undefined,
    WebAssembly: wasm ? {} : undefined,
    createLive: options => { const instance = {}; created.push({ options, instance });
      return Promise.resolve(instance); },
    window: { addEventListener: (name, callback) => { listeners[name] = callback; } } });
  vm.runInContext(source, context);
  return { document, elements, listeners, scripts, created, observers };
}

test('offscreen prime module waits for visibility, then loads only once', async () => {
  const page = runner({ deferred: true, currentScript: { src: 'https://example.test/runner.js?v=abc123' } });
  const observer = page.observers[0];
  assert.equal(observer.element, page.elements['run-form']);
  assert.equal(observer.options.rootMargin, '200px');
  assert.equal(page.scripts.length, 0);
  assert.equal(page.elements.status.textContent, 'waiting until visible');
  observer.callback([]);
  observer.callback([{ isIntersecting: false }]);
  assert.equal(page.scripts.length, 0);
  observer.callback([{ isIntersecting: true }]);
  observer.callback([{ isIntersecting: true }]);
  assert.equal(page.scripts.length, 1);
  assert.equal(page.scripts[0].src, 'live.js?v=abc123');
  assert.equal(observer.disconnected, true);
  page.scripts[0].onload();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(page.created[0].instance.liveInput, '100');
});

test('submit can load an offscreen module and deferred load errors stay visible', () => {
  const page = runner({ deferred: true });
  let prevented = false;
  page.elements['run-form'].onsubmit({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(page.scripts.length, 1);
  assert.equal(page.observers[0].disconnected, true);
  page.scripts[0].onerror();
  assert.equal(page.document.documentElement.dataset.status, 'fail');
  assert.match(page.elements.stdout.textContent, /Could not load live.js/);
});

test('starts a run on load, streams lines and reruns on submit', async () => {
  const page = runner();
  assert.equal(page.scripts[0].src, 'live.js');
  page.scripts[0].onload();
  await new Promise(resolve => setImmediate(resolve));
  const { options, instance } = page.created[0];
  assert.equal(options.arguments[0], 'static-roots');
  assert.equal(page.elements.run.disabled, false);
  assert.equal(instance.liveInput, '100');
  assert.equal(page.document.documentElement.dataset.status, 'running');
  options.onLiveLine('checked 100 of 200, 25 primes so far');
  options.onLiveFinish('46 primes below 200');
  assert.equal(page.elements.result.textContent,
    'checked 100 of 200, 25 primes so far\n46 primes below 200\n');
  assert.equal(page.document.documentElement.dataset.status, 'pass');
  instance.liveInput = null;
  page.elements.input.value = '50';
  let prevented = false;
  page.elements['run-form'].onsubmit({ preventDefault: () => { prevented = true; } });
  assert.ok(prevented);
  assert.equal(instance.liveInput, '50');
  assert.equal(page.elements.result.textContent, '');
  assert.equal(page.elements.run.textContent, 'Run again');
  options.onJankFrame({ frames: 9, collections: 2, used: 1048576, heap: 2097152 });
  assert.match(page.elements.stats.textContent, /frame 9, 2 garbage collections/);
});

test('the page version stamp reaches live.js and live.wasm', async () => {
  const page = runner({ currentScript: { src: 'https://example.test/jank-wasm/runner.js?v=abc123' } });
  assert.equal(page.scripts[0].src, 'live.js?v=abc123');
  page.scripts[0].onload();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(page.created[0].options.locateFile('live.wasm', 'https://example.test/jank-wasm/'),
    'https://example.test/jank-wasm/live.wasm?v=abc123');
});

test('missing WebAssembly and load errors give visible diagnostics', () => {
  const missing = runner({ wasm: false });
  assert.equal(missing.scripts.length, 0);
  assert.match(missing.elements.stdout.textContent, /WebAssembly is unavailable/);
  assert.equal(missing.document.documentElement.dataset.status, 'fail');
  assert.match(missing.elements.status.textContent, /requires memory64 and Wasm exceptions/);
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
    assert.match(page.elements.status.textContent, /requires memory64 and Wasm exceptions/);
    assert.notEqual(page.elements.stdout.textContent, '');
  }
});

function gameRunner({ output = '', wasm = true, jspi = true, webgl2 = true, contextError = false, currentScript } = {}) {
  const elements = Object.fromEntries(['stdout', 'status', 'app', 'canvas', 'game-message'].map(id => [id, { textContent: '' }]));
  const canvasListeners = {};
  elements.canvas.addEventListener = (name, callback) => { canvasListeners[name] = callback; };
  elements.canvas.focus = () => { elements.canvas.focused = true; };
  elements.app.textContent = output;
  const listeners = {};
  const scripts = [];
  const contextRequests = [];
  const document = {
    currentScript,
    documentElement: { dataset: { status: 'running' } },
    getElementById: id => elements[id],
    createElement: tag => tag === 'canvas' ? {
      getContext(type) {
        contextRequests.push(type);
        if (contextError) throw new Error('Context unavailable');
        return webgl2 ? {} : null;
      }
    } : {},
    body: { appendChild: script => scripts.push(script) }
  };
  const context = vm.createContext({ document, URL,
    WebAssembly: wasm ? (jspi ? { promising() {}, Suspending() {} } : {}) : undefined,
    window: { addEventListener: (name, callback) => { listeners[name] = callback; } } });
  vm.runInContext(gameSource, context);
  return { context, document, elements, listeners, scripts, canvasListeners, contextRequests };
}

test('Flappy Bird checks WebGL2 on a separate canvas before loading the game', () => {
  const page = gameRunner();
  assert.deepEqual(page.contextRequests, ['webgl2']);
  assert.equal(page.scripts.length, 1);
  assert.equal(page.context.Module.canvas, page.elements.canvas);
});

test('Flappy Bird missing or throwing WebGL2 context blocks module loading with requirements', () => {
  for (const options of [{ webgl2: false }, { contextError: true }]) {
    const page = gameRunner(options);
    assert.deepEqual(page.contextRequests, ['webgl2']);
    assert.equal(page.scripts.length, 0);
    assert.equal(page.document.documentElement.dataset.status, 'fail');
    assert.equal(page.elements['game-message'].hidden, false);
    assert.match(page.elements['game-message'].textContent, /Needs memory64, Wasm exceptions, JSPI and WebGL2/);
    assert.match(page.elements['game-message'].textContent, /WebGL2 is unavailable/);
    assert.match(page.elements.stdout.textContent, /WebGL2 is unavailable/);
  }
});


test('the page version stamp reaches flappy-bird.js and flappy-bird.wasm', () => {
  const page = gameRunner({ currentScript: { src: 'https://example.test/flappy-bird-runner.js?v=abc123' } });
  assert.equal(page.scripts[0].src, 'flappy-bird.js?v=abc123');
  assert.equal(page.context.Module.locateFile('flappy-bird.wasm', 'https://example.test/'),
    'https://example.test/flappy-bird.wasm?v=abc123');
});

test('Flappy Bird waits for a rendered frame without changing upstream stdout', () => {
  const page = gameRunner();
  assert.equal(page.scripts[0].src, 'flappy-bird.js');
  assert.equal(page.context.Module.canvas, page.elements.canvas);
  assert.equal(page.document.documentElement.dataset.status, 'running');
  page.context.Module.onJankFrame({ frames: 1 });
  assert.equal(page.document.documentElement.dataset.status, 'pass');
  assert.equal(page.elements.status.textContent, 'running · wasm64 · frame 1');
  assert.equal(page.elements['game-message'].hidden, true);
  page.context.Module.onJankFrame({ frames: 60 });
  assert.equal(page.elements.status.textContent, 'running · wasm64 · frame 60');
});

test('Flappy Bird unavailable Wasm or JSPI and load failures fail visibly', () => {
  const unsupported = gameRunner({ jspi: false });
  assert.equal(unsupported.scripts.length, 0);
  assert.match(unsupported.elements['game-message'].textContent, /JSPI is unavailable/);
  const missing = gameRunner({ wasm: false });
  assert.equal(missing.scripts.length, 0);
  assert.match(missing.elements.stdout.textContent, /WebAssembly is unavailable/);
  assert.equal(missing.elements['game-message'].hidden, false);
  assert.match(missing.elements['game-message'].textContent, /Could not run the game/);
  const page = gameRunner();
  page.scripts[0].onerror();
  assert.match(page.elements.stdout.textContent, /Could not load flappy-bird.js/);
});

test('Flappy Bird runtime failures stay failed after subsequent frames', () => {
  for (const trigger of [page => page.context.Module.onAbort('abort'),
    page => page.context.Module.onExit(0),
    page => page.listeners.error({ message: 'runtime error' }),
    page => page.listeners.unhandledrejection({ reason: 'rejection' })]) {
    const page = gameRunner();
    trigger(page);
    page.context.Module.onJankFrame({ frames: 60 });
    assert.equal(page.document.documentElement.dataset.status, 'fail');
    assert.notEqual(page.elements.stdout.textContent, '');
  }
});

test('Flappy Bird click focuses canvas and only Space prevents page scrolling', () => {
  const page = gameRunner();
  page.canvasListeners.click();
  assert.equal(page.elements.canvas.focused, true);
  for (const code of ['Space', 'Enter', 'KeyP', 'Tab']) {
    let prevented = false;
    page.canvasListeners.keydown({ code, preventDefault: () => { prevented = true; } });
    assert.equal(prevented, code === 'Space');
  }
});
