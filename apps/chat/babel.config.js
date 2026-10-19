/**
 * Exists for ONE reason: jest must be able to load `nostr-tools`.
 *
 * nostr-tools 2.25 pins `@noble/curves` / `@noble/hashes` / `@scure/*` to versions that ship
 * ESM ONLY (`"type": "module"`, no CJS build) and pins them EXACTLY, so they cannot be overridden
 * down to a CJS release without forking the dependency.
 *
 * Node 22 runs them fine — `require()` of an ES module is supported, and the service does exactly
 * that in production (chatapi/relay/identity.js). Jest is the only thing that cannot: it runs the
 * suite as CommonJS and, by default, refuses to transform anything under node_modules, so the first
 * `import` statement inside @noble is a SyntaxError. That failed four suites at LOAD time while
 * every assertion in them was still correct.
 *
 * So: transform those packages, and only those. `transformIgnorePatterns` in package.json carries
 * the matching allowlist — the two halves belong together and neither works alone.
 */
module.exports = {
  presets: [['@babel/preset-env', { targets: { node: 'current' } }]],
};
