import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';

const value = (name) => {
  const i = process.argv.indexOf(name);
  if (i < 0 || !process.argv[i + 1]) throw new Error(`Missing ${name}`);
  return process.argv[i + 1];
};

const planPath = path.resolve(value('--plan'));
const output = path.resolve(value('--output'));
const plan = JSON.parse(await fs.readFile(planPath, 'utf8'));
if (!plan.browser_executable) {
  throw new Error('No browser executable configured; set runtime.browser to an existing Chrome/Edge path');
}
const root = path.resolve(fileURLToPath(new URL('../', import.meta.url)));
const entry = path.join(root, 'src', 'index.tsx');
const serveUrl = await bundle({entryPoint: entry, rootDir: root, publicDir: plan.asset_root});
const composition = await selectComposition({serveUrl, id: 'NarratedVideo', inputProps: plan, browserExecutable: plan.browser_executable});
await renderMedia({
  composition,
  serveUrl,
  codec: 'h264',
  outputLocation: output,
  inputProps: plan,
  muted: true,
  concurrency: 2,
  disallowParallelEncoding: true,
  imageFormat: 'jpeg',
  overwrite: true,
  logLevel: 'error',
  browserExecutable: plan.browser_executable,
});
