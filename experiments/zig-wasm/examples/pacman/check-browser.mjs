// AI-assisted bounded gameplay check against an already running Chrome and server.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const url = process.argv[2] ?? 'http://127.0.0.1:8765/';
const directory = process.argv[3] ?? '/home/ubuntu/pacman-shots';
const endpoint = process.env.CHROME_CDP ?? 'http://127.0.0.1:29229';
fs.mkdirSync(directory, {recursive: true});
const target = await (await fetch(`${endpoint}/json/new?about:blank`, {method: 'PUT'})).json();
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
let nextId = 0;
const pending = new Map(), exceptions = [], messages = [];
socket.onmessage = event => {
  const message = JSON.parse(event.data);
  if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params);
  if (message.method === 'Runtime.consoleAPICalled')
    messages.push(message.params.args.map(arg => arg.value ?? arg.description).join(' '));
  if (pending.has(message.id)) {
    const {resolve, reject} = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(JSON.stringify(message.error)));
    else resolve(message.result);
  }
};
const call = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++nextId;
  pending.set(id, {resolve, reject});
  socket.send(JSON.stringify({id, method, params}));
});
async function evaluate(expression) {
  const result = await call('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function frames(count) {
  await evaluate(`new Promise((resolve, reject) => {
    const start = Module.jankFrameStats.frames;
    const timeout = setTimeout(() => reject(new Error('Frame loop stalled')), 10000);
    function check() {
      if (Module.jankFrameStats.frames >= start + ${count}) { clearTimeout(timeout); resolve(); }
      else requestAnimationFrame(check);
    }
    check();
  })`);
}
async function snapshot(name) {
  const pixels = await evaluate(`new Promise(resolve => {
    Module.onJankFrame = () => {
      delete Module.onJankFrame;
      const gl = Module.ctx, canvas = Module.canvas;
      const data = new Uint8Array(canvas.width * canvas.height * 4);
      gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, data);
      const seen = new Uint8Array(canvas.width * canvas.height);
      let largest = null;
      const yellow = i => data[i*4] === 255 && data[i*4+1] === 224 && data[i*4+2] === 40;
      for (let y = 70; y < canvas.height - 30; ++y) {
        for (let x = 20; x < canvas.width - 20; ++x) {
          const i = (canvas.height - 1 - y) * canvas.width + x;
          if (seen[i] || !yellow(i)) continue;
          const queue = [i]; seen[i] = 1;
          let minX = x, maxX = x, minY = y, maxY = y;
          for (let q = 0; q < queue.length; ++q) {
            const at = queue[q], xx = at % canvas.width, yy = canvas.height - 1 - Math.floor(at / canvas.width);
            minX = Math.min(minX, xx); maxX = Math.max(maxX, xx);
            minY = Math.min(minY, yy); maxY = Math.max(maxY, yy);
            for (const n of [at-1, at+1, at-canvas.width, at+canvas.width]) {
              if (n >= 0 && n < seen.length && !seen[n] && yellow(n)) { seen[n] = 1; queue.push(n); }
            }
          }
          if (!largest || queue.length > largest.area)
            largest = {area: queue.length, x: (minX+maxX)/2, y: (minY+maxY)/2};
        }
      }
      resolve({pac: largest, glError: gl.getError(), width: canvas.width, height: canvas.height});
    };
  })`);
  assert.equal(pixels.glError, 0, 'WebGL error');
  assert.ok(pixels.pac?.area > 200, `Pac-Man not rendered: ${JSON.stringify(pixels)}`);
  const result = await call('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
  fs.writeFileSync(path.join(directory, `${name}.png`), Buffer.from(result.data, 'base64'));
  return pixels;
}
async function key(code, value) {
  await call('Input.dispatchKeyEvent', {type: 'keyDown', key: code, code,
    windowsVirtualKeyCode: value, nativeVirtualKeyCode: value});
  await frames(3);
  await call('Input.dispatchKeyEvent', {type: 'keyUp', key: code, code,
    windowsVirtualKeyCode: value, nativeVirtualKeyCode: value});
}
try {
  await call('Runtime.enable');
  await call('Page.enable');
  await call('Page.bringToFront');
  await call('Page.navigate', {url});
  await evaluate(`new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Initialization timed out')), 60000);
    function check() {
      if (window.Module?.jankFrameStats?.frames >= 3) { clearTimeout(timeout); resolve(); }
      else setTimeout(check, 20);
    }
    check();
  })`);
  const output = await evaluate('document.getElementById("stdout").textContent');
  assert.ok(output.split('\n').includes('pacman: rules passed'), output);
  assert.ok(output.split('\n').includes('pacman: initialized'), output);
  console.log('MARKERS: pacman: rules passed; pacman: initialized');
  await evaluate('Module.canvas.focus()');
  await key('ArrowRight', 39);
  await frames(12);
  const before = await snapshot('right-before');
  await frames(16);
  const right = await snapshot('right-after');
  assert.ok(right.pac.x > before.pac.x + 10, 'Right arrow did not reverse the initially left-moving Pac-Man');
  await key('ArrowLeft', 37);
  await frames(12);
  const leftBefore = await snapshot('left-before');
  await frames(16);
  const left = await snapshot('left-after');
  assert.ok(left.pac.x < leftBefore.pac.x - 10, 'Left arrow did not reverse Pac-Man');
  await key('ArrowUp', 38);
  await key('ArrowDown', 40);
  await frames(5);
  const final = await snapshot('arrows');
  assert.equal(exceptions.length, 0, JSON.stringify(exceptions));
  assert.notEqual(await evaluate('document.documentElement.dataset.status'), 'fail');
  const errors = messages.filter(line => /GL_INVALID|GL error|WebGL.*error|abort|exception/i.test(line));
  assert.deepEqual(errors, [], 'GL/console errors');
  console.log(`INPUT: PASS right x=${before.pac.x}->${right.pac.x}; left x=${leftBefore.pac.x}->${left.pac.x}; all four arrows sent`);
  console.log(`CANVAS: ${final.width}x${final.height}; GL error=0; browser exceptions=0; GL/console errors=0`);
  for (const warning of messages.filter(line => line.startsWith('GC Warning:')))
    console.log(`STARTUP WARNING: ${warning}`);
  console.log(`SCREENSHOTS: ${directory}/{right-before,right-after,left-before,left-after,arrows}.png`);
  console.log('PACMAN BROWSER: PASS');
} finally {
  fs.writeFileSync(path.join(directory, 'console.log'), messages.join('\n'));
  fs.writeFileSync(path.join(directory, 'exceptions.json'), JSON.stringify(exceptions, null, 2));
  socket.close();
}
