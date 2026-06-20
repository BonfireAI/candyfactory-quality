/**
 * Control-rod contract for import-contract gate tests.
 *
 * Same forbidden rules as the kit's real .dependency-cruiser.cjs but WITHOUT
 * the `exclude: { path: '__rods__' }` option so that test #1 can cruise this
 * directory and prove CONTRACT_BROKEN is detected for the core→adapters edge.
 *
 * tsConfig.fileName is relative to THIS file's directory; the gate resolves it
 * absolute before passing to cruise:
 *   ts/src/gates/__rods__/upwardImport/  +  ../../../../tsconfig.json
 *   → ts/tsconfig.json  ✓
 */
/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  forbidden: [
    { name: 'no-circular', severity: 'error', from: {}, to: { circular: true } },
    {
      name: 'core-not-to-adapters',
      severity: 'error',
      comment: 'core must not import adapters/packs/tenants (DIP)',
      from: { path: '(^|/)core/' },
      to: { path: '(^|/)(adapters|packs|tenants)/' },
    },
  ],
  options: {
    doNotFollow: { path: 'node_modules' },
    tsConfig: { fileName: '../../../../tsconfig.json' },
  },
};
