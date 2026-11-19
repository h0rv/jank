// AI-assisted Node runner for the experimental wasm64 static runtime.
import { spawn } from 'node:child_process';
import { access, mkdir, mkdtemp, readdir, readFile, writeFile } from 'node:fs/promises';
import { availableParallelism } from 'node:os';
import { basename, dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

const scripts = dirname(fileURLToPath(import.meta.url));
const root = dirname(scripts);
const source = join(root, '../../compiler+runtime');
const tools = join(root, '.tools');
const target = join(root, 'artifacts/build-wasm64');
const host = join(root, 'artifacts/build-host/jank');
const runtime = join(target, 'libjank-static-runtime.a');
const node = join(tools, 'node-v26.13.1-linux-x64/bin/node');
const nodeFlags = ['--stack_size=6144'];
const sdk = join(tools, 'gc-wasm/emsdk');
const container = 'jank-host-build';
const user = process.getuid() + ':' + process.getgid();

const { values } = parseArgs({
  options: {
    suite: { type: 'string', default: 'all' },
    filter: { type: 'string', default: '' },
    jobs: { type: 'string', default: String(Math.min(availableParallelism(), 6)) },
    help: { type: 'boolean' },
  },
});
if (values.help) {
  console.log('node scripts/wasm-tests.mjs [--suite all|doctest|files] [--filter REGEX] [--jobs N]');
  process.exit(0);
}
const jobs = Number(values.jobs);
if (!['all', 'files', 'doctest'].includes(values.suite)
    || !Number.isSafeInteger(jobs) || jobs < 1) {
  throw new Error('Expected --suite all|doctest|files and positive integer --jobs');
}
if (values.filter && values.suite !== 'files') {
  throw new Error('--filter applies only to --suite files');
}
const filter = new RegExp(values.filter);
const outputParent = join(root, 'artifacts/wasm64-tests');
await mkdir(outputParent, { recursive: true });
const output = await mkdtemp(join(outputParent, 'run-'));
console.log('Results: ' + output);

function execute(command, args, timeout = 120_000) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args);
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    child.stdout.setEncoding('utf8').on('data', (chunk) => { stdout += chunk; });
    child.stderr.setEncoding('utf8').on('data', (chunk) => { stderr += chunk; });
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGKILL');
    }, timeout);
    child.once('error', (error) => { clearTimeout(timer); reject(error); });
    child.once('close', (code, signal) => {
      clearTimeout(timer);
      resolve({ code, signal, stdout, stderr, timedOut });
    });
  });
}

async function docker(args, log, { cwd = target, timeout } = {}) {
  const seconds = Math.ceil((timeout ?? 120_000) / 1000);
  const command = ['exec', '--user', user, '-w', cwd, container, 'timeout', '-k', '5s',
    seconds + 's', 'env',
    'LANG=C.UTF-8', 'LC_ALL=C.UTF-8', 'TMPDIR=' + join(root, 'artifacts/tmp'),
    'EM_CONFIG=' + join(sdk, '.emscripten'), ...args];
  const result = await execute('docker', command, (seconds + 10) * 1000);
  result.timedOut ||= result.code === 124;
  if (log) {
    await writeFile(log, JSON.stringify(['docker', ...command]) + '\n'
      + JSON.stringify({ code: result.code, signal: result.signal, timedOut: result.timedOut })
      + '\n' + result.stdout + '\n' + result.stderr);
  }
  return result;
}

const failed = (result) => result.code !== 0 || result.timedOut;
const failureKind = (result, ordinary) => result.timedOut ? 'timeout'
  : result.signal ? 'process-signal' : ordinary;

async function parallel(items, work) {
  const results = [];
  let next = 0;
  const workers = Array.from({ length: Math.min(jobs, items.length) }, async () => {
    while (next < items.length) {
      const index = next++;
      results[index] = await work(items[index], index);
    }
  });
  const settled = await Promise.allSettled(workers);
  for (const worker of settled) {
    if (worker.status === 'rejected') throw worker.reason;
  }
  return results;
}

async function files(directory, extension) {
  const entries = await readdir(directory, { recursive: true, withFileTypes: true });
  return entries.filter((entry) => entry.isFile() && entry.name.endsWith(extension))
    .map((entry) => join(entry.parentPath, entry.name)).sort();
}

for (const path of [join(target, 'compile_commands.json'), runtime, node,
  join(root, 'artifacts/build-binaryen/bin/wasm-opt'),
  ...(values.suite !== 'doctest' ? [host] : []),
]) {
  try {
    await access(path);
  } catch {
    throw new Error('Missing ' + path + '; first build the documented hello-cljc project with jank-build');
  }
}
if (failed(await execute('docker', ['start', container]))) {
  throw new Error('Cannot start the jank-host-build container');
}

