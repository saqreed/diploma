import {useCallback, useEffect, useRef, useState, type FormEvent} from 'react'
import {Navigate} from 'react-router'
import {api, type Application, type Field} from '../api'
import {useSession} from '../session'
type Source = {table_name: string; key_field: string; allowed_fields: string[]; mapping: Record<string, string>}
const emptyApp: Application = {id: '', name: '', ttl_seconds: 600, catalog: {operation: {fields: {amount: {type: 'number', source: 'API', required: true}}}}}
export function SettingsPage() {
  const {account} = useSession()
  const [apps, setApps] = useState<Application[]>([])
  const [draft, setDraft] = useState<Application | null>(null)
  const [creating, setCreating] = useState(false)
  const [newEvent, setNewEvent] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [sourceApp, setSourceApp] = useState('demo')
  const [source, setSource] = useState<Source>({table_name: 'demo.requests', key_field: 'id', allowed_fields: ['amount', 'recipient'], mapping: {amount: 'amount', recipient: 'recipient'}})
  const [url, setUrl] = useState('')
  const [mapping, setMapping] = useState('amount=amount\nrecipient=recipient')
  const [resetPhrase, setResetPhrase] = useState('')
  const [sourceLoading, setSourceLoading] = useState(false)
  const sourceRequest = useRef(0)
  const load = useCallback(async () => {setApps(await api<Application[]>('/admin/applications'))}, [])
  useEffect(() => {if (account?.role === 'admin') void api<Application[]>('/admin/applications').then(setApps).catch(e => setError(e.message))}, [account])
  if (!account) return <Navigate to="/login" replace />
  if (account.role !== 'admin') return <p>Настройки доступны администратору.</p>
  async function save(e: FormEvent) {e.preventDefault(); if (!draft) return; setError(''); try {const result = await api<{api_key?: string}>('/admin/applications' + (creating ? '' : '/' + draft.id), creating ? 'POST' : 'PUT', draft); setApiKey(result.api_key ?? ''); setDraft(null); await load(); setNotice('Настройки приложения сохранены.')} catch (e) {setError((e as Error).message)}}
  function changeField(action: string, name: string, value: Field, newName = name) {if (!draft) return; const catalog = structuredClone(draft.catalog); const config = catalog[action]; if (!config) return; config.fields = name in config.fields ? Object.fromEntries(Object.entries(config.fields).map(([key, item]) => key === name ? [newName, value] : [key, item])) : {...config.fields, [newName]: value}; setDraft({...draft, catalog})}
  function addField(action: string) {if (!draft) return; const fields = draft.catalog[action]?.fields; if (!fields) return; let number = Object.keys(fields).length + 1; while ('field_' + number in fields) number++; changeField(action, 'field_' + number, {type: 'string', source: 'API', required: true})}
  function removeField(action: string, name: string) {if (!draft) return; const catalog = structuredClone(draft.catalog); const config = catalog[action]; if (!config) return; delete config.fields[name]; setDraft({...draft, catalog})}
  function renameField(action: string, name: string, field: Field, input: HTMLInputElement) {
    if (input.value !== name && draft?.catalog[action]?.fields[input.value]) {
      input.setCustomValidity('Поле с таким именем уже существует')
      input.reportValidity()
      return
    }
    if (input.checkValidity() && input.value !== name) changeField(action, name, field, input.value)
  }
  async function loadSource(id: string) {
    const requestNumber = ++sourceRequest.current
    setSourceApp(id); setUrl(''); setError(''); setSourceLoading(true)
    try {
      const result = await api<Source | null>('/admin/sources/' + id)
      if (requestNumber !== sourceRequest.current) return
      if (result) {setSource(result); setMapping(Object.entries(result.mapping).map(([a, b]) => a + '=' + b).join('\n'))}
      else {setSource({table_name: 'demo.requests', key_field: 'id', allowed_fields: [], mapping: {}}); setMapping('')}
    } catch (e) {if (requestNumber === sourceRequest.current) setError((e as Error).message)}
    finally {if (requestNumber === sourceRequest.current) setSourceLoading(false)}
  }
  async function saveSource(e: FormEvent) {e.preventDefault(); setError(''); try {const pairs = mapping.split('\n').filter(Boolean).map(line => line.split('=').map(s => s.trim())); if (pairs.some(p => p.length !== 2 || !p[0] || !p[1])) throw new Error('Сопоставление: одно поле=столбец на каждой строке'); await api('/admin/sources/' + sourceApp, 'PUT', {...source, mapping: Object.fromEntries(pairs), url}); setUrl(''); setNotice('Источник сохранён. Пароль не отображается повторно.')} catch (e) {setError((e as Error).message)}}
  return <><div className="page-heading"><div><span className="eyebrow">ПОДКЛЮЧЕНИЕ ПРИЛОЖЕНИЙ</span><h1>Приложения и источники</h1><p className="muted">Предметную область задаёт каталог событий и полей.</p></div><button className="primary" onClick={() => {setDraft(structuredClone(emptyApp)); setCreating(true)}}>+ Приложение</button></div>{error && <div className="error" role="alert">{error}</div>}{notice && <div className="notice">{notice}</div>}{apiKey && <div className="notice"><strong>Ключ нового приложения — отображается один раз</strong><p><code>{apiKey}</code></p><button onClick={() => setApiKey('')}>Скрыть</button></div>}<section className="card">{apps.map(a => <div className="list-row" key={a.id}><strong>{a.name}</strong><span>{a.id} · {Object.keys(a.catalog).length} типов · срок {a.ttl_seconds} с</span><button onClick={() => {setDraft(structuredClone(a)); setCreating(false)}}>Настроить</button></div>)}</section>
    {draft && <form className="card" onSubmit={save}><h2>Каталог приложения</h2><div className="form-grid"><label>Идентификатор<input required disabled={!creating} value={draft.id} onChange={e => setDraft({...draft, id: e.target.value})} /></label><label>Название<input required value={draft.name} onChange={e => setDraft({...draft, name: e.target.value})} /></label><label>Срок решения, секунды<input required type="number" min="1" max="86400" value={draft.ttl_seconds} onChange={e => setDraft({...draft, ttl_seconds: Number(e.target.value)})} /></label></div>{Object.entries(draft.catalog).map(([action, config]) => <fieldset key={action}><legend>Тип события: {action}</legend><div className="table-scroll"><table><thead><tr><th>Поле</th><th>Тип</th><th>Источник</th><th>Обязательное</th><th/></tr></thead><tbody>{Object.entries(config.fields).map(([name, field]) => <tr key={name}><td><input aria-label={'Имя поля ' + name} required defaultValue={name} onChange={e => e.currentTarget.setCustomValidity('')} onBlur={e => renameField(action, name, field, e.currentTarget)} onKeyDown={e => {if (e.key === 'Enter') {e.preventDefault(); e.currentTarget.blur()}}} /></td><td><select aria-label={'Тип ' + name} value={field.type} onChange={e => changeField(action, name, {...field, type: e.target.value as Field['type']})}><option value="string">Строка</option><option value="number">Число</option><option value="boolean">Логическое</option></select></td><td><select aria-label={'Источник ' + name} value={field.source} onChange={e => changeField(action, name, {...field, source: e.target.value as Field['source']})}><option>API</option><option>DB</option></select></td><td><input aria-label={'Обязательное ' + name} type="checkbox" checked={field.required} onChange={e => changeField(action, name, {...field, required: e.target.checked})} /></td><td><button type="button" onClick={() => removeField(action, name)}>Убрать</button></td></tr>)}</tbody></table></div><button type="button" onClick={() => addField(action)}>+ Поле</button><button type="button" onClick={() => {const catalog = structuredClone(draft.catalog); delete catalog[action]; setDraft({...draft, catalog})}}>Убрать тип события</button></fieldset>)}<div className="toolbar"><label>Новый тип события<input value={newEvent} onChange={e => setNewEvent(e.target.value)} /></label><button type="button" disabled={!newEvent || Boolean(draft.catalog[newEvent])} onClick={() => {setDraft({...draft, catalog: {...draft.catalog, [newEvent]: {fields: {object_id: {type: 'string', source: 'API', required: true}}}}}); setNewEvent('')}}>Добавить тип</button></div><div className="actions"><button className="primary">Сохранить каталог</button><button type="button" onClick={() => setDraft(null)}>Закрыть</button></div></form>}
    <form className="card" onSubmit={saveSource}><h2>Источник PostgreSQL · только чтение</h2><p className="muted">Один источник на поле. Разрешённые таблицы и серверы задаются при локальном подключении. История поступает через API.</p><fieldset disabled={sourceLoading} className="form-grid"><label>Приложение<select aria-label="Приложение" value={sourceApp} onChange={e => loadSource(e.target.value)}>{apps.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label><label>URL подключения<input required type="password" autoComplete="new-password" placeholder="postgresql+asyncpg://…" value={url} onChange={e => setUrl(e.target.value)} /></label><label>Таблица<input required value={source.table_name} onChange={e => setSource({...source, table_name: e.target.value})} /></label><label>Столбец ключа<input required value={source.key_field} onChange={e => setSource({...source, key_field: e.target.value})} /></label><label>Разрешённые столбцы через запятую<input required value={source.allowed_fields.join(', ')} onChange={e => setSource({...source, allowed_fields: e.target.value.split(',').map(s => s.trim())})} /></label><label>Сопоставление: поле проверки=столбец<textarea required value={mapping} onChange={e => setMapping(e.target.value)} /></label></fieldset>{sourceLoading && <p role="status">Загружаем настройки источника…</p>}<button className="primary" disabled={sourceLoading}>Сохранить источник</button></form>
    <section className="card"><h2>Вернуть учебное демо</h2><p className="muted">Текущие заявки сохранятся в архиве базы данных. Появятся исходные учебные заявки, незавершённые попытки отменятся. Журнал и настройки правил останутся; новая история расчётов начнётся с момента возврата. Введите «Вернуть учебное демо» для выполнения.</p><div className="toolbar"><label>Подтверждение возврата<input value={resetPhrase} onChange={e => setResetPhrase(e.target.value)} /></label><button disabled={resetPhrase !== 'Вернуть учебное демо'} onClick={async () => {setError(''); try {const result = await api<{message: string}>('/demo/reset', 'POST', {confirmation: resetPhrase}); setNotice(result.message); setResetPhrase('')} catch (e) {setError((e as Error).message)}}}>Вернуть демо</button></div></section>
  </>
}
