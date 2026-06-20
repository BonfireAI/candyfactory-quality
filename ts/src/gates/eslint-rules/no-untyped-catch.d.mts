import type { Rule } from 'eslint';

// The rule is authored as plain ESM JS (.mjs); this declaration gives the
// .ts test (and any TS consumer) a typed default export instead of implicit any.
declare const rule: Rule.RuleModule;
export default rule;
