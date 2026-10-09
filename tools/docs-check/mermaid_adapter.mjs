// Local installed package only. No rendering, browser, network or package manager.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
let entry;
try {
  const supplied = process.argv[2];
  if (supplied) {
    const full = path.resolve(supplied);
    if (fs.statSync(full).isDirectory()) {
      entry = require.resolve(full);
    } else {
      entry = full;
    }
  } else {
    entry = require.resolve('mermaid');
  }
} catch {
  process.stdout.write(process.argv[2] ? 'UNUSABLE' : 'UNAVAILABLE');
  process.exit(2);
}

// Suppress package diagnostics, which can contain source text or private values.
const output = process.stdout.write.bind(process.stdout);
process.stdout.write = () => true;
process.stderr.write = () => true;
let mermaid;
try {
  mermaid = (await import(pathToFileURL(entry).href)).default;
  if (typeof mermaid?.parse !== 'function') throw new Error();
  mermaid.initialize?.({ startOnLoad: false, securityLevel: 'strict' });
  // A parser that cannot parse a known-valid control is unusable in this runtime.
  if (!(await mermaid.parse('flowchart TD\nA-->B', { suppressErrors: false }))) throw new Error();
  let rejected = false;
  try {
    rejected = !(await mermaid.parse('not_a_mermaid_diagram_792', { suppressErrors: false }));
  } catch { rejected = true; }
  if (!rejected) throw new Error();
} catch {
  output('UNUSABLE');
  process.exit(2);
}
try {
  const text = fs.readFileSync(0, 'utf8');
  const parsed = await mermaid.parse(text, { suppressErrors: false });
  if (!parsed) throw new Error();
  output('PASS');
} catch (error) {
  // Runtime/DOM/package errors are not proof of invalid diagram syntax.
  const syntax = error?.hash || error?.name === 'UnknownDiagramError';
  output(syntax ? 'INVALID' : 'UNUSABLE');
  process.exitCode = syntax ? 1 : 2;
}
