import assert from 'node:assert/strict'
import {test} from 'node:test'
import {api, ApiError} from '../src/api.ts'

const pending=()=>new Response(JSON.stringify({code:'history_pending',message:'История доставляется'}),{status:503})

test('transient history synchronization retries the exact keyed action',async t=>{
  const sent=[]
  t.mock.method(globalThis,'fetch',async (url,options)=>{
    sent.push([url,options.body])
    return sent.length<3 ? pending() : Response.json({decision:{state:'APPROVED',expires_at:'2026-10-22T18:00:00Z'},execution:{operation_id:'same-operation'}})
  })
  const body={action:'pay',version:4,operation_id:'same-operation'}
  const result=await api('/demo/requests/one/action','POST',body)
  assert.equal(result.execution.operation_id,body.operation_id)
  assert.equal(sent.length,3)
  assert(sent.every(([url,payload])=>url==='/api/demo/requests/one/action'&&payload===JSON.stringify(body)))
})

test('a persistent history gate remains an error after a bounded wait',async t=>{
  let count=0
  t.mock.method(globalThis,'fetch',async()=>{count++;return pending()})
  await assert.rejects(api('/demo/export/action','POST',{operation_id:'same-export'}),error=>error instanceof ApiError&&error.status===503)
  assert.equal(count,9)
})

test('restrictions and other failures never restart an action or human gate',async t=>{
  for(const [path,status,code] of [
    ['/demo/requests/one/action',409,'history_changed'],
    ['/demo/requests/one/action',503,'antifraud_unavailable'],
    ['/demo/execute',503,'history_pending'],
    ['/decisions/one/review',503,'history_pending'],
    ['/demo/decisions/one/confirm',503,'history_pending'],
    ['/demo/requests',503,'history_pending'],
  ]) {
    let count=0
    t.mock.method(globalThis,'fetch',async()=>{count++;return new Response(JSON.stringify({code,message:'Остановлено'}),{status})})
    await assert.rejects(api(path,'POST',{operation_id:'original'}),error=>error instanceof ApiError&&error.code===code)
    assert.equal(count,1,path)
    t.mock.restoreAll()
  }
})

test('an action requiring review is returned once without retry or execution',async t=>{
  let count=0
  t.mock.method(globalThis,'fetch',async()=>{count++;return Response.json({decision:{state:'PENDING_REVIEW'},execution:null})})
  const result=await api('/demo/requests/one/action','POST',{operation_id:'review'})
  assert.equal(result.decision.state,'PENDING_REVIEW')
  assert.equal(result.execution,null)
  assert.equal(count,1)
})

test('a non-JSON failure stays a readable error without retrying an unknown outcome',async t=>{
  let count=0
  t.mock.method(globalThis,'fetch',async()=>{count++;return new Response('upstream unavailable',{status:502})})
  await assert.rejects(api('/demo/requests/one/action','POST',{operation_id:'unknown-outcome'}),error=>error instanceof ApiError&&error.status===502&&error.code===''&&error.message.includes('Сервер не вернул ответ'))
  assert.equal(count,1)
})
