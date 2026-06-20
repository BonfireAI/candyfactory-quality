/**
 * ESLint flat-config rule: local/no-untyped-catch
 *
 * Enforces the Elegance Law's fail-fast pillar: every catch block must
 * contain at least one ThrowStatement or ReturnStatement (at any nesting
 * depth).  An empty catch, or one that only logs/swallows the error,
 * is reported as a problem.
 *
 * Heuristic (intentionally simple):
 *   PASS — the catch body contains a ThrowStatement OR a ReturnStatement
 *          anywhere in its AST subtree.
 *   FAIL — no ThrowStatement and no ReturnStatement found → `swallowed`.
 *
 * This rule file is plain JS (.mjs) so it can be imported by the flat-config
 * without transpilation.  The rule itself is under CC ≤ 10, ≤ 50 statements.
 */

// ---------------------------------------------------------------------------
// AST helpers
// ---------------------------------------------------------------------------

/**
 * Keys on ESLint AST nodes that must NOT be traversed (parent pointers,
 * source-location metadata) to avoid infinite recursion.
 */
const SKIP_KEYS = new Set(['parent', 'range', 'loc', 'start', 'end', 'tokens', 'comments']);

/**
 * AST node types that introduce a new function scope.  `hasThrowOrReturn`
 * must not descend into these: a throw/return inside a nested function does
 * NOT handle the surrounding catch block.
 */
const FUNCTION_NODES = new Set([
  'FunctionExpression',
  'ArrowFunctionExpression',
  'FunctionDeclaration',
]);

/**
 * Return true when `val` looks like an ESLint AST node (plain object with a
 * string `.type`).  Rejects arrays, primitives, and null.
 *
 * @param {unknown} val
 * @returns {val is import('estree').Node}
 */
function isNode(val) {
  return (
    val !== null &&
    typeof val === 'object' &&
    !Array.isArray(val) &&
    typeof /** @type {Record<string, unknown>} */ (val)['type'] === 'string'
  );
}

/**
 * Check whether any element of `arr` is an AST node that contains a
 * ThrowStatement or ReturnStatement.
 *
 * Extracted from `hasThrowOrReturn` to keep each function under CC 10.
 *
 * @param {unknown[]} arr
 * @returns {boolean}
 */
function arrayHasThrowOrReturn(arr) {
  for (const item of arr) {
    if (isNode(item) && hasThrowOrReturn(/** @type {import('estree').Node} */ (item))) {
      return true;
    }
  }
  return false;
}

/**
 * Recursively walk an AST node and return true if it is, or contains, a
 * ThrowStatement or ReturnStatement.
 *
 * Skips keys in SKIP_KEYS to prevent infinite cycles through `parent`.
 *
 * CC budget: 9 (well within the ≤ 10 limit).
 *
 * @param {import('estree').Node} node
 * @returns {boolean}
 */
function hasThrowOrReturn(node) {
  if (node.type === 'ThrowStatement' || node.type === 'ReturnStatement') return true;
  if (FUNCTION_NODES.has(node.type)) return false; // do not descend into nested function scopes
  for (const [key, val] of Object.entries(node)) {
    if (SKIP_KEYS.has(key)) continue;
    if (Array.isArray(val) && arrayHasThrowOrReturn(val)) return true;
    if (isNode(val) && hasThrowOrReturn(/** @type {import('estree').Node} */ (val))) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Rule definition
// ---------------------------------------------------------------------------

/** @type {import('eslint').Rule.RuleModule} */
const rule = {
  meta: {
    type: 'problem',
    docs: {
      description:
        'Catch blocks must rethrow or return a typed failure; swallowing errors ' +
        'violates the Elegance Law (fail-fast pillar).',
      url: 'https://github.com/BonfireAI/bonfire/blob/main/design/%2Badr/ADR-0030-bubblegum-law.md',
    },
    messages: {
      swallowed:
        'A catch block must rethrow or throw a typed error; do not swallow failures (Elegance Law).',
    },
    schema: [],
  },

  /**
   * @param {import('eslint').Rule.RuleContext} context
   * @returns {import('eslint').Rule.RuleListener}
   */
  create(context) {
    return {
      CatchClause(node) {
        if (!hasThrowOrReturn(node.body)) {
          context.report({ node, messageId: 'swallowed' });
        }
      },
    };
  },
};

export default rule;
