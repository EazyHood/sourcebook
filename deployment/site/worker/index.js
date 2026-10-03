import { MAX_BODY, DEFAULT_MODEL, DEFAULT_BASE, EXAMPLE_DOCS, EXAMPLE_ACTIONS } from './contract.js';
import { Problem, documentsFrom, validateActions, validateProviderConfig, readBounded, requestModel } from './core.js';

export const BUDGET_SQL = `INSERT INTO inference_budget (day, attempts) VALUES (?, 1)
ON CONFLICT(day) DO UPDATE SET attempts = attempts + 1 WHERE attempts < ?
RETURNING attempts`;
export function liveConfig(env,origin){
  const model=env.NEBIUS_MODEL||DEFAULT_MODEL,base=env.NEBIUS_BASE_URL||DEFAULT_BASE;
  const limit=typeof env.SOURCEBOOK_DAILY_LIMIT==='string'&&/^\d+$/.test(env.SOURCEBOOK_DAILY_LIMIT)?Number(env.SOURCEBOOK_DAILY_LIMIT):0;
  const enabled=env.SOURCEBOOK_ALLOW_LIVE==='true'&&Number.isSafeInteger(limit)&&limit>=1&&limit<=20&&env.SOURCEBOOK_PUBLIC_ORIGIN===origin&&typeof env.DB?.prepare==='function';
  let valid=false;try{validateProviderConfig(env.NEBIUS_API_KEY,model,base);valid=true;}catch{}
  return {enabled:enabled&&valid,model,base,limit};
}
export async function reserveBudget(db,limit,day){
  try{
    const row=await db.prepare(BUDGET_SQL).bind(day,limit).first();
    if(!row)throw new Problem('The daily demo review limit has been reached. The worked example remains available.',429);
    if(!Number.isSafeInteger(row.attempts)||row.attempts<1||row.attempts>limit)throw new Error('Invalid counter');
  }catch(error){
    if(error instanceof Problem)throw error;
    throw new Problem('Live reviews are unavailable because the usage limit could not be verified. Use the worked example.',503);
  }
}
const cookieToken=request=>request.headers.get('Cookie')?.split(';').map(s=>s.trim()).find(s=>s.startsWith('__Host-sourcebook_csrf='))?.split('=')[1];
function reply(value,status=200,type='application/json; charset=utf-8',extra={}){
  return new Response(typeof value==='string'?value:JSON.stringify(value),{status,headers:{
    'Content-Type':type,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
    'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    'Referrer-Policy':'no-referrer',...extra,
  }});
}
export function createWorker(assets={},modelCall=requestModel){
  return {async fetch(request,env={},ctx={}){
    void ctx;
    try{
      const url=new URL(request.url),path=url.pathname;
      if(request.method==='GET'){
        if(path==='/api/status'){
          const config=liveConfig(env,url.origin);
          const token=Array.from(crypto.getRandomValues(new Uint8Array(32)),n=>n.toString(16).padStart(2,'0')).join('');
          return reply({configured:config.enabled,model:config.model,provider:'Nebius Token Factory',csrf:token,storage:'documents in memory only',mode:config.enabled?'nebius':'example',notice:config.enabled?'A daily review limit applies.':'Live reviews are disabled. Open the worked example to explore the app.'},200,undefined,{'Set-Cookie':`__Host-sourcebook_csrf=${token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=3600`});
        }
        if(path==='/api/example'){
          const documents=documentsFrom(EXAMPLE_DOCS),[actions,rejected]=validateActions(EXAMPLE_ACTIONS,documents);
          return reply({mode:'example',documents,actions,rejected,model:'No model called — hand-authored example',created_at:new Date().toISOString(),usage:{}});
        }
        if(Object.hasOwn(assets,path))return reply(assets[path].body,200,assets[path].mime);
        return reply({error:'Not found'},404);
      }
      if(request.method!=='POST')return reply({error:'Method not allowed'},405,undefined,{Allow:'GET, POST'});
      const token=request.headers.get('X-CSRF-Token'),cookie=cookieToken(request);
      if(!token||!/^[a-f0-9]{64}$/.test(token)||cookie!==token)throw new Problem('Reload this page before submitting.',403);
      if(request.headers.get('Origin')!==url.origin||request.headers.get('Sec-Fetch-Site')==='cross-site')throw new Problem('Cross-origin requests are not allowed.',403);
      if(path!=='/api/analyze'||url.search)throw new Problem('Not found',404);
      const rawLength=request.headers.get('Content-Length');
      if(rawLength!==null&&(!/^\d+$/.test(rawLength)||Number(rawLength)>MAX_BODY||Number(rawLength)===0))throw new Problem('Request is empty or too large.',413);
      if(request.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase()!=='application/json')throw new Problem('Send JSON.',415);
      const bytes=await readBounded(request.body,MAX_BODY,'Request is empty or too large.',413);
      if(!bytes.length)throw new Problem('Request is empty or too large.',413);
      let payload;try{payload=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{throw new Problem('Malformed JSON request.',400);}
      const documents=documentsFrom(payload?.documents);
      const config=liveConfig(env,url.origin);
      if(!config.enabled)throw new Problem('Live reviews are disabled. Use the labelled worked example; no model will be called.',503);
      await reserveBudget(env.DB,config.limit,new Date().toISOString().slice(0,10));
      const [response,usage]=await modelCall(documents,env.NEBIUS_API_KEY,config.model,config.base);
      const [actions,rejected]=validateActions(response,documents);
      return reply({mode:'nebius',model:config.model,documents,actions,rejected,usage,created_at:new Date().toISOString()});
    }catch(error){
      if(error instanceof Problem)return reply({error:error.message},error.status);
      return reply({error:'The review could not be completed. Your browser input is unchanged.'},500);
    }
  }};
}
