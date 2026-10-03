import { MAX_BODY, MAX_MODEL_BYTES, MAX_ACTIONS, DEFAULT_MODEL, DEFAULT_BASE, SYSTEM_PROMPT } from './contract.js';

export class Problem extends Error {
  constructor(message,status=400){super(message);this.status=status;}
}
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
// Python counts Unicode code points; JavaScript's string.length counts UTF-16 units.
const chars = value => [...value].length;
export function documentsFrom(value){
  if(!Array.isArray(value)||value.length<1||value.length>10)throw new Problem('Add between 1 and 10 documents.');
  let total=0;
  return value.map((item,index)=>{
    if(!object(item))throw new Problem('Each document needs a name and text.');
    const {name}=item;let {text}=item;
    if(typeof name!=='string'||!name.trim()||chars(name)>120)throw new Problem('Document names must be 1–120 characters.');
    if(typeof text!=='string'||!text.trim())throw new Problem('Every document must contain text.');
    text=text.replace(/\r\n?/g,'\n');total+=chars(text);
    if(total>80000)throw new Problem('Documents exceed the 80,000-character limit.',413);
    return {id:`D${index+1}`,name:name.trim(),text};
  });
}
export function validateActions(payload,documents){
  if(!object(payload)||!Array.isArray(payload.actions))throw new Problem('The model did not return an actions array. Retry the review.',502);
  const lookup=new Map(documents.map(d=>[d.id,d]));const accepted=[];let rejected=0;
  for(const item of payload.actions.slice(0,MAX_ACTIONS)){
    if(!object(item)){rejected++;continue;}
    const {task,evidence}=item;
    if(typeof task!=='string'||!task.trim()||chars(task)>400||!Array.isArray(evidence)||evidence.length<1||evidence.length>5){rejected++;continue;}
    const checked=[];
    for(const cite of evidence){
      if(!object(cite)||typeof cite.document_id!=='string')break;
      const doc=lookup.get(cite.document_id),{line,quote}=cite;
      if(!doc||!Number.isSafeInteger(line)||typeof quote!=='string'||!quote.trim()||chars(quote)<8||chars(quote)>2000)break;
      const lines=doc.text.split('\n');
      if(line<1||line>lines.length||!lines[line-1].includes(quote))break;
      checked.push({document_id:doc.id,name:doc.name,line,quote});
    }
    if(checked.length!==evidence.length){rejected++;continue;}
    const quotes=checked.map(c=>c.quote).join('\n');
    const grounded=field=>typeof item[field]==='string'&&item[field].trim()&&chars(item[field])<=100&&quotes.includes(item[field])?item[field]:null;
    accepted.push({id:`A${accepted.length+1}`,task:task.trim(),owner:grounded('owner'),due:grounded('due'),evidence:checked});
  }
  return [accepted,rejected+Math.max(0,payload.actions.length-MAX_ACTIONS)];
}
export function validateProviderConfig(key,model,base){
  let url;try{url=new URL(base);}catch{}
  if(typeof base!=='string'||!url||url.protocol!=='https:'||!url.hostname.endsWith('.nebius.com')||url.port||url.username||url.password||url.search||url.hash)throw new Problem('NEBIUS_BASE_URL must be an HTTPS endpoint on a nebius.com subdomain.',503);
  if(typeof key!=='string'||!key.trim()||/[\r\n]/.test(key))throw new Problem('A valid NEBIUS_API_KEY must be configured in the server environment.',503);
  if(typeof model!=='string'||!model.toLowerCase().startsWith('nvidia/'))throw new Problem('Select an NVIDIA model in NEBIUS_MODEL for this hackathon build.',503);
}
export async function readBounded(stream,limit,message,status){
  if(!stream)return new Uint8Array();const reader=stream.getReader();const chunks=[];let total=0;
  try{while(true){const {done,value}=await reader.read();if(done)break;total+=value.byteLength;if(total>limit){await reader.cancel();throw new Problem(message,status);}chunks.push(value);}}
  finally{reader.releaseLock();}
  const all=new Uint8Array(total);let offset=0;for(const value of chunks){all.set(value,offset);offset+=value.length;}return all;
}
export async function requestModel(documents,key,model=DEFAULT_MODEL,base=DEFAULT_BASE,transport=fetch){
  validateProviderConfig(key,model,base);
  const numbered=documents.map(d=>({id:d.id,name:d.name,lines:d.text.split('\n').map((text,i)=>({line:i+1,text}))}));
  const data={model,temperature:0,max_tokens:5000,response_format:{type:'json_object'},messages:[{role:'system',content:SYSTEM_PROMPT},{role:'user',content:JSON.stringify({documents:numbered})}]};
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),90000);
  try{
    const response=await transport(base.replace(/\/+$/,'')+'/chat/completions',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+key},body:JSON.stringify(data),redirect:'manual',signal:controller.signal});
    if(!response.ok){await response.body?.cancel();throw new Problem(`Nebius returned HTTP ${response.status}. Check your key, model access or quota, then retry.`,502);}
    const bytes=await readBounded(response.body,MAX_MODEL_BYTES,'Nebius returned an oversized response. Use fewer documents and retry.',502);
    const raw=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
    if(!object(raw)||!Array.isArray(raw.choices)||raw.choices.length===0)throw new Error('Invalid response shape');
    const choice=raw.choices[0];
    if(choice?.finish_reason==='length')throw new Problem('The model reached its output limit. Use fewer documents and retry.',502);
    if(typeof choice?.message?.content!=='string')throw new Error('Invalid response shape');
    const usage={};if(object(raw.usage))for(const name of ['prompt_tokens','completion_tokens','total_tokens'])if(Number.isSafeInteger(raw.usage[name])&&raw.usage[name]>=0)usage[name]=raw.usage[name];
    return [JSON.parse(choice.message.content),usage];
  }catch(error){
    if(error instanceof Problem)throw error;
    if(controller.signal.aborted||error instanceof TypeError)throw new Problem('Nebius could not be reached. Your documents remain in this browser; retry when connected.',502);
    throw new Problem('Nebius returned a response this app could not validate. Try a smaller input.',502);
  }finally{clearTimeout(timer);}
}
