import {test} from 'node:test'
import assert from 'node:assert/strict'
import {decimalText} from '../src/api.ts'
import {ruleIssues} from '../src/rule-validation.ts'

test('checked decimal fields retain every digit instead of rounding to demo currency',()=>{
  assert.equal(decimalText('1234567890123456.1250'),'1\u00a0234\u00a0567\u00a0890\u00a0123\u00a0456,1250')
  assert.equal(decimalText('11500.125'),'11\u00a0500,125')
})
test('action switch preserves the expression and reports incompatibilities',()=>{
  const app={catalog:{new:{fields:{amount:{type:'string'}},statuses:['DONE']}}}
  const node={kind:'all',children:[{kind:'field',field:'old_id',op:'eq',value:'keep'},{kind:'aggregate',field:'amount',aggregate:'sum',statuses:[],event_types:['missing']}]}
  const before=JSON.stringify(node)
  const issues=ruleIssues(node,app,'new')
  assert(issues.some(i=>i.includes('old_id')))
  assert(issues.some(i=>i.includes('числовое')))
  assert(issues.some(i=>i.includes('статус')))
  assert(issues.some(i=>i.includes('missing')))
  assert.equal(JSON.stringify(node),before)
})
