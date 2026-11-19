// AI-assisted JSPI suspend guard for scripts/raylib-loop-driver.cpp.
// emscripten_sleep is the only JSPI suspension point of a synchronous raylib
// app. While main is suspended, browser callbacks re-enter Wasm on the same
// linear-memory stack below the suspended stack pointer. The guard runs as the
// Suspending import itself, so it has no linear-memory frame of its own, and
// checks that the suspended frames [sp, base) are byte-identical on resume.
addToLibrary({
  __wrap_emscripten_sleep__deps: ['$stackSave', 'emscripten_sleep'],
  __wrap_emscripten_sleep__async: true,
  __wrap_emscripten_sleep__sig: 'vi',
  __wrap_emscripten_sleep: async (ms) => {
    const guard = Module.jankSuspend ??= {active: false, count: 0, maxBytes: 0};
    const fail = what => abort(`JSPI SUSPEND GUARD: ${what} (suspension ${guard.count}, ` +
      `sp=${guard.sp}, base=${guard.base})`);
    if (guard.active) fail('nested suspension would share the suspended C stack');
    const sp = Number(stackSave()), base = Module.jankStackBase;
    const saved = HEAPU8.slice(sp, base);
    Object.assign(guard, {active: true, sp, base, count: guard.count + 1,
      maxBytes: Math.max(guard.maxBytes, base - sp)});
    try {
      await _emscripten_sleep(ms);
    } finally {
      guard.active = false;
    }
    const resumed = Number(stackSave());
    if (resumed !== sp) fail(`stack pointer changed across suspension to ${resumed}`);
    const current = HEAPU8.subarray(sp, base);
    let first = -1, changed = 0;
    for (let i = 0; i < saved.length; i++) {
      if (saved[i] !== current[i]) {
        changed++;
        if (first < 0) first = i;
      }
    }
    if (changed) fail(`suspended stack frames were overwritten (${changed} bytes, first at sp+${first})`);
  },
});
