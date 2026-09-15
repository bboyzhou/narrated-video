import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';
import {validatePlan} from '../src/validate.mjs';
import {createHash} from 'node:crypto';

const value = (name) => {
  const i = process.argv.indexOf(name);
  if (i < 0 || !process.argv[i + 1]) throw new Error(`Missing ${name}`);
  return process.argv[i + 1];
};

const planPath = path.resolve(value('--plan'));
const validateOnly=process.argv.includes('--validate-only');
const output = validateOnly ? null : path.resolve(value('--output'));
const plan = JSON.parse(await fs.readFile(planPath, 'utf8'));
const report = validatePlan(plan);
await fs.writeFile(planPath.replace(/\.json$/, '') + '-qa.json', JSON.stringify(report,null,2));
if(report.status !== 'passed')throw new Error('Render plan QA failed: '+report.errors.join('; '));
if(validateOnly)process.exit(0);
if (!plan.browser_executable) {
  throw new Error('No browser executable configured; set runtime.browser to an existing Chrome/Edge path');
}
const root = path.resolve(fileURLToPath(new URL('../', import.meta.url)));
const entry = path.join(root, 'src', 'index.tsx');
const hash=createHash('sha256');
for(const dir of ['src','scripts'])for(const name of (await fs.readdir(path.join(root,dir))).sort())hash.update(await fs.readFile(path.join(root,dir,name)));
hash.update(await fs.readFile(path.join(root,'package-lock.json')));
for(const name of (await fs.readdir(plan.asset_root)).sort()){hash.update(name);hash.update(await fs.readFile(path.join(plan.asset_root,name)));}
const bundleDir=path.join(root,'.bundle-cache',hash.digest('hex'));
let serveUrl=bundleDir;
try{await fs.access(path.join(bundleDir,'.complete'));}
catch{serveUrl=await bundle({entryPoint:entry,rootDir:root,publicDir:plan.asset_root,outDir:bundleDir});await fs.writeFile(path.join(bundleDir,'.complete'),'ok');}
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