// Reuse the app driver's exact target compiler flags; the compile database is shell-quoted.
const database = await docker(['python3', '-B', '-c', [
  'import json, pathlib, runpy, sys',
  'wasm_compile_flags = runpy.run_path("jank-build.py")["wasm_compile_flags"]',
  'print(json.dumps(wasm_compile_flags(json.loads(pathlib.Path(sys.argv[1]).read_text()))))',
].join('\n'), join(target, 'compile_commands.json')], join(output, 'compiler-flags.log'),
{ cwd: scripts });
if (failed(database)) throw new Error('Unable to read the wasm64 compile database');
const [flags, compileCwd] = JSON.parse(database.stdout);

async function compile(input, object, log, extra = []) {
  return await docker([...flags, '-O2', ...extra, '-c', input, '-o', object], log, { cwd: compileCwd });
}

async function build(directory, objects, name) {
  const js = join(directory, name + '.js');
  const link = await docker([flags[0], '-O2', '--profiling-funcs', '-sMEMORY64=1',
    '-fwasm-exceptions', '-sALLOW_MEMORY_GROWTH=1', '-sSTACK_SIZE=4194304',
    '-sENVIRONMENT=node', '-sEXIT_RUNTIME=1', '-sNODERAWFS=1',
    ...objects, runtime, '-o', js], join(directory, name + '-link.log'));
  if (failed(link)) return { status: failureKind(link, 'link-error') };
  const transform = await docker(['BINARYEN_CORES=' + Math.min(jobs, 6), 'python3',
    join(root, 'wasm-probe/spill-pointers.py'), root, join(directory, name + '.wasm'),
    '--no-coalesce'], join(directory, name + '-spill.log'),
  { timeout: 300_000 });
  if (failed(transform)) return { status: failureKind(transform, 'spill-error') };
  return { js };
}

async function doctest() {
  const directory = join(output, 'doctest');
  await mkdir(directory);
  const testSources = await files(join(source, 'test/cpp'), '.cpp');
  const nativeOnly = {
    'jank/jit/processor.cpp': 'native JIT file aggregate; replaced by the AOT fixture runner',
    'jank/analyze/cpp_util.cpp': 'Clang and CppInterOp',
    'jank/util/sha256.cpp': 'LLVM Support',
  };
  const omitted = new Set(['main.cpp', ...Object.keys(nativeOnly)]);
  const objects = await parallel([
    join(scripts, 'wasm-doctest.cpp'),
    ...testSources.filter((path) => !omitted.has(relative(join(source, 'test/cpp'), path))),
    join(source, 'src/cpp/jank/jit/parse_ld_script.cpp'),
    // The native CMake target enables a lexer helper used by the same unmodified doctests.
    join(source, 'src/cpp/jank/read/lex.cpp'),
  ], async (input, index) => {
    const object = join(directory, index + '.o');
    const result = await compile(input, object, object + '.log', [
      '-DJANK_TEST', '-DDOCTEST_CONFIG_NO_POSIX_SIGNALS', '-DDOCTEST_CONFIG_SUPER_FAST_ASSERTS',
      '-Wno-c++11-narrowing',
      '-I' + join(source, 'third-party/doctest'),
    ]);
    return failed(result) ? null : object;
  });
  if (objects.includes(null)) return { status: 'target-cpp-error' };
  const binary = await build(directory, objects, 'doctest');
  if (!binary.js) return binary;
  const result = await docker([node, ...nodeFlags, binary.js, '--no-colors',
    '--test-case-exclude=generated throws use rooted runtime exceptions'],
  join(directory, 'node.log'), { cwd: source });
  const summary = result.stdout.match(/^JANK_WASM_DOCTEST (\d+) (\d+) (\d+) (\d+)$/m);
  const gc = result.stdout.match(/^JANK_WASM_DOCTEST_GC (\d+) (\d+) (\d+)$/m);
  if (!summary || !gc || gc[3] !== '0' || Number(summary[4]) === 0) {
    return { status: failureKind(result, 'incomplete') };
  }
  const [, registered, cases, failures, forcedCollections] = summary.map(Number);
  const failedCases = [...result.stdout.matchAll(/^JANK_WASM_DOCTEST_FAILURE (\d+) (.+)$/gm)]
    .map(([, flags, location]) => ({ flags: Number(flags), location }));
  return { status: failed(result) || failures ? 'fail' : 'pass',
    cases, passed: cases - failures, failed: failures, filtered: registered - cases,
    nativeOnly,
    collections: Number(gc[2]) - Number(gc[1]), forcedCollections, failedCases };
}

