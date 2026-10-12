// Dependency-free execution of the production hook's refresh callback. This is a
// state-transition probe, not a React rendering or desktop end-to-end test.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../app/src/hooks/useDashboard.ts'), 'utf8')
  .replace(/^import .*;\n/gm, '')
  .replace('export function useDashboard', 'function useDashboard')
  .replace(/useState<[^>]+>/g, 'useState');
let states = [], next = 0;
let recovered = false;
const sandbox = {
  useState(initial) { const i = next++; states[i] = initial; return [initial, x => states[i] = x]; },
  useEffect() {}, useCallback(fn) { return fn; },
  getDashboard: async () => { if (!recovered) throw Error('incompatible daemon'); return {recovered: true}; },
  getDaemonStatus: async () => ({online: true, signed_in: true, handshake: {state: recovered ? 'compatible' : 'incompatible'}}),
};
vm.createContext(sandbox);
vm.runInContext(source + '\nthis.hook = useDashboard();', sandbox);
(async () => {
  await sandbox.hook.refresh();
  if (states[4]?.state !== 'incompatible') throw Error('failed setup control');
  recovered = true;
  await sandbox.hook.refresh();
  console.log(JSON.stringify({data: states[0], online: states[1], error: states[3], handshake: states[4]}));
  if (states[4]?.state === 'incompatible') {
    console.error('FAIL: successful refresh leaves the blocking handshake unchanged');
    process.exitCode = 1;
  }
})();
