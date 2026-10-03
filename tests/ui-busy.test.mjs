import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

// Exercise the actual app scripts without a browser, network or DOM dependency.
// Optional SOURCEBOOK_UI_TEST_SOURCE selects one file for a before/after replay.
const sources=process.env.SOURCEBOOK_UI_TEST_SOURCE
 ? [pathToFileURL(resolve(process.env.SOURCEBOOK_UI_TEST_SOURCE))]
 : [new URL('../static/app.js',import.meta.url),new URL('../deployment/site/public/app.js',import.meta.url)];

function node(tag='div'){
 return {tag,children:[],attributes:{},value:'',files:[],disabled:false,hidden:false,textContent:'',className:'',
  append(...items){this.children.push(...items);},
  replaceChildren(...items){this.children=[...items];},
  setAttribute(name,value){this.attributes[name]=value;},
  reset(){this.resets=(this.resets??0)+1;},
  classList:{toggle(){}},focus(){},scrollIntoView(){}};
}
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
async function loadApp(source){
 const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,node());return elements.get(id);};
 const blocked=['doc-name','doc-text','add-submit','files','example'];
 const requests=[];
 const example={mode:'example',documents:[{id:'D1',name:'Example.txt',text:'Authored example text.'}],actions:[],rejected:0};
 const document={getElementById:get,createElement:node,querySelectorAll:()=>blocked.map(get)};
 const context=vm.createContext({document,console,structuredClone,setTimeout,clearTimeout,
  fetch:async(path,options)=>{
   requests.push({path,body:options?.body?JSON.parse(options.body):null});
   const data=path==='/api/status'?{configured:true,csrf:'test-only',model:'fixture-model'}
    :path==='/api/example'?example
    :path==='/api/analyze'?{mode:'nebius',documents:JSON.parse(options.body).documents,actions:[],rejected:0}
    :null;
   assert.ok(data,'Unexpected request in local test: '+path);
   return {ok:true,json:async()=>structuredClone(data)};
  }});
 vm.runInContext(await readFile(source,'utf8'),context,{filename:source.pathname});
 await new Promise(setImmediate);
 assert.deepEqual(requests.map(r=>r.path),['/api/status']);
 const submit=(name='Existing.txt',text='Existing synthetic document.')=>{
  get('doc-name').value=name;get('doc-text').value=text;
  let prevented=false;get('add-form').onsubmit({preventDefault(){prevented=true;}});assert.ok(prevented);
 };
 submit();assert.equal(get('doc-count').textContent,'1 / 10');
 return {get,requests,submit,blocked};
}
async function assertLocked(app){
 const {get,requests,submit}=app;
 let secondRead=0;
 get('files').files=[{name:'Ignored.txt',size:20,text:()=>{secondRead++;return Promise.resolve('Ignored synthetic text.');}}];
 submit('Ignored form.txt','This form must not be added.');
 await get('example').onclick();await get('analyze').onclick();await get('files').onchange();
 assert.deepEqual(requests.map(r=>r.path),['/api/status'],'No example or model request may start while File.text is pending');
 assert.equal(secondRead,0,'A second file event must not start another read');
 assert.equal(get('doc-count').textContent,'1 / 10','The form must not add documents while reading');
 assert.equal(get('workspace').attributes['aria-busy'],'true');
 for(const id of [...app.blocked,'analyze'])assert.equal(get(id).disabled,true,id+' must be disabled');
}
async function assertReleased(app,expectedCount){
 const {get,requests,submit}=app;
 assert.equal(get('workspace').attributes['aria-busy'],'false');
 for(const id of [...app.blocked,'analyze'])assert.equal(get(id).disabled,false,id+' must be enabled');
 assert.equal(get('files').value,'');
 assert.equal(get('doc-count').textContent,`${expectedCount} / 10`);
 submit('After read.txt','Form submission works after the read.');
 assert.equal(get('doc-count').textContent,`${expectedCount+1} / 10`);
 await get('analyze').onclick();
 assert.equal(requests.at(-1).path,'/api/analyze');assert.equal(requests.at(-1).body.documents.length,expectedCount+1);
 await get('example').onclick();assert.equal(requests.at(-1).path,'/api/example');
 assert.equal(get('workspace').attributes['aria-busy'],'false');
}

for(const source of sources){
 const label=source.pathname.includes('/deployment/')?'Sites UI':'Python UI';
 for(const outcome of ['success','error'])test(`${label}: pending file blocks other actions and releases on ${outcome}`,async t=>{
  const app=await loadApp(source),pending=deferred();
  // Resolve even if an assertion fails, so baseline replay leaves no pending read.
  t.after(()=>pending.resolve('Cleanup synthetic text.'));
  app.get('files').files=[{name:'Pending.txt',size:32,text:()=>pending.promise}];
  app.get('files').value='pending-selection';
  const reading=app.get('files').onchange();
  await assertLocked(app);
  if(outcome==='success')pending.resolve('Document read completed successfully.');
  else pending.reject(new Error('Synthetic file read failure'));
  await reading;
  if(outcome==='error')assert.match(app.get('message').textContent,/Synthetic file read failure/);
  await assertReleased(app,outcome==='success'?2:1);
 });
}