async function compileFixture(path, index) {
  const filename = basename(path);
  const expected = filename.split('-')[0];
  const id = String(index).padStart(4, '0');
  const test = { id, path: relative(source, path), expected };
  if (expected === 'skip' || expected === 'warn') return { ...test, status: 'upstream-' + expected };
  if (!['pass', 'fail', 'throw'].includes(expected)) throw new Error('Unknown fixture prefix: ' + path);
  const namespace = 'wasm-test-' + id;
  const moduleFile = namespace.replaceAll('-', '_');
  const directory = join(output, 'files', id);
  await mkdir(directory);
  const fixture = await readFile(path, 'utf8');
  // A leading raw C++ declaration must stay at top level so the host analyzer
  // can resolve its C++ names when compiling the function below.
  const rawDeclaration = /^(?:\s|;[^\n]*(?:\n|$))*\(cpp\/raw\s+"(?:[^"\\]|\\[\s\S])*"\s*\)/;
  let declarations = '';
  let body = fixture;
  for (let match; (match = body.match(rawDeclaration));) {
    declarations += match[0] + '\n';
    body = body.slice(match[0].length);
  }
  // Keep the actual forms out of the host's top-level evaluation path.
  // Both the host reader and the Wasm runtime start the fixture in the native harness's user ns.
  await writeFile(join(directory, moduleFile + '.jank'),
    "(clojure.core/in-ns 'user)\n(clojure.core/refer 'clojure.core)\n"
    + declarations + '(defn ' + namespace + ' []\n' + body + '\n)\n');
  const result = await docker(['JANK_RUNTIME_DIR=' + join(root, 'artifacts/host-resources'), host,
    '--module-path', directory, '--build-dir', join(directory, 'generated'),
    '--output-target', 'cpp', 'compile-module', namespace], join(directory, 'frontend.log'),
  { cwd: directory });
  if (failed(result)) return { ...test, status: failureKind(result, 'host-rejected') };
  const generated = (await files(join(directory, 'generated'), '.cpp')).filter(
    (entry) => basename(entry) === moduleFile + '.cpp');
  if (generated.length !== 1) return { ...test, status: 'missing-generated-source' };
  const object = join(directory, 'fixture.o');
  const targetResult = await compile(generated[0], object, join(directory, 'target.log'));
  if (failed(targetResult)) return { ...test, status: failureKind(targetResult, 'target-cpp-error') };
  const nm = await docker([join(sdk, 'upstream/bin/llvm-nm'),
    '--extern-only', '--defined-only', '--format=posix', object], join(directory, 'symbols.log'));
  if (failed(nm)) return { ...test, status: 'symbol-read-error' };
  const symbols = nm.stdout.split('\n').flatMap((line) => {
    const [name, type] = line.split(/\s+/);
    return type && !['W', 'V', 'w', 'v', 'U'].includes(type) ? [name] : [];
  });
  return { ...test, object, namespace, moduleFile, symbols };
}

