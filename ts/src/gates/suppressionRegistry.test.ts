import { describe, it, expect } from 'vitest';
import { writeFileSync, unlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { findSuppressions, suppressionRegistryGate } from './suppressionRegistry.js';
import type { RegistryEntry } from './suppressionRegistry.js';

// ---------------------------------------------------------------------------
// Resolve test fixtures via import.meta.url so the tests are cwd-independent.
//
// import.meta.url = file:///…/ts/src/gates/suppressionRegistry.test.ts
//   new URL('./__rods__/…', import.meta.url) → ts/src/gates/__rods__/…
//   new URL('../',          import.meta.url) → ts/src/
//   new URL('./…ts',        import.meta.url) → ts/src/gates/….ts
// ---------------------------------------------------------------------------
const ROD_FILE = fileURLToPath(
  new URL('./__rods__/unregisteredIgnore.fixture.ts', import.meta.url),
);
const SRC_DIR = fileURLToPath(new URL('../', import.meta.url));
/** Absolute path to the gate's own source — used for the self-scan test. */
const GATE_SRC = fileURLToPath(new URL('./suppressionRegistry.ts', import.meta.url));

// ---------------------------------------------------------------------------
// 1. findSuppressions — finds @ts-ignore in the rod file (explicit path)
// ---------------------------------------------------------------------------
describe('findSuppressions — rod file scan', () => {
  it('finds the @ts-ignore directive in the fixture', () => {
    const suppressions = findSuppressions([ROD_FILE]);

    expect(suppressions.length).toBeGreaterThanOrEqual(1);

    const match = suppressions.find(s => s.directive === '@ts-ignore');
    expect(match).toBeDefined();
    expect(match?.line).toBe(1);
    expect(match?.file).toContain('unregisteredIgnore.fixture.ts');
  });
});

// ---------------------------------------------------------------------------
// 2. suppressionRegistryGate — empty registry → gate fails, names file+line
// ---------------------------------------------------------------------------
describe('suppressionRegistryGate — empty registry', () => {
  it('returns ok:false with UNREGISTERED_SUPPRESSION naming file and line', async () => {
    const result = await suppressionRegistryGate({
      roots: [ROD_FILE],
      registry: join(tmpdir(), `kt6-nonexistent-${Date.now()}.json`),
    }).run();

    expect(result.gate).toBe('suppression-registry');
    expect(result.ok).toBe(false);
    expect(result.problems.length).toBeGreaterThanOrEqual(1);

    const problem = result.problems.find(p => p.startsWith('UNREGISTERED_SUPPRESSION'));
    expect(problem).toBeDefined();
    expect(problem).toContain('unregisteredIgnore.fixture.ts');
    expect(problem).toContain(':1 ');
    expect(problem).toContain('@ts-ignore');
  });
});

// ---------------------------------------------------------------------------
// 3. suppressionRegistryGate — registered entry → gate passes
// ---------------------------------------------------------------------------
describe('suppressionRegistryGate — registered suppression', () => {
  it('returns ok:true when the fixture suppression is in the registry', async () => {
    // Run the gate once to discover the exact file key that the gate will emit.
    const discovered = findSuppressions([ROD_FILE]);
    const tsIgnore = discovered.find(s => s.directive === '@ts-ignore');
    expect(tsIgnore).toBeDefined();

    const entry: RegistryEntry = {
      file: tsIgnore!.file,
      line: tsIgnore!.line,
      directive: '@ts-ignore',
      reason: 'KT6 control-rod: deliberate type mismatch',
      blessedBy: 'kt6-test',
    };

    const tmpRegistry = join(tmpdir(), `kt6-registry-${Date.now()}.json`);
    writeFileSync(tmpRegistry, JSON.stringify([entry]), 'utf8');

    try {
      const result = await suppressionRegistryGate({
        roots: [ROD_FILE],
        registry: tmpRegistry,
      }).run();

      expect(result.gate).toBe('suppression-registry');
      expect(result.ok).toBe(true);
      expect(result.problems).toHaveLength(0);
    } finally {
      unlinkSync(tmpRegistry);
    }
  });
});

// ---------------------------------------------------------------------------
// 4. findSuppressions — recursive walk of src/ excludes __rods__
// ---------------------------------------------------------------------------
describe('findSuppressions — __rods__ excluded from recursive walk', () => {
  it('does not surface the rod fixture when walking src/', () => {
    const suppressions = findSuppressions([SRC_DIR]);

    // Verify the rod file path is absent from all results.
    const rodHit = suppressions.find(s =>
      s.file.includes('unregisteredIgnore.fixture'),
    );
    expect(rodHit).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// 5. findSuppressions — self-scan: gate source must return zero suppressions
//    (DIRECTIVE_PATTERNS has the words as string/regex literals, not comments)
// ---------------------------------------------------------------------------
describe('findSuppressions — self-scan of gate source', () => {
  it('returns zero suppressions when scanning suppressionRegistry.ts itself', () => {
    const suppressions = findSuppressions([GATE_SRC]);
    expect(suppressions).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// 6. findSuppressions — comment anchoring: string literal vs line comment
// ---------------------------------------------------------------------------
describe('findSuppressions — comment anchoring', () => {
  it('ignores directive words in string literals and detects them in // comments', () => {
    const tmpFile = join(tmpdir(), `kt6-anchor-${Date.now()}.ts`);
    // Line 1: directive word only in a string literal — must NOT be detected.
    // Line 2: directive in a // line comment — MUST be detected.
    writeFileSync(tmpFile, "const x = '@ts-ignore';\n// @ts-ignore\n", 'utf8');
    try {
      const found = findSuppressions([tmpFile]);
      const hits = found.filter(s => s.directive === '@ts-ignore');
      expect(hits).toHaveLength(1);
      expect(hits[0]?.line).toBe(2);
    } finally {
      unlinkSync(tmpFile);
    }
  });
});
