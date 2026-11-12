import {useCallback, useEffect, useRef, useState, type FormEvent} from 'react'
import {api, fieldLabel, type Application, type Field} from '../api'
import {useMemoryDraft} from '../drafts'

type Connection={kind:string;host:string;port:string;database:string;user:string;password:string}
type Source={application_id:string;connection:Omit<Connection,'password'>;table_name:string;key_field:string;allowed_fields:string[];mapping:Record<string,string>;credentials_saved:boolean}
type Resource={name:string;fields:Record<string,{type:string;nullable:boolean}>;note?:string}
type Inventory={scope:string;updated_at:string;inventory_at:string|null;warnings:string[];sources:Array<{id:string;kind:string;host:string;port:number;origin:string;state:string;databases:string[];selectable:boolean}>}
const kinds:Record<string,string>={postgresql:'PostgreSQL · реляционная БД',mysql:'MySQL · реляционная БД',mongodb:'MongoDB · документная БД',unknown:'Неизвестный тип БД'}
const types:Record<string,string>={string:'Строка',number:'Число',integer:'Целое число',boolean:'Да / нет',objectid:'ObjectId → строка',unsupported:'Не поддерживается'}
const ports:Record<string,string>={postgresql:'5432',mysql:'3306',mongodb:'27017'}
const blank:Connection={kind:'postgresql',host:'',port:'5432',database:'',user:'',password:''}
const compatible=(type:string,field:Field)=>field.type===(type==='integer'?'number':type==='objectid'?'string':type)

