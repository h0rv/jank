// AI-assisted bounded Chrome check; uses only Node built-ins.
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const directory = path.join(root, 'artifacts/raylib/wasm64');
const logs = path.join(root, 'artifacts/logs/raylib');
fs.mkdirSync(logs, {recursive: true});
const server = http.createServer((req, res) => {
  const name = req.url === '/' ? 'index.html' : req.url.slice(1);
  if (!['index.html', 'probe.js', 'probe.wasm'].includes(name)) {
    res.writeHead(404).end();
    return;
  }
  res.setHeader('Content-Type', name.endsWith('.wasm') ? 'application/wasm' :
    name.endsWith('.js') ? 'text/javascript' : 'text/html');
  fs.createReadStream(path.join(directory, name)).pipe(res);
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const chrome = spawn('google-chrome', ['--headless', '--no-sandbox', '--no-first-run',
  '--disable-dev-shm-usage', '--enable-unsafe-swiftshader', '--use-angle=swiftshader',
  '--remote-debugging-port=0', `--user-data-dir=${logs}/chrome-profile`, 'about:blank']);
let stderr = '', socket, nextId = 0;
const pending = new Map(), exceptions = [], consoleLines = [];
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
  const waitFor = condition => evaluate(`new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Probe timed out')), 30000);
    function check() {
      if (window.probeErrors?.length) { clearTimeout(timeout); reject(new Error(probeErrors.join('\\n'))); }
      else if (${condition}) { clearTimeout(timeout); resolve(window.probeState); }
      else requestAnimationFrame(check);
    }
    check();
  })`);
  await call('Runtime.enable');
  await call('Page.enable');
  await call('Page.navigate', {url: `http://127.0.0.1:${server.address().port}/`});
  const before = await waitFor('window.probeState?.frames >= 5');
  if (before.glError || before.pixel.join(',') !== '190,33,55,255')
    throw new Error(`Initial pixel mismatch: ${JSON.stringify(before)}`);
  await evaluate('Module.canvas.focus()');
  await call('Input.dispatchKeyEvent', {type: 'keyDown', key: ' ', code: 'Space',
    windowsVirtualKeyCode: 32, nativeVirtualKeyCode: 32});
  const after = await waitFor('window.probeState?.keys === 1');
  await call('Input.dispatchKeyEvent', {type: 'keyUp', key: ' ', code: 'Space',
    windowsVirtualKeyCode: 32, nativeVirtualKeyCode: 32});
  if (after.glError || after.pixel.join(',') !== '0,228,48,255')
    throw new Error(`Changed pixel mismatch: ${JSON.stringify(after)}`);
  const rect = await evaluate('(() => { const r=Module.canvas.getBoundingClientRect(); return {x:r.x+50,y:r.y+195}; })()');
  await call('Input.dispatchMouseEvent', {type:'mouseMoved', ...rect});
  await call('Input.dispatchMouseEvent', {type:'mousePressed', ...rect, button:'left', clickCount:1});
  await waitFor(`window.probeState?.frames > ${after.frames + 2}`);
  await call('Input.dispatchMouseEvent', {type:'mouseReleased', ...rect, button:'left', clickCount:1});
  const final = await waitFor('window.probeState?.clicks === 1');
  if (exceptions.length || await evaluate('probeErrors.length')) throw new Error('Browser exceptions observed');
  const screenshot = await call('Page.captureScreenshot', {format: 'png'});
  fs.writeFileSync(path.join(logs, 'probe.png'), Buffer.from(screenshot.result.data, 'base64'));
  console.log(`CANVAS: PASS frames>=${before.frames} pixel=${before.pixel}`);
  for (const line of consoleLines.filter(line => /KEY SPACE|GUI BUTTON/.test(line))) console.log(line);
  console.log(`KEY INPUT: PASS state=${after.keys} pixel=${after.pixel}`);
  console.log(`RAYGUI BUTTON: PASS clicks=${final.clicks}`);
  console.log('BROWSER EXCEPTIONS: 0');
  console.log(`SCREENSHOT: ${logs}/probe.png`);
  console.log('RAYLIB/RAYGUI MEMORY64: PASS');
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
