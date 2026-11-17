// AI-assisted runner for the ahead-of-time hello-cljc example.
const diagnostics = document.getElementById('stdout');
const status = document.getElementById('status');
function finish(ok, message) {
  document.documentElement.dataset.status = ok ? 'pass' : 'fail';
  status.textContent = message;
  document.title = `jank-wasm · ${ok ? 'PASS' : 'FAIL'}`;
}
function fail(reason) {
  diagnostics.textContent += `${reason}\n`;
  finish(false, 'failed, see runtime log');
}
window.addEventListener('error', event => fail(event.message));
window.addEventListener('unhandledrejection', event => fail(event.reason));
var Module = {
  arguments: ['static-roots'],
  print: line => { diagnostics.textContent += `${line}\n`; },
  printErr: line => { diagnostics.textContent += `${line}\n`; },
  onAbort: fail,
  onExit: code => {
    const lines = document.getElementById('app').textContent.split('\n');
    const ok = code === 0 && ['platform: browser', 'weighted buffer: 30',
      'hello: checks passed'].every(line => lines.includes(line));
    finish(ok, ok ? 'exit 0, checks passed' : 'failed, see runtime log');
  }
};
if (typeof WebAssembly === 'undefined') {
  fail('WebAssembly is unavailable in this browser.');
} else {
  const script = document.createElement('script');
  script.src = 'hello.js';
  script.onerror = () => fail('Could not load hello.js. Serve all site files together over HTTP.');
  document.body.appendChild(script);
}
