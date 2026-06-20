// Rod fixture: intentional type error for tscStrictGate test.
// This file is in __rods__ and excluded from production gate runs.
const x: string = 42; // TS2322: Type 'number' is not assignable to type 'string'.
export { x };