export function Connections({apps,onSaved,active}:{apps:Application[];onSaved:()=>Promise<void>;active:boolean}) {
  const [saved,setSaved]=useState<Source[]>([])
  const [search,setSearch]=useState('')
  const [inventory,setInventory]=useState<Inventory|null>(null)
  const [refreshing,setRefreshing]=useState(false)
  const [show,setShow]=useMemoryDraft('connection-open',false)
  const [application,setApplication]=useMemoryDraft('connection-app','')
  const [connection,setConnection]=useMemoryDraft<Connection>('connection-draft',blank)
  const [table,setTable]=useMemoryDraft('connection-table','')
  const [key,setKey]=useMemoryDraft('connection-key','')
  const [mapping,setMapping]=useMemoryDraft<Record<string,string>>('connection-mapping',{})
  const [fieldSources,setFieldSources]=useMemoryDraft<Record<string,string>>('connection-field-sources',{})
  const [testKey,setTestKey]=useMemoryDraft('connection-test-key','')
  const [resources,setResources]=useState<Resource[]>([])
  const [databases,setDatabases]=useState<string[]>([])
  const [options,setOptions]=useState<Array<{kind:string;host:string;port:string;databases:string[]}>>([])
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [pending,setPending]=useState(false)
  const [accessSignature,setAccessSignature]=useState('')
  const [testSignature,setTestSignature]=useState('')
  const [url,setUrl]=useState('')
  const request=useRef(0)
  const formRef=useRef<HTMLFormElement>(null)
  const app=apps.find(a=>a.id===application)
  const fields=Object.assign({},...Object.values(app?.catalog??{}).map(c=>c.fields)) as Record<string,Field>
  const resource=resources.find(r=>r.name===table)
  const signature=JSON.stringify({connection,url,application})
  const selection=JSON.stringify({signature,table,key,mapping,fieldSources,testKey})
  const verified=accessSignature===signature
  const old=saved.find(s=>s.application_id===application)
  const same=old&&Object.entries(old.connection).every(([k,v])=>connection[k as keyof Connection]===v)
  const availableDatabases=options.find(o=>o.kind===connection.kind&&o.host===connection.host&&o.port===connection.port)?.databases??databases
  const receive=useCallback((results: [PromiseSettledResult<Source[]>,PromiseSettledResult<Inventory>])=>{
    if(results[0].status==='fulfilled')setSaved(results[0].value)
    if(results[1].status==='fulfilled')setInventory(results[1].value)
    const failure=results.find(r=>r.status==='rejected')
    if(failure?.status==='rejected')setError(failure.reason.message)
    setRefreshing(false)
  },[])
  async function refresh(){setRefreshing(true);receive(await Promise.allSettled([api<Source[]>('/admin/sources'),api<Inventory>('/admin/source-discovery')]))}
  useEffect(()=>{if(!active)return;let current=true;void Promise.allSettled([api<Source[]>('/admin/sources'),api<Inventory>('/admin/source-discovery')]).then(results=>{if(current)receive(results)});return()=>{current=false}},[active,receive])
  useEffect(()=>{if(!active)return;let current=true;void api<typeof options>('/admin/source-options').then(value=>{if(current)setOptions(value)}).catch(()=>{});return()=>{current=false}},[active])
  function changeConnection(next:Connection){setConnection(next);setResources([]);setAccessSignature('');setTestSignature('');setNotice('');setError('')}
  function selectApp(id:string){
    setApplication(id);setAccessSignature('');setTestSignature('');setError('');setNotice('');setResources([]);setUrl('');setTestKey('')
    const existing=saved.find(s=>s.application_id===id)
    const config=Object.assign({},...Object.values(apps.find(a=>a.id===id)?.catalog??{}).map(c=>c.fields)) as Record<string,Field>
    setFieldSources(Object.fromEntries(Object.entries(config).map(([n,f])=>[n,f.source])))
    if(existing){setConnection({...existing.connection,password:''});setTable(existing.table_name);setKey(existing.key_field);setMapping(existing.mapping)}
    else{setConnection({...connection,password:''});setTable('');setKey('');setMapping({})}
  }
  function start(source?:Inventory['sources'][number]){
    setShow(true);setError('');setNotice('');setUrl('');setAccessSignature('');setTestSignature('');setResources([])
    if(source){changeConnection({kind:source.kind,host:source.host,port:String(source.port),database:source.databases[0]??'',user:'',password:''});setDatabases(source.databases);setTable('');setKey('');setMapping({})}
    else{changeConnection(blank);setDatabases([]);setTable('');setKey('');setMapping({})}
    setTimeout(()=>formRef.current?.scrollIntoView({block:'start',behavior:'smooth'}),0)
  }
  const accessPayload=()=>url?{url}:{connection}
  const payload=()=>({...accessPayload(),table_name:table,key_field:key,allowed_fields:Array.from(new Set(Object.values(mapping))),mapping,field_sources:fieldSources,record_key:testKey})
  async function run(task:()=>Promise<void>){if(pending)return;setPending(true);setError('');setNotice('');try{await task()}catch(e){setError((e as Error).message)}finally{setPending(false)}}
  async function inspect(){await run(async()=>{
    if(!application)throw new Error('Сначала выберите приложение')
    const current=++request.current
    const result=await api<{resources:Resource[];databases:string[];message:string}>('/admin/sources/'+application+'/inspect','POST',accessPayload())
    if(current!==request.current)return
    setResources(result.resources);setDatabases(result.databases);setAccessSignature(signature);setNotice(result.message)
    if(!table){setTable(result.resources[0]?.name??'');setKey('')}
  })}
  async function test(){await run(async()=>{
    if(!testKey.trim())throw new Error('Введите ключ тестовой записи')
    const result=await api<{message:string;fields:string[]}>('/admin/sources/'+application+'/test','POST',payload())
    setTestSignature(selection);setNotice(result.message+' Поля: '+result.fields.map(fieldLabel).join(', '))
  })}
  async function save(e:FormEvent){e.preventDefault();await run(async()=>{
    if(testSignature!==selection)throw new Error('Проверьте чтение с текущими настройками перед сохранением')
    await api('/admin/sources/'+application,'PUT',payload());setConnection({...connection,password:''});setUrl('');setAccessSignature('');setTestSignature('');await refresh();await onSaved();setNotice('Источник сохранён. Пароль не отображается повторно.')
  })}
  return <div className="connections" hidden={!active}>
    <section className="card"><div className="section-heading"><div><h2>Подключённые источники</h2><p className="muted">Один профиль на приложение. История проверок остаётся во внутренней PostgreSQL.</p></div><button onClick={()=>start()}>Добавить вручную</button></div>
      <label>Поиск подключений<input type="search" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Приложение, тип БД или адрес"/></label>
      {!saved.length && <p className="empty">Сохранённых источников пока нет.</p>}
      <div className="source-cards saved-sources">{saved.filter(s=>[s.application_id,apps.find(a=>a.id===s.application_id)?.name,kinds[s.connection.kind],s.connection.host].join(' ').toLocaleLowerCase().includes(search.toLocaleLowerCase())).map(s=><article className="source-card" key={s.application_id}><span className="source-symbol" aria-hidden>▤</span><h3>{apps.find(a=>a.id===s.application_id)?.name??s.application_id}</h3><p>{kinds[s.connection.kind]}</p><p>{s.connection.host}:{s.connection.port} / {s.connection.database}</p><span className="badge APPROVED">Настроен</span><small>Доступ проверяется заново по запросу. {s.table_name}</small><button onClick={()=>{setShow(true);selectApp(s.application_id)}}>Настроить подключение</button></article>)}</div>
    </section>
    <section className="card"><div className="section-heading"><h2>Обнаруженные источники</h2><button disabled={refreshing} onClick={()=>void refresh()}>{refreshing?'Обновляем…':'Обновить'}</button></div><p className="muted">{inventory?.scope??'Загружаем границы обнаружения…'}</p><p className="small">Проверяются только объявленные адреса. Доступный порт ещё не означает вход в БД или права чтения.</p>
      {inventory && <small>Последняя проверка: {new Date(inventory.updated_at).toLocaleTimeString('ru')} · Инвентарь: {inventory.inventory_at?new Date(inventory.inventory_at).toLocaleTimeString('ru'):'серверная конфигурация'}</small>}
      {inventory?.warnings.map(w=><p className="warning" key={w}>{w}</p>)}
      {!refreshing && !inventory?.sources.length && <p className="empty">В настроенном инвентаре нет источников. Можно добавить подключение вручную.</p>}
      <div className="source-cards">{inventory?.sources.map(s=><article className="source-card" key={s.id}><span className="source-symbol" aria-hidden>▤</span><h3>{s.id}</h3><p>{kinds[s.kind]??kinds.unknown}</p><p>{s.host}:{s.port}</p><small>{s.origin}</small><span className={'badge '+(s.state==='available'?'APPROVED':s.state==='unavailable'?'REJECTED':'')}>{s.state==='available'?'Доступен':s.state==='unavailable'?'Ошибка подключения':'Обнаружен'}</span><button disabled={!s.selectable} onClick={()=>start(s)}>Выбрать источник</button>{!s.selectable && <small>Нет разрешения в серверной политике.</small>}</article>)}</div>
    </section>
    {show && <form ref={formRef} className="card connection-form" onSubmit={save}>
      <div className="section-heading"><h2>Настройка подключения</h2><button type="button" onClick={()=>setShow(false)}>Свернуть</button></div>
      <p className="muted">Проверки не меняют сохранённый профиль. Изменения применяются только кнопкой «Сохранить источник».</p>
      <fieldset disabled={pending}><legend>1. Приложение и доступ</legend><div className="form-grid">
        <label>Приложение<select aria-label="Приложение источника" required value={application} onChange={e=>selectApp(e.target.value)}><option value="">Выберите приложение</option>{apps.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
        <label>Тип БД<select aria-label="Тип БД" value={connection.kind} onChange={e=>changeConnection({...blank,kind:e.target.value,port:ports[e.target.value]!})}>{Object.entries(kinds).filter(([k])=>k!=='unknown').map(([k,t])=><option key={k} value={k}>{t}</option>)}</select></label>
        {Object.entries({host:'Сервер БД',port:'Порт БД',user:'Пользователь только для чтения',password:'Пароль подключения'}).map(([k,t])=><label key={k}>{t}<input autoComplete={k==='password'?'new-password':'off'} list={k==='host'?'source-hosts':undefined} type={k==='password'?'password':k==='port'?'number':'text'} min={k==='port'?1:undefined} max={k==='port'?65535:undefined} value={connection[k as keyof Connection]} onChange={e=>changeConnection({...connection,[k]:e.target.value,...(k!=='password'?{password:''}:{})})}/></label>)}
        <datalist id="source-hosts">{options.filter(o=>o.kind===connection.kind).map(o=><option key={o.host} value={o.host}/>)}</datalist><label>База данных{availableDatabases.length?<select aria-label="База данных" value={connection.database} onChange={e=>changeConnection({...connection,database:e.target.value,password:''})}><option value="">Выберите базу</option>{Array.from(new Set([...availableDatabases,connection.database].filter(Boolean))).map(d=><option key={d} value={d}>{d}</option>)}</select>:<input value={connection.database} onChange={e=>changeConnection({...connection,database:e.target.value,password:''})}/>}</label>
      </div><p className="small">{same?'Пароль уже сохранён для этого подключения. Пустое поле оставит его прежним.':'Для нового адреса, типа БД, пользователя или базы нужен пароль.'}</p>
      <details><summary>Готовая строка подключения</summary><label>URL подключения<input type="password" autoComplete="new-password" value={url} onChange={e=>{setUrl(e.target.value);setAccessSignature('');setTestSignature('')}}/></label><small>Только адрес и учётные данные. Параметры драйвера в URL запрещены.</small></details>
      <button type="button" onClick={()=>void inspect()}>Проверить доступ и получить поля</button>{verified&&<span className="badge APPROVED">Доступ проверен</span>}
      </fieldset>
      {verified && <fieldset disabled={pending}><legend>2. Ресурс, ключ и поля</legend><div className="form-grid"><label>Таблица / коллекция<select aria-label="Таблица / коллекция" required value={table} onChange={e=>{setTable(e.target.value);setKey('');setMapping({});setTestSignature('')}}><option value="">Выберите ресурс</option>{resources.map(r=><option key={r.name} value={r.name}>{r.name}</option>)}</select></label><label>Поле ключа<select aria-label="Поле ключа" required value={key} onChange={e=>setKey(e.target.value)}><option value="">Выберите ключ</option>{Object.entries(resource?.fields??{}).filter(([,f])=>['integer','number','string','objectid'].includes(f.type)).map(([n,f])=><option key={n} value={n}>{n} · {types[f.type]}</option>)}</select></label></div>
      {resource?.note&&<p className="notice">{resource.note}</p>}<div className="table-scroll"><table><thead><tr><th>Поле приложения</th><th>Тип</th><th>Источник значения</th><th>Поле источника</th></tr></thead><tbody>{Object.entries(fields).map(([n,f])=><tr key={n}><td>{f.label||fieldLabel(n)}<small>{n}</small></td><td>{types[f.type]}</td><td><select aria-label={'Источник '+n} value={fieldSources[n]??f.source} onChange={e=>{setFieldSources({...fieldSources,[n]:e.target.value});if(e.target.value==='API'){const next={...mapping};delete next[n];setMapping(next)}}}><option value="API">API · из запроса</option><option value="DB">БД · по ключу</option></select></td><td>{(fieldSources[n]??f.source)==='DB'?<><select aria-label={'Сопоставление '+n} required value={mapping[n]??''} onChange={e=>setMapping({...mapping,[n]:e.target.value})}><option value="">Выберите совместимое поле</option>{mapping[n]&&!resource?.fields[mapping[n]]&&<option value={mapping[n]}>{mapping[n]} · отсутствует</option>}{Object.entries(resource?.fields??{}).map(([column,spec])=><option key={column} value={column} disabled={!compatible(spec.type,f)}>{column} · {types[spec.type]}{!compatible(spec.type,f)?' · несовместимо':''}</option>)}</select>{mapping[n]&&(!resource?.fields[mapping[n]]||!compatible(resource.fields[mapping[n]]!.type,f))&&<small className="error">Выберите совместимое поле</small>}</>:<span className="muted">Передаёт приложение</span>}</td></tr>)}</tbody></table></div></fieldset>}
      {verified && <fieldset disabled={pending}><legend>3. Проверка чтения и сохранение</legend><div className="connection-test"><label>Ключ тестовой записи<input value={testKey} onChange={e=>setTestKey(e.target.value)} placeholder={resource?.fields[key]?.type==='objectid'?'24 шестнадцатеричных символа':'Ключ одной существующей записи'}/></label><button type="button" onClick={()=>void test()}>Проверить подключение и чтение</button></div><button className="primary" disabled={testSignature!==selection}>Сохранить источник</button></fieldset>}
      {pending&&<p role="status">Проверяем…</p>}{error&&<div className="error" role="alert">{error}</div>}{notice&&<div className="notice" role="status">{notice}</div>}
    </form>}
    {!show&&error&&<p className="error" role="alert">{error}</p>}
  </div>
}
