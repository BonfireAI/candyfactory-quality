#!/usr/bin/env node
// Consumer entrypoint for @candyfactory/cf-gate-ts.
//
// The gate runner is TypeScript (src/runner/cfGateTs.ts) and runs via tsx. A
// repo that installs this package (e.g. as a `file:` dependency) gets `cf-gate-ts`
// on its PATH (node_modules/.bin) and can invoke it without wiring tsx itself —
// tsx + typescript + eslint + dependency-cruiser ship as this package's runtime
// `dependencies` (not devDependencies, which npm would not install for a consumer).
//
// tsx must be resolved from THIS package's location (it lives in the kit's own
// node_modules under a `file:` symlink install, or hoisted under a normal
// install). Node's resolver walks both, so require.resolve from here finds it;
// resolving `--import tsx` from the consumer cwd would not.
//
// Usage:  cf-gate-ts [path/to/cfq-ts.config.json]   (defaults to ./cfq-ts.config.json)
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const runner = resolve(here, '../src/runner/cfGateTs.ts');
const require = createRequire(import.meta.url);

// Resolve tsx's CLI entry from this package's perspective and run it directly.
const tsxCli = pathToFileURL(require.resolve('tsx/cli')).href;

const result = spawnSync(
  process.execPath,
  [fileURLToPath(tsxCli), runner, ...process.argv.slice(2)],
  { stdio: 'inherit' },
);

process.exit(result.status ?? 1);
