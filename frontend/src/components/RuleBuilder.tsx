import {fieldLabel, label, type Application, type Expression, type Watchlist} from '../api'
import {baseNode, kinds} from '../rule-presets'
import {mechanismHelp, ruleText} from '../rule-text'
import {DurationInput, FieldSelect, ValueItems} from './FormControls'

function Checklist({title, options, value, onChange}: {title: string; options: string[]; value: string[]; onChange: (value: string[]) => void}) {
  return <fieldset><legend>{title}</legend><div className="checks">{Array.from(new Set([...options,...value])).map(n => <label key={n}><input type="checkbox" checked={value.includes(n)} onChange={e => onChange(e.target.checked ? [...value, n] : value.filter(v => v !== n))}/>{fieldLabel(label(n))}{!options.includes(n) && ' (сохранённое значение)'}</label>)}</div></fieldset>
}
export function RuleBuilder({node, onChange, app, action, lists, depth = 0, fieldFilter = false}: {node: Expression; onChange: (n: Expression) => void; app: Application; action: string; lists: Watchlist[]; depth?: number; fieldFilter?: boolean}) {
  const config = app.catalog[action]
  if (!config) return <p>Выберите зарегистрированное действие.</p>
  const names = Object.keys(config.fields)
  const set = (key: keyof Expression, value: unknown) => {const updated = {...node, [key]: value}; if (value === undefined) delete updated[key]; onChange(updated)}
  const historical = !['all', 'any', 'not', 'field'].includes(node.kind) && !(node.kind === 'related' && node.relation === 'current')
  const numeric = config.fields[node.field ?? '']?.type === 'number'
  const boolean = config.fields[node.field ?? '']?.type === 'boolean'
  const statuses=Array.from(new Set((node.event_types ?? [action]).flatMap(event=>app.catalog[event]?.statuses ?? [])))
  const ops = Object.entries({eq:'Равно', ne:'Не равно', gt:'Больше', ge:'Не меньше', lt:'Меньше', le:'Не больше', in:'Входит в список'}).filter(([key]) => key === 'in' ? node.kind === 'field' : ['eq','ne'].includes(key) || numeric || ['count','aggregate'].includes(node.kind))
  const changeField = (field: string) => {
    const type = config.fields[field]?.type
    const updated = {...node, field}
    if (node.kind === 'field') {
      delete updated.list_id
      updated.op = 'eq'
      updated.value = type === 'number' ? 0 : type === 'boolean' ? false : ''
    }
    if (node.kind === 'related') {updated.right_field = field; updated.op = 'eq'}
    onChange(updated)
  }
  return <div className={'rule-builder ' + (['all','any','not'].includes(node.kind) ? 'boolean-node' : '')}>
    <div className="node-heading"><label>Механизм<select aria-label="Механизм" value={node.kind} onChange={e => onChange(baseNode(e.target.value, app, action))}>{Object.entries(kinds).filter(([k]) => (!fieldFilter || ['all','any','not','field'].includes(k)) && (depth < 6 || !['all','any','not'].includes(k))).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></label></div>
    <p className="node-help">{mechanismHelp[node.kind]}</p>
    {['all','any'].includes(node.kind) && <div className="tree-children">{node.children?.map((child,i) => <details key={i} open className="tree-branch"><summary>Условие {i+1} · {ruleText(child)}</summary><RuleBuilder node={child} app={app} action={action} lists={lists} depth={depth+1} fieldFilter={fieldFilter} onChange={next => set('children',node.children?.map((n,j) => j === i ? next : n))}/><button type="button" className="quiet danger" disabled={(node.children?.length ?? 0) <= 1} onClick={() => set('children',node.children?.filter((_,j) => j !== i))}>Убрать условие</button></details>)}<button type="button" disabled={(node.children?.length ?? 0) >= 20} onClick={() => set('children',[...node.children ?? [],baseNode('field',app,action)])}>+ Условие</button></div>}
    {node.kind === 'not' && node.child && <RuleBuilder node={node.child} onChange={n => set('child',n)} app={app} action={action} lists={lists} depth={depth+1} fieldFilter={fieldFilter}/>}
    <div className="form-grid node-fields">
      {['field','aggregate','related','novelty'].includes(node.kind) && <FieldSelect title="Поле" value={node.field} fields={Object.fromEntries(Object.entries(config.fields).filter(([,f])=>node.kind!=='aggregate'||node.aggregate!=='sum'||f.type==='number'))} onChange={changeField}/>}
      {['field','count','aggregate','related'].includes(node.kind) && <label>Сравнение<select aria-label="Сравнение" value={node.op} onChange={e => {const updated={...node,op:e.target.value,value:e.target.value === 'in' ? [] : numeric || node.kind !== 'field' ? 0 : boolean ? false : ''};delete updated.list_id;onChange(updated)}}>{ops.map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></label>}
      {node.kind === 'field' && node.op === 'in' && <label>Список наблюдения<select aria-label="Список наблюдения" value={node.list_id ?? ''} onChange={e => {const updated: Expression={...node,value:[]};if(e.target.value) updated.list_id=e.target.value;else delete updated.list_id;onChange(updated)}}><option value="">Значения вручную</option>{lists.map(l => {const valid=l.values.every(v=>numeric?typeof v!=='boolean'&&String(v).trim()!==''&&Number.isFinite(Number(v)):boolean?typeof v==='boolean':typeof v==='string');return <option key={l.id} value={l.id} disabled={!valid}>{l.name}{valid?'':' · несовместимый тип'}</option>})}</select></label>}
      {node.kind === 'field' && node.op !== 'in' && boolean && <label>Значение / порог<select aria-label="Значение / порог" value={String(node.value === true)} onChange={e => set('value',e.target.value === 'true')}><option value="true">Да</option><option value="false">Нет</option></select></label>}
      {node.kind==='field' && node.op==='in' && !node.list_id && <ValueItems value={Array.isArray(node.value)?node.value:[]} type={config.fields[node.field??'']?.type??'string'} onChange={v=>set('value',v)}/>}
      {['field','count','aggregate'].includes(node.kind) && node.op!=='in' && !(node.kind==='field'&&boolean) && <label>Значение / порог{node.kind==='field' && config.fields[node.field??'']?.values?.length ? <select aria-label="Значение / порог" value={String(node.value??'')} onChange={e=>set('value',e.target.value)}>{Array.from(new Set([...(config.fields[node.field??'']?.values??[]).map(String),String(node.value??'')])).map(v=><option key={v} value={v}>{v}</option>)}</select> : <input required type={numeric||node.kind!=='field'?'number':'text'} step="any" value={String(node.value??'')} onChange={e=>set('value',e.target.value)}/>}</label>}
      {node.kind === 'aggregate' && <label>Расчёт<select aria-label="Расчёт" value={node.aggregate} onChange={e => onChange({...node,aggregate:e.target.value,field:(e.target.value === 'sum' ? names.find(n => config.fields[n]?.type === 'number') : node.field) ?? names[0] ?? ''})}><option value="sum">Сумма</option><option value="unique">Количество уникальных значений</option></select></label>}
      {node.kind === 'related' && <><label>Связанные данные<select aria-label="Связанные данные" value={node.relation ?? 'history'} onChange={e => set('relation',e.target.value)}><option value="history">Событие истории</option><option value="current">Объект: проверенные поля этой операции</option></select></label><label>Поле связанного объекта / события<select aria-label="Поле связанного объекта / события" value={node.right_field} onChange={e => set('right_field',e.target.value)}>{names.filter(n => config.fields[n]?.type === config.fields[node.field ?? '']?.type).map(n => <option key={n} value={n}>{fieldLabel(n)}</option>)}</select></label></>}
      {historical && <DurationInput value={node.period_seconds} optional={node.kind==='previous'} onChange={v=>set('period_seconds',v)}/>}
      {historical && <div><Checklist title="Учитываемые статусы" options={statuses} value={node.statuses??[]} onChange={v=>set('statuses',v)}/><small>{statuses.length?'Варианты из каталога выбранных событий.':'В каталоге нет статусов. Добавьте варианты в настройках приложения; прежние значения сохранены.'}</small></div>}
    </div>
    {node.kind === 'sequence' && <fieldset><legend>Порядок событий</legend>{node.sequence?.map((step,i) => <div className="sequence-step" key={i}><span>{i+1}.</span><select aria-label={'Шаг последовательности ' + (i+1)} value={step} onChange={e => set('sequence',node.sequence?.map((v,j) => i === j ? e.target.value : v))}>{Object.keys(app.catalog).map(n => <option key={n} value={n}>{label(n)}</option>)}</select><button type="button" disabled={i === 0} onClick={() => {const next=[...node.sequence ?? []];[next[i-1],next[i]]=[next[i]!,next[i-1]!];set('sequence',next)}}>Раньше</button><button type="button" disabled={(node.sequence?.length ?? 0) <= 2} onClick={() => set('sequence',node.sequence?.filter((_,j) => i !== j))}>Убрать шаг</button></div>)}<button type="button" onClick={() => set('sequence',[...node.sequence ?? [],Object.keys(app.catalog)[0]!])}>+ Шаг</button></fieldset>}
    {historical && <details open className="history-settings"><summary>Отбор истории и связь событий</summary><Checklist title="Типы событий истории" options={Object.keys(app.catalog)} value={node.event_types ?? []} onChange={v => set('event_types',v)}/><Checklist title="Группировка по полям" options={names} value={node.group_by ?? []} onChange={v => set('group_by',v)}/>{['duplicate','previous'].includes(node.kind) && <Checklist title="Поля совпадения актуальных значений" options={names} value={node.match_fields ?? []} onChange={v => set('match_fields',v)}/>}<label className="check"><input type="checkbox" checked={Boolean(node.filter)} onChange={e => set('filter',e.target.checked ? baseNode('field',app,action) : undefined)}/>Фильтр событий истории</label>{node.filter && <RuleBuilder node={node.filter} onChange={v => set('filter',v)} app={app} action={action} lists={lists} depth={depth+1} fieldFilter/>}</details>}
    {['count','aggregate'].includes(node.kind) && <label className="check"><input type="checkbox" checked={node.include_current ?? false} onChange={e => set('include_current',e.target.checked)}/>Включать текущую операцию в расчёт один раз</label>}
    {node.kind === 'novelty' && <label className="check"><input type="checkbox" checked={node.on_empty ?? false} onChange={e => set('on_empty',e.target.checked)}/>Срабатывать и при пустой истории</label>}
  </div>
}
