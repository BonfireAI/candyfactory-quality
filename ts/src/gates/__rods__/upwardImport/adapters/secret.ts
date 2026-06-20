/**
 * Control-rod target: an adapter module that core must not import.
 *
 * Exists solely to give the DIP-violation rod (core/badImporter.ts) a real
 * cross-layer import target.  No production logic here.
 */
export const SECRET = 'adapter-secret';
