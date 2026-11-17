// AI-assisted runner: keeps the compiled live-demo module running and starts prime counts.
// The page's ?v= stamp, passed on so a republish never mixes cached and new files.
const version = document.currentScript?.src ? new URL(document.currentScript.src).search : '';
const form = document.getElementById('run-form');
const input = document.getElementById('input');
const run = document.getElementById('run');
const result = document.getElementById('result');
const status = document.getElementById('status');
const stats = document.getElementById('stats');
const diagnostics = document.getElementById('stdout');
let module = null;
let startedAt = 0;
let shownAt = -Infinity;
let loading = false;
let observer = null;

function finish(state, message) {
  document.documentElement.dataset.status = state;
  status.textContent = message;
}
function fail(reason) {
  diagnostics.textContent += `${reason}\n`;
  run.disabled = true;
  finish('fail', 'failed; requires memory64 and Wasm exceptions; see runtime log');
}
function start() {
  if (!module) return;
  startedAt = performance.now();
  result.textContent = '';
  finish('running', 'running');
  run.textContent = 'Run again';
  module.liveInput = input.value.trim();
}
function append(line) {
  result.textContent += `${line}\n`;
  result.scrollTop = result.scrollHeight;
}

window.addEventListener('error', event => fail(event.message));
window.addEventListener('unhandledrejection', event => fail(event.reason));

const options = {
  arguments: ['static-roots'],
  locateFile: (path, dir) => `${dir}${path}${version}`,
  jankCollectEvery: 30,
  print: line => { diagnostics.textContent += `${line}\n`; },
  printErr: line => { diagnostics.textContent += `${line}\n`; },
  onAbort: fail,
  onLiveLine: append,
  onLiveFinish: line => {
    append(line);
    finish('pass', `done in ${Math.round(performance.now() - startedAt)} ms`);
  },
  onJankFrame: frame => {
    const now = performance.now();
    if (now - shownAt < 250) return;
    shownAt = now;
    stats.textContent = `Running: frame ${frame.frames}, ${frame.collections} garbage collections, ` +
      `${(frame.used / 1048576).toFixed(1)} MiB of ${(frame.heap / 1048576).toFixed(1)} MiB GC heap in use.`;
  }
};

function load() {
  if (loading || typeof WebAssembly === 'undefined') return;
  loading = true;
  observer?.disconnect();
  status.textContent = 'loading';
  const script = document.createElement('script');
  script.src = `live.js${version}`;
  script.onerror = () => fail('Could not load live.js. Serve all site files together over HTTP.');
  script.onload = () => createLive(options).then(instance => {
    module = instance;
    run.disabled = false;
    start();
  }, fail);
  document.body.appendChild(script);
}

form.addEventListener('submit', event => {
  event.preventDefault();
  if (module) start();
  else load();
});

if (typeof WebAssembly === 'undefined') {
  fail('WebAssembly is unavailable in this browser.');
} else if (typeof IntersectionObserver === 'function') {
  status.textContent = 'waiting until visible';
  observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) load();
  }, { rootMargin: '200px' });
  observer.observe(form);
} else {
  load();
}
