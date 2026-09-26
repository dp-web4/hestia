#!/usr/bin/env node
// Fail if the dashboard's inline JavaScript references an identifier nothing declares.
//
// Why this exists (2026-09-25): two such references shipped, and no check could see either.
// `node --check` parses; an undeclared name is a RUNTIME ReferenceError, raised only when that
// line runs.
//   - `hidden` in renderRoleTrust (#1113 moved a trailer out of the function that declares
//     it). Selecting ANY agent threw out of the tick, the header read "offline (hidden is not
//     defined)", and the witness chain stayed on "All". dp hit it live.
//   - `modal` in the Escape handler (512d7c2, 2026-07-26). No such element or variable
//     exists, so Escape threw before it could close the trust-detail modal. Two months unseen.
//
// Usage (CI installs the two packages into a throwaway directory):
//   npm install --prefix <dir> eslint@10 globals
//   NODE_PATH=<dir>/node_modules node tools/dashboard_no_undef.mjs
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { Linter } = require('eslint');
const globals = require('globals');

const FILE = 'core/src/server/dashboard/index.html';
const html = readFileSync(FILE, 'utf8');

// Every inline (non-src) <script>, remembering the line each body starts on so a finding
// names the line in index.html rather than in an extracted blob.
const re = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g;
const linter = new Linter({ configType: 'flat' });
const config = [{
  languageOptions: { ecmaVersion: 'latest', sourceType: 'script', globals: { ...globals.browser } },
  rules: { 'no-undef': 'error' },
}];

let blocks = 0;
const problems = [];
for (let m; (m = re.exec(html)); ) {
  blocks += 1;
  const startLine = html.slice(0, m.index + m[0].indexOf('>') + 1).split('\n').length;
  for (const msg of linter.verify(m[1], config)) {
    problems.push(`${FILE}:${startLine + msg.line - 1}:${msg.column}  ${msg.message} (${msg.ruleId ?? 'parse'})`);
  }
}

if (blocks === 0) {
  console.error(`no inline <script> found in ${FILE}; the layout moved and this check is blind`);
  process.exit(1);
}
if (problems.length) {
  console.error(problems.join('\n'));
  console.error(`dashboard no-undef: ${problems.length} problem(s)`);
  process.exit(1);
}
console.log(`dashboard no-undef: clean (${blocks} inline script block(s))`);
