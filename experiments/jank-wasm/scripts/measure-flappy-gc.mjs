// AI-assisted Chrome benchmark for the published and returning-frame Flappy Bird builds.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {gzipSync} from 'node:zlib';

const [jsPath] = process.argv.slice(2);
if (!jsPath?.endsWith('.js')) throw new Error('Usage: node scripts/measure-flappy-gc.mjs PATH.js');
const seconds = Number(process.env.PLAY_SECONDS ?? 180);
const collectEvery = Number(process.env.COLLECT_EVERY ?? 30);
const forceEveryFrame = process.env.STRESS === '1';
const startups = Number(process.env.STARTUP_RUNS ?? 5);
const js = await fs.readFile(jsPath);
const wasmPath = jsPath.replace(/\.js$/, '.wasm');
const wasm = await fs.readFile(wasmPath);
const page = `<!doctype html><meta charset="utf-8"><canvas id="game" tabindex="0"></canvas>
<script>
const samples = [], errors = [];
window.addEventListener('error', e => errors.push(String(e.message)));
window.addEventListener('unhandledrejection', e => errors.push(String(e.reason)));
let firstFrame;
let onFrame;
var Module = {
  canvas: document.querySelector('canvas'),
  jankCollectEvery: ${forceEveryFrame ? 1 : collectEvery},
  locateFile: () => '/game.wasm',
  printErr: console.warn,
  onAbort: reason => errors.push(String(reason)),
  onExit: status => errors.push('Unexpected exit: ' + status),
  onJankFrame: stats => {
    firstFrame ??= stats.time;
    samples.push(stats);
    onFrame?.();
  },
};
</script><script src="/game.js"></script>`;
const assets = new Map([
  ['/', ['text/html', page]],
  ['/game.js', ['text/javascript', js]],
  ['/game.wasm', ['application/wasm', wasm]],
]);
const server = http.createServer((request, response) => {
  const asset = assets.get(request.url);
  if (!asset) return response.writeHead(404).end();
  response.writeHead(200, {'Content-Type': asset[0], 'Cache-Control': 'no-store'}).end(asset[1]);
});
server.listen(0, '127.0.0.1');
await once(server, 'listening');
const url = `http://127.0.0.1:${server.address().port}/`;
const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'flappy-gc-chrome-'));
const chrome = spawn(process.env.CHROME ?? 'google-chrome', [
  '--headless', '--no-sandbox', '--no-first-run', '--window-size=1000,700',
  '--disable-dev-shm-usage', '--enable-unsafe-swiftshader', '--use-angle=swiftshader',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
]);
let socket;
const exceptions = [];
try {
  const endpoint = await new Promise((resolve, reject) => {
    let stderr = '';
    chrome.stderr.on('data', chunk => {
      stderr += chunk;
      const match = stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) resolve(new URL(match[1]));
    });
    chrome.once('error', reject);
    chrome.once('exit', code => reject(new Error(`Chrome exited ${code}: ${stderr}`)));
  });
  const [target] = (await (await fetch(`http://${endpoint.host}/json/list`)).json())
    .filter(target => target.type === 'page');
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  const pending = new Map();
  let sequence = 0;
  socket.onmessage = event => {
    const result = JSON.parse(event.data);
    if (result.method === 'Runtime.exceptionThrown') exceptions.push(result.params.exceptionDetails);
    pending.get(result.id)?.(result);
    pending.delete(result.id);
  };
  function call(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++sequence;
      const timeout = setTimeout(() => {
        pending.delete(id);
        reject(new Error(`Timed out: ${method}`));
      }, 35000);
      pending.set(id, ({result, error}) => {
        clearTimeout(timeout);
        if (error) reject(new Error(JSON.stringify(error)));
        else resolve(result);
      });
      socket.send(JSON.stringify({id, method, params}));
    });
  }
  async function evaluate(expression) {
    const result = await call('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
    assert.ok(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
  const key = (type, name, code, n) => call('Input.dispatchKeyEvent', {
    type, key: name, code, windowsVirtualKeyCode: n, nativeVirtualKeyCode: n,
  });
  const space = type => key(type, ' ', 'Space', 32);
  async function waitForFrames(n) {
    await evaluate(`new Promise((resolve, reject) => {
      const target = (Module.jankFrameStats?.frames ?? 0) + ${n};
      (function check() {
        if (errors.length) reject(new Error(errors.join('\\n')));
        else if (Module.jankFrameStats?.frames >= target) resolve();
        else setTimeout(check, 3);
      })();
    })`);
  }
  const frames = () => evaluate('Module.jankFrameStats.frames');
  const click = async () => {
    const rect = await evaluate('Module.canvas.getBoundingClientRect().toJSON()');
    const point = {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
    await call('Input.dispatchMouseEvent', {type: 'mouseMoved', ...point});
    await call('Input.dispatchMouseEvent', {type: 'mousePressed', ...point, button: 'left', clickCount: 1});
    await waitForFrames(2);
    await call('Input.dispatchMouseEvent', {type: 'mouseReleased', ...point, button: 'left', clickCount: 1});
    await waitForFrames(2);
  };
  const birdY = () => evaluate(`new Promise(resolve => {
    onFrame = () => {
      onFrame = undefined;
      const gl = Module.ctx, height = Module.canvas.height, pixels = new Uint8Array(height * 4);
      gl.readPixels(80, 0, 1, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      let sum = 0, count = 0;
      for (let y = 0; y < height; y++) {
        const i = y * 4;
        if (pixels[i] === 0 && pixels[i+1] === 240 && pixels[i+2] === 255) {
          sum += height - 1 - y;
          count++;
        }
      }
      resolve(count ? sum / count : null);
    };
  })`);
  async function checkMotion() {
    const before = await birdY();
    assert.notEqual(before, null, 'New game did not render the bird');
    await space('keyDown');
    await waitForFrames(8);
    const up = await birdY();
    await space('keyUp');
    await waitForFrames(12);
    const down = await birdY();
    assert.ok(up !== null && up < before - 8, `Space did not raise bird: ${before} -> ${up}`);
    assert.ok(down !== null && down > up + 5, `Release did not lower bird: ${up} -> ${down}`);
  }
  await call('Runtime.enable');
  await call('Page.enable');
  await call('Network.enable');
  await call('Network.setCacheDisabled', {cacheDisabled: true});
  const startup = [];
  for (let i = 0; i < startups; i++) {
    await call('Page.navigate', {url});
    await evaluate(`new Promise((resolve, reject) => {
      (function check() {
        if (document.readyState === 'complete' && typeof errors !== 'undefined') {
          if (errors.length) return reject(new Error(errors.join('\\n')));
          if (firstFrame !== undefined) return resolve(firstFrame);
        }
        setTimeout(check, 5);
      })();
    })`).then(value => startup.push(value));
  }
  await evaluate('Module.canvas.focus()');
  await click();
  await checkMotion();
  const start = await frames();
  let lastY, still = 0, restarts = 0;
  const deadline = performance.now() + seconds * 1000;
  while (performance.now() < deadline) {
    let y = await birdY();
    assert.notEqual(y, null, 'Lost sight of the bird during play');
    still = Math.abs(y - lastY) < 0.5 ? still + 1 : 0;
    if (still >= 3) {
      await key('keyDown', 'Enter', 'Enter', 13);
      await waitForFrames(2);
      await key('keyUp', 'Enter', 'Enter', 13);
      if (await birdY() === null) {
        await click();
        await checkMotion();
        restarts++;
        y = await birdY();
        assert.notEqual(y, null, 'Restart did not render the bird');
      }
      still = 0;
    }
    lastY = y;
    // The bird rises 3 px/frame on Space and falls 1 px/frame otherwise.
    const upFrames = Math.max(1, Math.min(20, Math.round((24 + y - 205) / 4)));
    await space('keyDown');
    await waitForFrames(upFrames);
    await space('keyUp');
    await waitForFrames(24 - upFrames);
  }
  const samples = await evaluate(`samples.filter(sample => sample.frames >= ${start})`);
  assert.ok(samples.length > 1, 'Not enough rendered frames');
  const first = samples.at(0), last = samples.at(-1);
  if (forceEveryFrame) {
    assert.equal(last.collections - first.collections, last.frames - first.frames,
      'Stress must collect on every frame');
  }
  assert.deepEqual(await evaluate('errors'), []);
  assert.deepEqual(exceptions, []);
  const delta = samples.slice(1).map((sample, i) => sample.time - samples[i].time).sort((a, b) => a - b);
  const percentile = p => delta[Math.ceil(p * delta.length) - 1];
  const medianStartup = [...startup].sort((a, b) => a - b)[Math.floor(startup.length / 2)];
  console.log(JSON.stringify({
    jsPath, startupMs: startup, medianStartupMs: medianStartup,
    moduleBytes: wasm.length, gzipBytes: gzipSync(wasm, {level: 9}).length,
    frameMs: {p50: percentile(.50), p95: percentile(.95), p99: percentile(.99), max: delta.at(-1)},
    frames: last.frames - first.frames, elapsedMs: last.time - first.time, restarts,
    collections: last.collections - first.collections, first, last,
    peak: Object.fromEntries(['heap', 'used', 'memory'].map(k => [k, Math.max(...samples.map(s => s[k]))])),
    stress: forceEveryFrame,
  }, null, 2));
} finally {
  socket?.close();
  if (chrome.pid && chrome.exitCode === null) {
    chrome.kill();
    await once(chrome, 'exit');
  }
  server.close();
  await delay(100);
  await fs.rm(profile, {recursive: true, force: true});
}
