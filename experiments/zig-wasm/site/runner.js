// AI-assisted runner: keeps the compiled live-demo module running and feeds it edits.
const input = document.getElementById('input');
const result = document.getElementById('result');
const status = document.getElementById('status');
const stats = document.getElementById('stats');
const diagnostics = document.getElementById('stdout');
let module = null;
let sentAt = 0;
let shownAt = -Infinity;

function finish(state, message) {
  document.documentElement.dataset.status = state;
  status.textContent = message;
}
function fail(reason) {
  diagnostics.textContent += `${reason}\n`;
  input.disabled = true;
  finish('fail', 'failed, see runtime log');
}
function send() {
  if (!module) return;
  sentAt = performance.now();
  module.liveInput = input.value;
}

window.addEventListener('error', event => fail(event.message));
window.addEventListener('unhandledrejection', event => fail(event.reason));

const options = {
  arguments: ['static-roots'],
  jankCollectEvery: 30,
  print: line => { diagnostics.textContent += `${line}\n`; },
  printErr: line => { diagnostics.textContent += `${line}\n`; },
  onAbort: fail,
  onLiveResult: text => {
    result.textContent = text;
    finish('pass', `answered in ${Math.max(0, performance.now() - sentAt).toFixed(1)} ms`);
  },
  onJankFrame: frame => {
    const now = performance.now();
    if (now - shownAt < 250) return;
    shownAt = now;
    stats.textContent = `Running: frame ${frame.frames}, ${frame.collections} garbage collections, ` +
      `${(frame.used / 1048576).toFixed(1)} MiB of ${(frame.heap / 1048576).toFixed(1)} MiB GC heap in use.`;
  }
};

if (typeof WebAssembly === 'undefined') {
  fail('WebAssembly is unavailable in this browser.');
} else {
  const script = document.createElement('script');
  script.src = 'live.js';
  script.onerror = () => fail('Could not load live.js. Serve all site files together over HTTP.');
  script.onload = () => createLive(options).then(instance => {
    module = instance;
    input.disabled = false;
    input.addEventListener('input', send);
    send();
  }, fail);
  document.body.appendChild(script);
}
