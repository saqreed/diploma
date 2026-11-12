// Additive live checks against the source lab. No resets, no secret output.
import fs from 'node:fs'
import path from 'node:path'
import assert from 'node:assert/strict'
import {fileURLToPath} from 'node:url'
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..')
const parse=file=>Object.fromEntries(fs.readFileSync(file,'utf8').split(/\r?\n/).filter(l=>l.includes('=')&&!l.startsWith('#')).map(l=>[l.slice(0,l.indexOf('=')),l.slice(l.indexOf('=')+1).replace(/^['"]|['"]$/g,'')]))
const env={...parse(path.join(root,'.env')),...parse(path.join(root,'.env.sources'))}
const base=process.env.DIPLOMA_TEST_URL||'http://127.0.0.1:8000'
let cookie=''
async function call(route,body,method=body?'POST':'GET',expected=200,headers={}){
 const response=await fetch(base+'/api'+route,{method,headers:{'Content-Type':'application/json','X-Requested-With':'antifraud-ui',Cookie:cookie,...headers},...(body?{body:JSON.stringify(body)}:{})})
 if(route==='/auth/login')cookie=response.headers.get('set-cookie').split(';')[0]
 const text=await response.text();for(const key of ['SOURCE_LAB_READER_PASSWORD','SOURCE_LAB_ADMIN_PASSWORD','DIPLOMA_READER_PASSWORD'])assert(!text.includes(env[key]),'secret returned')
 const result=JSON.parse(text);assert.equal(response.status,expected,route+': '+(result.message||response.status));return result
}
await call('/auth/login',{username:'admin',password:env.DIPLOMA_SEED_PASSWORD})
const discovery=await call('/admin/source-discovery')
assert.equal(discovery.sources.filter(s=>s.state==='available').length,3)
const report={at:new Date().toISOString(),discovery:discovery.sources.map(s=>({id:s.id,state:s.state})),engines:[]}
const prefix='qa-connectors-'+Date.now()
for(const [kind,host,port,table] of [['postgresql','source-pg','5432','public.operations'],['mysql','source-mysql','3306','lab.operations'],['mongodb','source-mongo','27017','operations']]){
 const id=prefix+'-'+kind
 const catalog={transfer:{statuses:['DONE','FAILED'],fields:{amount:{type:'number',source:'DB',required:true},recipient:{type:'string',source:'DB',required:true},active:{type:'boolean',source:'DB',required:true}}}}
 const application=await call('/admin/applications',{id,name:'Проверка '+kind,ttl_seconds:600,catalog})
 const connection={kind,host,port,database:'lab',user:'lab_reader',password:env.SOURCE_LAB_READER_PASSWORD}
 const access=await call('/admin/sources/'+id+'/inspect',{connection})
 assert.equal(access.resources[0].name,table)
 assert.equal(access.resources[0].fields.active.type,'boolean')
 const settings={connection,table_name:table,key_field:'id',allowed_fields:['amount','recipient','active'],mapping:{amount:'amount',recipient:'recipient',active:'active'},field_sources:{amount:'DB',recipient:'DB',active:'DB'},record_key:'1'}
 await call('/admin/sources/'+id+'/test',settings)
 await call('/admin/sources/'+id,settings,'PUT')
 const saved=await call('/admin/sources/'+id)
 await call('/admin/sources/'+id+'/inspect',{connection:{...connection,password:''}})
 await call('/admin/rules',{application_id:id,name:'Сумма и активная операция',action:'transfer',reaction:'REVIEW',expression:{kind:'all',children:[{kind:'field',field:'amount',op:'ge',value:'10000.12'},{kind:'field',field:'active',op:'eq',value:true}]}})
 const payload={application_id:id,operation_id:crypto.randomUUID(),action:'transfer',initiator:'lab-actor',record_key:'1',fields:{amount:'0',recipient:'Подмена API',active:false}}
 const headers={'X-Application-Key':application.api_key}
 const decision=await call('/checks',payload,'POST',200,headers)
 assert.equal(decision.state,'PENDING_REVIEW');assert.equal(decision.checked_values.amount,'11500.125');assert.equal(decision.checked_values.recipient,'Учебный получатель');assert.equal(decision.checked_values.active,true)
 const repeat=await call('/checks',payload,'POST',200,headers);assert.equal(repeat.id,decision.id);assert.equal(repeat.expires_at,decision.expires_at)
 for(const record_key of ['missing','999','3']){const blocked=await call('/checks',{...payload,operation_id:crypto.randomUUID(),record_key},'POST',200,headers);assert.equal(blocked.state,'REJECTED')}
 const denied=[
  {...settings,connection:{...connection,password:'incorrect'}},
  {...settings,connection:{...connection,user:'lab_denied'}},
  {...settings,connection:{...connection,user:'lab_writer'}},
  {...settings,connection:{...connection,host:'not-allowed'}},
  {...settings,table_name:'private.forbidden'},
  {...settings,key_field:'batch',record_key:'duplicate'},
  {...settings,key_field:'id',record_key:'1.5'},
  {...settings,allowed_fields:['unsupported'],mapping:{recipient:'unsupported'}},
  {...settings,connection:{...connection,kind:kind==='mysql'?'postgresql':'mysql',password:''}},
 ]
 for(const invalid of denied){const result=await call('/admin/sources/'+id+'/test',invalid,'POST',422);if(invalid.connection?.user==='lab_writer')assert.match(result.message,/права записи|прямыми правами/)}
 await call('/admin/sources/'+id,{...settings,connection:{...connection,password:'incorrect'}},'PUT',422)
 assert.deepEqual(await call('/admin/sources/'+id),saved,'probe or failed save changed source')
 if(kind==='mongodb'){
  await call('/admin/sources/'+id+'/test',{...settings,key_field:'_id',record_key:'000000000000000000000001'})
  await call('/admin/sources/'+id+'/test',{...settings,key_field:'_id',record_key:'1'},'POST',422)
  assert.equal((await call('/checks',{...payload,operation_id:crypto.randomUUID(),record_key:'4'},'POST',200,headers)).state,'REJECTED')
 }
 report.engines.push({kind,application_id:id,decision_id:decision.id,state:decision.state,amount:decision.checked_values.amount,negative_cases:denied.length,passed:true})
 console.log('PASS '+kind+': discovery, metadata, typed read, mapping, REVIEW, replay, negative cases')
}
if(process.env.DIPLOMA_EVIDENCE)fs.writeFileSync(process.env.DIPLOMA_EVIDENCE,JSON.stringify(report,null,2))
