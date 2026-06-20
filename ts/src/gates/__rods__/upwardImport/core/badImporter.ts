/**
 * Control rod: a core file that illegally imports an adapter module.
 *
 * This intentional DIP violation triggers the `core-not-to-adapters` rule in
 * .dependency-cruiser.cjs so that the import-contract gate test can assert
 * CONTRACT_BROKEN is detected.  Never ship this path in real source.
 */
import { SECRET } from '../adapters/secret.js';

export const LEAKED_SECRET = SECRET;
