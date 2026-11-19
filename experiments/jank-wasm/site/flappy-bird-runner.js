// AI-assisted runner for the ahead-of-time raylib game.
const diagnostics = document.getElementById('stdout');
const status = document.getElementById('status');
const canvas = document.getElementById('canvas');
const message = document.getElementById('game-message');
let failed = false, ready = false;
function fail(reason) {
  failed = true;
  diagnostics.textContent += `${reason}\n`;
  document.documentElement.dataset.status = 'fail';
  status.textContent = 'failed, see runtime log';
  message.hidden = false;
  message.textContent = `Could not run the game. Needs memory64, Wasm exceptions, JSPI and WebGL2. ${reason}`;
  diagnostics.hidden = false;
}
canvas.addEventListener('click', () => canvas.focus());
canvas.addEventListener('keydown', event => {
  if (event.code === 'Space') event.preventDefault();
});
window.addEventListener('error', event => fail(event.message));
window.addEventListener('unhandledrejection', event => fail(event.reason));
// The page's ?v= stamp, passed on so a republish never mixes cached and new files.
const version = document.currentScript?.src ? new URL(document.currentScript.src).search : '';
var Module = {
  canvas,
  locateFile: (path, dir) => `${dir}${path}${version}`,
  print: line => { diagnostics.textContent += `${line}\n`; },
  printErr: line => { diagnostics.textContent += `${line}\n`; console.warn(line); },
  onAbort: fail,
  onExit: code => fail(`Game exited (${code}).`),
  onJankFrame: stats => {
    if (failed) return;
    if (!ready || stats.frames % 60 === 0) status.textContent = `running · wasm64 · frame ${stats.frames}`;
    ready = true;
    message.hidden = true;
    document.documentElement.dataset.status = 'pass';
  }
};
if (typeof WebAssembly === 'undefined') {
  fail('WebAssembly is unavailable in this browser.');
} else if (typeof WebAssembly.promising !== 'function' || typeof WebAssembly.Suspending !== 'function') {
  fail('WebAssembly JSPI is unavailable in this browser.');
} else {
  const script = document.createElement('script');
  script.src = `flappy-bird.js${version}`;
  script.onerror = () => fail('Could not load flappy-bird.js. Serve all site files together over HTTP.');
  document.body.appendChild(script);
}