async function runBatch(batch, index, results) {
  const directory = join(output, 'files', 'batch-' + index);
  await mkdir(directory);
  await writeFile(join(directory, 'wasm-fixtures.inc'),
    batch.map((test) => 'extern "C" void jank_load_' + test.moduleFile + '();\n').join('')
    + 'fixture const fixtures[]{\n' + batch.map((test) => '  {'
      + [test.id, test.path, test.namespace]
          .map((value) => JSON.stringify(value)).join(', ')
      + ", '" + test.expected[0] + "', &jank_load_" + test.moduleFile + '},\n').join('') + '};\n');
  const object = join(directory, 'runner.o');
  const driver = await compile(join(scripts, 'wasm-jank-fixtures.cpp'), object,
    join(directory, 'driver.log'), ['-I' + directory]);
  const binary = failed(driver) ? { status: 'driver-build-error' }
    : await build(directory, [object, ...batch.map((test) => test.object)], 'fixtures');
  if (!binary.js) {
    if (binary.status === 'link-error' && batch.length > 1) {
      const middle = Math.ceil(batch.length / 2);
      return [
        ...await runBatch(batch.slice(0, middle), index + '-a', results),
        ...await runBatch(batch.slice(middle), index + '-b', results),
      ];
    }
    for (const test of batch) results.set(test.id, { status: binary.status });
    return [];
  }

  const failures = [];
  for (let remaining = batch; remaining.length;) {
    const startedAt = remaining[0].id;
    const result = await docker([node, ...nodeFlags, binary.js, startedAt],
      join(directory, startedAt + '-node.log'),
      { cwd: source });
    const ids = new Set(remaining.map((test) => test.id));
    const starts = new Set([...result.stdout.matchAll(/^JANK_WASM_START (\d+)$/gm)]
      .map((m) => m[1]).filter((id) => ids.has(id)));
    for (const [, id, status, collections, forcedCollections, disabled] of result.stdout.matchAll(
      /^JANK_WASM_RESULT (\d+) ([a-z-]+) (\d+) (\d+) (\d+)$/gm)) {
      if (starts.has(id)) {
        results.set(id, { status: disabled === '0' ? status : 'gc-disabled', ran: true,
          collections: Number(collections), forcedCollections: Number(forcedCollections) });
      }
    }
    if (!starts.size) {
      for (const test of remaining) {
        results.set(test.id, { status: failureKind(result, 'startup-failed') });
      }
      break;
    }
    for (const test of remaining) {
      if (starts.has(test.id) && !results.has(test.id)) {
        results.set(test.id, { status: failureKind(result, 'wasm-abort'), ran: true });
      }
    }
    if (![...starts].some((id) => results.get(id).forcedCollections > 0)) {
      for (const id of starts) {
        if (results.get(id).status === 'pass') {
          results.set(id, { ...results.get(id), status: 'missing-gc-evidence' });
        }
      }
    }
    if (failed(result) && remaining.every((test) => results.has(test.id))
        && starts.size && remaining.every((test) => results.get(test.id).collections != null)) {
      failures.push({ batch: index, status: failureKind(result, 'shutdown-failed') });
    }
    remaining = remaining.filter((test) => !results.has(test.id));
  }
  return failures;
}

async function jankFiles() {
  const paths = (await files(join(source, 'test/jank'), '.jank'))
    .filter((path) => !basename(path).startsWith('.') && filter.test(relative(source, path)));
  if (!paths.length) throw new Error('No fixtures match --filter');
  console.log('Compiling ' + paths.length + ' jank fixtures');
  await mkdir(join(output, 'files'));
  const fixtures = await parallel(paths, compileFixture);
  const batches = [];
  const results = new Map();
  for (const test of fixtures) {
    if (!test.object) {
      results.set(test.id, { status: test.status });
      continue;
    }
    // Raw C++ fixtures can independently define the same external symbol.
    // Do not silently allow duplicate definitions and bind a test to another fixture.
    let batch = batches.find((entry) => entry.tests.length < 64
      && test.symbols.every((symbol) => !entry.symbols.has(symbol)));
    if (!batch) {
      batch = { symbols: new Set(), tests: [] };
      batches.push(batch);
    }
    for (const symbol of test.symbols) batch.symbols.add(symbol);
    batch.tests.push(test);
  }
  console.log('Linking and running ' + batches.length + ' fixture bundles under Node');
  // Each Binaryen process is internally parallel and uses substantial memory.
  const batchFailures = [];
  for (const [index, batch] of batches.entries()) {
    batchFailures.push(...await runBatch(batch.tests, String(index), results));
  }
  const report = fixtures.map(({ id, path, expected }) => ({ id, path, expected, ...results.get(id) }));
  const counts = {};
  for (const test of report) {
    const key = test.status === 'host-rejected'
      ? 'host-rejected-' + (test.expected === 'pass' ? 'unexpected' : test.expected)
      : test.status;
    counts[key] = (counts[key] ?? 0) + 1;
  }
  const ran = report.filter((test) => test.ran).length;
  const passed = counts.pass ?? 0;
  return { selected: report.length, ran, passed, failed: ran - passed,
    notRun: report.length - ran, counts, batchFailures, fixtures: report };
}

const report = {};
if (values.suite !== 'files') {
  report.doctest = await doctest();
  console.log('Doctest: ' + JSON.stringify(report.doctest));
}
if (values.suite !== 'doctest') {
  report.files = await jankFiles();
  console.log('Jank files: ' + JSON.stringify(report.files.counts));
}
await writeFile(join(output, 'results.json'), JSON.stringify(report, null, 2) + '\n');
if ((report.doctest && report.doctest.status !== 'pass')
    || report.files?.batchFailures.length
    || report.files?.fixtures.some(({ status }) => !['pass', 'upstream-skip', 'upstream-warn'].includes(status))) {
  process.exitCode = 1;
}
