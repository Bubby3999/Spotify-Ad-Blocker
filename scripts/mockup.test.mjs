import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { selectTarget } from './mockup.mjs';

test('default preview matches the platform and Windows can be inspected on Mac', () => {
  assert.equal(selectTarget([], 'darwin'), 'macos');
  assert.equal(selectTarget([], 'win32'), 'windows');
  assert.equal(selectTarget(['--windows'], 'darwin'), 'windows');
});

test('unsupported arguments cannot reach a live application or build command', () => {
  assert.throws(() => selectTarget(['--live'], 'darwin'), /Usage/);
  assert.throws(() => selectTarget(['--windows', '--live'], 'win32'), /Usage/);
});

test('help and invalid arguments work from another directory without opening a UI', () => {
  const script = fileURLToPath(new URL('./mockup.mjs', import.meta.url));
  const help = spawnSync(process.execPath, [script, '--help'], { cwd: tmpdir(), encoding: 'utf8', timeout: 5000 });
  assert.equal(help.status, 0, help.stderr);
  assert.match(help.stdout, /sample controls only/);
  const invalid = spawnSync(process.execPath, [script, '--live'], { encoding: 'utf8', timeout: 5000 });
  assert.equal(invalid.status, 1);
  assert.match(invalid.stderr, /Usage/);
});
