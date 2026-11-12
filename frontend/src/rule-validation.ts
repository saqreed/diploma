import type {Application, Expression} from './api'

export function ruleIssues(node:Expression,app:Application,action:string):string[]{
  const fields=app.catalog[action]?.fields??{}
  const names=[node.field,node.right_field,...node.group_by??[],...node.match_fields??[]].filter((v):v is string=>Boolean(v))
  const issues=names.filter(n=>!fields[n]).map(n=>`Поле «${n}» отсутствует у выбранного действия`)
  if(node.field&&fields[node.field]){
    const type=fields[node.field]!.type
    if(node.kind==='aggregate'&&node.aggregate==='sum'&&type!=='number')issues.push('Для суммы нужно числовое поле')
    if(node.kind==='field'&&node.value_type&&node.value_type!==type)issues.push(`Тип поля «${node.field}» изменился. Выберите поле и значение заново`)
    if(node.kind==='related'&&node.right_field&&fields[node.right_field]?.type!==type)issues.push('Поля сравнения имеют разные типы')
  }
  for(const event of [...node.event_types??[],...node.sequence??[]])if(!app.catalog[event])issues.push(`Событие «${event}» отсутствует в каталоге`)
  if(!['field','all','any','not'].includes(node.kind)&&!(node.kind==='related'&&node.relation==='current')&&!node.statuses?.length)issues.push('Выберите хотя бы один статус истории из каталога')
  for(const child of [...node.children??[],...node.child?[node.child]:[],...node.filter?[node.filter]:[]])issues.push(...ruleIssues(child,app,action))
  return Array.from(new Set(issues))
}
