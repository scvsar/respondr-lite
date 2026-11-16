import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

// Keep the test flags used by repository scripts and deployment workflows.
const args = process.argv.slice(2).flatMap(argument => {
  if (argument === '--ci' || argument === '--watchAll=false') return [];
  if (argument === '--runInBand') return ['--maxWorkers=1'];
  if (argument === '--watchAll' || argument === '--watchAll=true') return ['--watch'];
  return [argument];
});
const runner = fileURLToPath(new URL('./vitest.mjs', import.meta.resolve('vitest/package.json')));
const result = spawnSync(process.execPath, [runner, ...(args.includes('--watch') ? [] : ['run']), ...args], {stdio:'inherit'});
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
