import { readFile, mkdir, writeFile, copyFile } from 'node:fs/promises';
const root = new URL('../', import.meta.url);
const read = name => readFile(new URL(name, root), 'utf8');
const assets = {};
for (const [route,file,mime] of [['/','index.html','text/html; charset=utf-8'],['/app.js','app.js','text/javascript; charset=utf-8'],['/style.css','style.css','text/css; charset=utf-8']]) {
  assets[route] = {body:await read('public/'+file),mime};
}
const modules = await Promise.all(['worker/contract.js','worker/core.js','worker/index.js'].map(read));
const bundle = modules.map(s=>s.replace(/^import .*;\r?\n/gm,'')).join('\n')+'\nconst ASSETS = '+JSON.stringify(assets)+';\nexport default createWorker(ASSETS);\n';
await mkdir(new URL('dist/server/',root),{recursive:true});
await mkdir(new URL('dist/.openai/',root),{recursive:true});
await writeFile(new URL('dist/server/index.js',root),bundle);
await copyFile(new URL('.openai/hosting.json',root),new URL('dist/.openai/hosting.json',root));
console.log('Built Sourcebook Worker with embedded assets. No client secrets.');
