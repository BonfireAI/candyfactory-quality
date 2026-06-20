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
    tsConfig: { fileName: 'tsconfig.json' },
  },
};
