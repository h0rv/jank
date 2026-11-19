// AI-assisted Chrome check of the JSPI suspend guard in raylib-loop-driver.cpp.
// Browser callbacks only reach Wasm while main is suspended in emscripten_sleep,
// so input floods exercise re-entry; the controls write into linear memory
// during a suspension, once above and once below the suspended stack pointer.
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const name = process.argv[2] ?? 'flappy-bird';
const directory = path.join(root, 'artifacts/app', name, 'wasm');
const seconds = Number(process.env.JSPI_STRESS_SECONDS ?? 20);
const logs = path.join(root, 'artifacts/logs/jspi-suspend', name);
fs.mkdirSync(logs, {recursive: true});
const server = http.createServer((req, res) => {
  const file = req.url === '/' ? 'index.html' : req.url.slice(1);
  if (!['index.html', `${name}.js`, `${name}.wasm`].includes(file)) {
    res.writeHead(404).end();
    return;
  }
  res.setHeader('Content-Type', file.endsWith('.wasm') ? 'application/wasm' :
    file.endsWith('.js') ? 'text/javascript' : 'text/html');
  fs.createReadStream(path.join(directory, file)).pipe(res);
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const chrome = spawn('google-chrome', ['--headless', '--no-sandbox', '--no-first-run',
  '--window-size=1400,1100', '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
  '--disable-dev-shm-usage', '--enable-unsafe-swiftshader', '--use-angle=swiftshader',
  '--remote-debugging-port=0', `--user-data-dir=${logs}/chrome-profile`, 'about:blank']);
let stderr = '', socket, nextId = 0;
const pending = new Map(), exceptions = [], consoleLines = [];
const guard = /JSPI SUSPEND GUARD: (.*)\)$/;
try {
  const endpoint = await new Promise((resolve, reject) => {
    chrome.stderr.on('data', data => {
      stderr += data;
      const match = stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) resolve(match[1]);
    });
    chrome.on('exit', code => reject(new Error(`Chrome exited ${code}`)));
    chrome.on('error', reject);
  });
  const address = new URL(endpoint);
  const targets = await (await fetch(`http://${address.host}/json/list`)).json();
  socket = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
  await new Promise(resolve => socket.onopen = resolve);
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params);
    if (message.method === 'Runtime.consoleAPICalled')
      consoleLines.push(message.params.args.map(arg => arg.value ?? arg.description).join(' '));
    if (pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    }
  };
  const call = (method, params = {}) => new Promise(resolve => {
    const id = ++nextId;
    pending.set(id, resolve);
    socket.send(JSON.stringify({id, method, params}));
  });
  async function evaluate(expression) {
    const result = await call('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
    if (result.error || result.result.exceptionDetails) throw new Error(JSON.stringify(result));
    return result.result.result.value;
  }
  const status = () => evaluate('document.documentElement.dataset.status');
  const waitFrames = count => evaluate(`new Promise((resolve, reject) => {
    const target = (Module.jankFrameStats?.frames ?? 0) + ${count};
    const timeout = setTimeout(() => reject(new Error('Frame loop stalled')), 30000);
    (function check() {
      if (document.documentElement.dataset.status === 'fail') { clearTimeout(timeout); reject(new Error('Page failed')); }
      else if (Module.jankFrameStats?.frames >= target) { clearTimeout(timeout); resolve(Module.jankFrameStats); }
      else requestAnimationFrame(check);
    })();
  })`);
  const load = async () => {
    await call('Page.navigate', {url: `http://127.0.0.1:${server.address().port}/`});
    await evaluate(`new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('No frames')), 60000);
      (function check() {
        if (window.Module?.jankFrameStats?.frames >= 5) { clearTimeout(timeout); resolve(); }
        else setTimeout(check, 50);
      })();
    })`);
    await evaluate('Module.canvas.focus()');
  };
  // Wait for the next suspension so the write lands in a frozen, freshly hashed range.
  const corrupt = offset => evaluate(`new Promise(resolve => {
    const count = Module.jankSuspend.count;
    (function wait() {
      if (Module.jankSuspend.count === count) { setTimeout(wait, 0); return; }
      const {sp, base} = Module.jankSuspend;
      const address = ${offset} >= 0 ? sp + Math.floor((base - sp) * ${offset}) : sp + ${offset};
      HEAPU8[address] ^= 0xff;
      resolve({sp, base, address});
    })();
  })`);
  await call('Runtime.enable');
  await call('Page.enable');

  await load();
  const start = await evaluate('Module.jankFrameStats');
  if (!(start.suspensions > 0 && start.suspendedStackBytes > 0))
    throw new Error(`Guard inactive: ${JSON.stringify(start)}`);
  const rect = await evaluate('(() => { const r=Module.canvas.getBoundingClientRect(); return {x:r.x, y:r.y, w:r.width, h:r.height}; })()');
  let events = 0;
  const deadline = Date.now() + seconds * 1000;
  for (let i = 0; Date.now() < deadline; i++) {
    const x = rect.x + rect.w * ((i * 37) % 100) / 100, y = rect.y + rect.h * ((i * 61) % 100) / 100;
    const burst = [
      call('Input.dispatchKeyEvent', {type: 'keyDown', key: ' ', code: 'Space', windowsVirtualKeyCode: 32}),
      call('Input.dispatchMouseEvent', {type: 'mouseMoved', x, y}),
      call('Input.dispatchMouseEvent', {type: 'mousePressed', x, y, button: 'left', clickCount: 1}),
      call('Input.dispatchMouseEvent', {type: 'mouseWheel', x, y, deltaX: 0, deltaY: 40}),
      call('Input.dispatchMouseEvent', {type: 'mouseReleased', x, y, button: 'left', clickCount: 1}),
      call('Input.dispatchKeyEvent', {type: 'keyUp', key: ' ', code: 'Space', windowsVirtualKeyCode: 32}),
    ];
    if (i % 25 === 0) burst.push(evaluate(`(Module.canvas.blur(), Module.canvas.focus(),
      window.dispatchEvent(new Event('resize')), true)`));
    await Promise.all(burst);
    events += burst.length;
  }
  const stressed = await waitFrames(3);
  if (await status() === 'fail' || exceptions.length) throw new Error('Stress run failed');
  if (stressed.suspensions - start.suspensions < 60) throw new Error('Too few suspensions');
  console.log(`STRESS: PASS seconds=${seconds} events=${events} frames=${stressed.frames - start.frames} ` +
    `suspensions=${stressed.suspensions - start.suspensions} suspended-stack-max=${stressed.suspendedStackBytes}`);

  const below = await corrupt(-64);
  await waitFrames(30);
  if (await status() === 'fail' || consoleLines.some(line => guard.test(line)))
    throw new Error('Guard fired on a write below the suspended stack pointer');
  console.log(`CONTROL BELOW SP: PASS address=${below.address} sp=${below.sp}`);

  const above = await corrupt(0.5);
  await evaluate(`new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Guard did not fire')), 10000);
    (function check() {
      if (document.documentElement.dataset.status === 'fail') { clearTimeout(timeout); resolve(); }
      else setTimeout(check, 10);
    })();
  })`);
  const fired = consoleLines.map(line => line.match(guard)?.[1]).find(Boolean);
  if (!fired?.startsWith('suspended stack frames were overwritten'))
    throw new Error(`Unexpected failure: ${consoleLines.slice(-5).join('\n')}`);
  console.log(`CONTROL ABOVE SP: PASS address=${above.address} sp=${above.sp} base=${above.base} guard="${fired}"`);
  console.log('JSPI SUSPEND GUARD: PASS');
} catch (error) {
  console.error(error);
  console.error(JSON.stringify(exceptions));
  process.exitCode = 1;
} finally {
  fs.writeFileSync(path.join(logs, 'chrome-stderr.log'), stderr);
  fs.writeFileSync(path.join(logs, 'console.log'), consoleLines.join('\n'));
  socket?.close();
  chrome.kill();
  server.close();
}
