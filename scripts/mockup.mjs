import { spawnSync } from 'node:child_process';
import { resolve, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const usage = 'Usage: npm run mockup [-- --windows]\nOpens sample controls only; Spotify and installed helper settings are not accessed.';

export function selectTarget(args, platform) {
  if (args.length === 1 && args[0] === '--help') return 'help';
  if (args.length === 1 && args[0] === '--windows') return 'windows';
  if (args.length) throw new Error(usage);
  return platform === 'darwin' ? 'macos' : 'windows';
}

function run(command, args) {
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit' });
  if (result.error) throw new Error(`Could not run ${command}: ${result.error.message}`);
  if (result.status !== 0) process.exit(result.status ?? 1);
}

function launchWindowsMockup() {
  const candidates = process.platform === 'win32'
    ? [[join(root, 'windows/.venv/Scripts/python.exe'), []], ['py', ['-3']], ['python', []]]
    : [[join(root, 'windows/.venv/bin/python'), []], ['python3', []], ['python3.12', []], ['python', []]];
  for (const [python, prefix] of candidates) {
    const check = spawnSync(python, [...prefix, '-c', 'import sys; assert sys.version_info >= (3, 10); import tkinter'], { encoding: 'utf8' });
    if (check.status === 0) {
      run(python, [...prefix, join(root, 'windows/mockup.py')]);
      return;
    }
  }
  throw new Error('The Windows UI mockup needs Python 3.10+ with Tk. Install a standard Python distribution with Tk support.');
}

function main() {
  try {
    const target = selectTarget(process.argv.slice(2), process.platform);
    if (target === 'help') {
      console.log(usage);
      return;
    }
    console.log(`Opening ${target === 'macos' ? 'macOS' : 'Windows'} UI mockup. All playback and settings are simulated.`);
    if (target === 'macos') {
      run('bash', [join(root, 'macos/Build Spotify Control.command')]);
      run(join(root, 'macos/build/Spotify Control.app/Contents/MacOS/SpotifyControl'), ['--mockup']);
    } else {
      launchWindowsMockup();
    }
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) main();
