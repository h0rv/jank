// AI-assisted bounded Chrome check; uses only Node built-ins.
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn, execFileSync} from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const directory = path.join(root, 'artifacts/app/tetris/wasm');
const headed = process.argv.includes('--headed');
const logs = path.join(root, 'artifacts/logs/tetris', headed ? 'headed' : 'headless');
fs.mkdirSync(logs, {recursive: true});
const server = http.createServer((req, res) => {
  const name = req.url === '/' ? 'index.html' : req.url.slice(1);
  if (!['index.html', 'tetris.js', 'tetris.wasm'].includes(name)) {
    res.writeHead(404).end();
    return;
  }
  res.setHeader('Content-Type', name.endsWith('.wasm') ? 'application/wasm' :
    name.endsWith('.js') ? 'text/javascript' : 'text/html');
  fs.createReadStream(path.join(directory, name)).pipe(res);
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const chrome = spawn('google-chrome', [...(headed ? [] : ['--headless']), '--no-sandbox', '--no-first-run',
  '--window-size=1400,1100', '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
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
      else if (${condition}) { clearTimeout(timeout); resolve(Module.jankFrameStats); }
      else requestAnimationFrame(check);
    }
    check();
  })`);
  await call('Runtime.enable');
  await call('Page.enable');
  await call('Page.navigate', {url: `http://127.0.0.1:${server.address().port}/`});
  await waitFor('window.Module?.jankFrameStats?.frames >= 5');
  const snapshot = async name => {
    const pixels = await evaluate(`new Promise(resolve => {
      Module.onJankFrame = () => {
        delete Module.onJankFrame;
        const gl = Module.ctx, canvas = Module.canvas;
        const data = new Uint8Array(canvas.width * canvas.height * 4);
        gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, data);
        const colors = new Set();
        let hash = 2166136261;
        for (let i = 0; i < data.length; i += 4) {
          const color = data[i] | data[i+1] << 8 | data[i+2] << 16;
          colors.add(color);
          hash = Math.imul(hash ^ color, 16777619);
        }
        resolve({colors: colors.size, hash: hash >>> 0, glError: gl.getError()});
      };
    })`);
    const screenshot = await call('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
    fs.writeFileSync(path.join(logs, `${name}.png`), Buffer.from(screenshot.result.data, 'base64'));
    if (pixels.colors < 2 || pixels.glError) throw new Error(`Blank/error canvas: ${JSON.stringify(pixels)}`);
    return pixels;
  };
  const before = await snapshot('welcome');
  await evaluate('Module.canvas.focus()');
  const key = async (key, code, value) => {
    const start = await evaluate('Module.jankFrameStats.frames');
    await call('Input.dispatchKeyEvent', {type: 'keyDown', key, code,
      windowsVirtualKeyCode: value, nativeVirtualKeyCode: value});
    await waitFor(`Module.jankFrameStats.frames >= ${start + 3}`);
    await call('Input.dispatchKeyEvent', {type: 'keyUp', key, code,
      windowsVirtualKeyCode: value, nativeVirtualKeyCode: value});
  };
  await key('Enter', 'Enter', 13);
  await key(' ', 'Space', 32);
  const rect = await evaluate('(() => { const r=Module.canvas.getBoundingClientRect(); return {x:r.x+r.width*0.5,y:r.y+r.height*(315/800)}; })()');
  await call('Input.dispatchMouseEvent', {type:'mouseMoved', ...rect});
  await call('Input.dispatchMouseEvent', {type:'mousePressed', ...rect, button:'left', clickCount:1});
  const clickFrame = await evaluate('Module.jankFrameStats.frames');
  await waitFor(`Module.jankFrameStats.frames >= ${clickFrame + 3}`);
  await call('Input.dispatchMouseEvent', {type:'mouseReleased', ...rect, button:'left', clickCount:1});
  await waitFor(`Module.jankFrameStats.frames >= ${clickFrame + 6}`);
  const started = await snapshot('started');
  await key('ArrowLeft', 'ArrowLeft', 37);
  await key('ArrowUp', 'ArrowUp', 38);
  await key('ArrowRight', 'ArrowRight', 39);
  await key(' ', 'Space', 32);
  const after = await snapshot('input');
  if (before.hash === started.hash || started.hash === after.hash)
    throw new Error('Inputs did not visibly change canvas');
  console.log(`CANVAS: PASS colors=${before.colors} welcome=${before.hash} started=${started.hash} input=${after.hash}`);
  console.log('INPUT: Enter/Space sent; raygui Start clicked; arrows/Space changed rendered game');
  const measure = async (interval, seconds) => {
    await evaluate(`Module.jankCollectEvery = ${interval}`);
    const start = await evaluate('Module.jankFrameStats');
    await evaluate(`new Promise(resolve => setTimeout(resolve, ${seconds * 1000}))`);
    const end = await evaluate('Module.jankFrameStats');
    const fps = 1000 * (end.frames - start.frames) / (end.time - start.time);
    console.log(`FPS: collect-every=${interval} seconds=${seconds} fps=${fps.toFixed(2)} collections=${end.collections-start.collections} heap=${end.heap} used=${end.used}`);
    if (!Number.isFinite(fps) || fps < 1) throw new Error('Frame loop stopped');
    return {fps, start, end};
  };
  if (!headed) {
    await measure(1, 10);
    await measure(10, 10);
    await evaluate('Module.jankCollectEvery = 1');
    const samples = [await evaluate('Module.jankFrameStats')];
    for (let second = 1; second <= 60; second++) {
      await key(second % 2 ? 'ArrowLeft' : 'ArrowRight', second % 2 ? 'ArrowLeft' : 'ArrowRight', second % 2 ? 37 : 39);
      if (second % 5 === 0) await key(' ', 'Space', 32);
      await evaluate('new Promise(resolve => setTimeout(resolve, 1000))');
      samples.push(await evaluate('Module.jankFrameStats'));
    }
    fs.writeFileSync(path.join(logs, 'memory.json'), JSON.stringify(samples, null, 2));
    const start = samples[0], end = samples.at(-1);
    console.log(`MEMORY: seconds=${((end.time-start.time)/1000).toFixed(2)} frames=${end.frames-start.frames} linear-start=${start.memory} linear-end=${end.memory} growth=${end.memory-start.memory} heap-start=${start.heap} heap-end=${end.heap} used-start=${start.used} used-end=${end.used}`);
    if (end.frames <= start.frames || end.collections <= start.collections) throw new Error('No frames/GC during play');
  }
  await snapshot('final');
  if (headed) execFileSync('import', ['-window', 'root', path.join(logs, 'desktop.png')]);
  if (exceptions.length || await evaluate('document.documentElement.dataset.status === "fail"'))
    throw new Error('Browser exceptions/failure observed');
  console.log('BROWSER EXCEPTIONS: 0');
  console.log(`SCREENSHOTS: ${logs}/{welcome,started,input,final}.png`);
  console.log('TETRIS MEMORY64: PASS');
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
