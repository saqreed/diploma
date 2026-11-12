import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Navigate } from 'react-router'
import { api, label, type Application, type Field } from '../api'
import { useSession } from '../session'
import { TabBar } from '../components/TabBar'
import {Connections} from '../components/Connections'
import {DurationInput,ValueItems} from '../components/FormControls'
import {useMemoryDraft} from '../drafts'
const emptyApp: Application = {
  id: '',
  name: '',
  ttl_seconds: 600,
  catalog: { operation: { fields: { amount: { type: 'number', source: 'API', required: true } } } },
}
export function SettingsPage() {
  const { account } = useSession()
  const [apps, setApps] = useState<Application[]>([])
  const [tab, setTab] = useState('applications')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [draft, setDraft] = useMemoryDraft<Application | null>('catalog-draft',null)
  const [creating, setCreating] = useMemoryDraft('catalog-creating',false)
  const [newEvent, setNewEvent] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [resetPhrase, setResetPhrase] = useState('')
  const [pending, setPending] = useState(false)
  const busy = useRef(false)
  const load = useCallback(async () => {
    setApps(await api<Application[]>('/admin/applications'))
  }, [])
  useEffect(() => {
    if (account?.role === 'admin')
      void api<Application[]>('/admin/applications')
        .then(setApps)
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false))
  }, [account])
  if (!account) return <Navigate to="/login" replace />
  if (account.role !== 'admin') return <p>Настройки доступны администратору.</p>
  async function save(e: FormEvent) {
    e.preventDefault()
    if (!draft || busy.current) return
    busy.current=true;setPending(true)
    setError('')
    try {
      const result = await api<{ api_key?: string }>(
        '/admin/applications' + (creating ? '' : '/' + draft.id),
        creating ? 'POST' : 'PUT',
        draft,
      )
      setApiKey(result.api_key ?? '')
      setDraft(null)
      await load()
      setNotice('Настройки приложения сохранены.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      busy.current=false;setPending(false)
    }
  }
  function changeField(action: string, name: string, value: Field, newName = name) {
    if (!draft) return
    const catalog = structuredClone(draft.catalog)
    const config = catalog[action]
    if (!config) return
    config.fields =
      name in config.fields
        ? Object.fromEntries(
            Object.entries(config.fields).map(([key, item]) =>
              key === name ? [newName, value] : [key, item],
            ),
          )
        : { ...config.fields, [newName]: value }
    setDraft({ ...draft, catalog })
  }
  function addField(action: string) {
    if (!draft) return
    const fields = draft.catalog[action]?.fields
    if (!fields) return
    let number = Object.keys(fields).length + 1
    while ('field_' + number in fields) number++
    changeField(action, 'field_' + number, { type: 'string', source: 'API', required: true })
  }
  function removeField(action: string, name: string) {
    if (!draft) return
    const catalog = structuredClone(draft.catalog)
    const config = catalog[action]
    if (!config) return
    delete config.fields[name]
    setDraft({ ...draft, catalog })
  }
  function renameField(action: string, name: string, field: Field, input: HTMLInputElement) {
    if (input.value !== name && draft?.catalog[action]?.fields[input.value]) {
      input.setCustomValidity('Поле с таким именем уже существует')
      input.reportValidity()
      return
    }
    if (input.checkValidity() && input.value !== name) changeField(action, name, field, input.value)
  }
  const visibleApps = apps.filter((app) =>
    [app.id, app.name].some((value) =>
      value.toLocaleLowerCase('ru').includes(search.toLocaleLowerCase('ru')),
    ),
  )
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Приложения и источники</h1>
          <p className="muted">Предметную область задаёт каталог событий и полей.</p>
        </div>
        <button
          className="primary"
          onClick={() => {
            setTab('applications')
            setDraft(structuredClone(emptyApp))
            setCreating(true)
          }}
        >
          + Приложение
        </button>
      </div>
      {error && tab !== 'sources' && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="notice" role="status">
          {notice}
        </div>
      )}
      {apiKey && (
        <div className="notice">
          <strong>Ключ нового приложения — отображается один раз</strong>
          <p>
            <code>{apiKey}</code>
          </p>
          <button onClick={() => setApiKey('')}>Скрыть</button>
        </div>
      )}
      <TabBar
        id="settings"
        label="Разделы настроек"
        active={tab}
        onChange={(value) => {
          setTab(value)
        }}
        items={[
          { id: 'applications', label: 'Приложения' },
          { id: 'sources', label: 'Подключения' },
          { id: 'demo', label: 'Учебные данные' },
        ]}
      />
      <div id="settings-panel" role="tabpanel" aria-labelledby={'settings-tab-' + tab}>
        {tab === 'applications' && !draft && (
          <section className="card">
            <div className="section-heading">
              <h2>Подключённые приложения</h2>
              <span className="muted">{apps.length} всего</span>
            </div>
            <div className="toolbar">
              <label>
                Поиск приложений
                <input
                  type="search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Название или идентификатор"
                />
              </label>
            </div>
            {loading && <p role="status">Загружаем приложения…</p>}
            <div className="list-scroll">
              {visibleApps.map((a) => (
                <div className="list-row" key={a.id}>
                  <strong>{a.name}</strong>
                  <span>
                    {a.id} · {Object.keys(a.catalog).length} типов · срок {a.ttl_seconds} с
                  </span>
                  <button
                    onClick={() => {
                      setDraft(structuredClone(a))
                      setCreating(false)
                    }}
                  >
                    Настроить
                  </button>
                </div>
              ))}
            </div>
            {!loading && !visibleApps.length && (
              <p className="empty">Приложения не найдены. Измените поиск или подключите новое.</p>
            )}
          </section>
        )}
        {tab === 'applications' && draft && (
          <form className="card" onSubmit={save}>
            <h2>Каталог приложения</h2><p className="muted">Тип действия определяет доступные поля. API — значение передаёт приложение; БД — читается по ключу из настроенного источника.</p>
            <div className="form-grid">
              <label>
                Идентификатор
                <input
                  required
                  disabled={!creating}
                  value={draft.id}
                  onChange={(e) => setDraft({ ...draft, id: e.target.value })}
                />
              </label>
              <label>
                Название
                <input
                  required
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                />
              </label>
              <DurationInput title="Срок решения" max={86400} value={draft.ttl_seconds} onChange={v=>setDraft({...draft,ttl_seconds:v??600})}/>
            </div>
            {Object.entries(draft.catalog).map(([action, config]) => (
              <fieldset key={action}>
                <legend>Тип события: {label(action)}</legend><ValueItems title="Статусы фактических событий" value={config.statuses??[]} onChange={v=>setDraft({...draft,catalog:{...draft.catalog,[action]:{...config,statuses:v.map(String)}}})}/><p className="small">Варианты этого приложения для настройки истории. Существующие статусы правил не удаляются.</p>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Поле</th>
                        <th>Тип</th>
                        <th>Источник</th>
                        <th>Обязательное</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(config.fields).map(([name, field]) => (
                        <tr key={name}>
                          <td>
                            <label>Понятное название<input value={field.label??''} placeholder={name} onChange={e=>changeField(action,name,{...field,label:e.target.value})}/></label>
                            <input
                              aria-label={'Имя поля ' + name}
                              required
                              defaultValue={name}
                              onChange={(e) => e.currentTarget.setCustomValidity('')}
                              onBlur={(e) => renameField(action, name, field, e.currentTarget)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  e.preventDefault()
                                  e.currentTarget.blur()
                                }
                              }}
                            />
                            <details><summary>Варианты значений</summary><ValueItems title={'Варианты '+name} value={field.values??[]} type={field.type} onChange={v=>changeField(action,name,{...field,values:v})}/><small>Подсказки конструктора. Новые значения не запрещаются автоматически.</small></details>
                          </td>
                          <td>
                            <select
                              aria-label={'Тип ' + name}
                              value={field.type}
                              onChange={(e) =>
                                changeField(action, name, {
                                  ...field,
                                  type: e.target.value as Field['type'],
                                })
                              }
                            >
                              <option value="string">Строка</option>
                              <option value="number">Число</option>
                              <option value="boolean">Логическое</option>
                            </select>
                          </td>
                          <td>
                            <select
                              aria-label={'Источник ' + name}
                              value={field.source}
                              onChange={(e) =>
                                changeField(action, name, {
                                  ...field,
                                  source: e.target.value as Field['source'],
                                })
                              }
                            >
                              <option value="API">API · из запроса</option>
                              <option value="DB">БД · из источника</option>
                            </select>
                          </td>
                          <td>
                            <input
                              aria-label={'Обязательное ' + name}
                              type="checkbox"
                              checked={field.required}
                              onChange={(e) =>
                                changeField(action, name, { ...field, required: e.target.checked })
                              }
                            />
                          </td>
                          <td>
                            <button type="button" onClick={() => removeField(action, name)}>
                              Убрать
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <button type="button" onClick={() => addField(action)}>
                  + Поле
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const catalog = structuredClone(draft.catalog)
                    delete catalog[action]
                    setDraft({ ...draft, catalog })
                  }}
                >
                  Убрать тип события
                </button>
              </fieldset>
            ))}
            <div className="toolbar">
              <label>
                Новый тип события
                <input value={newEvent} onChange={(e) => setNewEvent(e.target.value)} />
              </label>
              <button
                type="button"
                disabled={!newEvent || Boolean(draft.catalog[newEvent])}
                onClick={() => {
                  setDraft({
                    ...draft,
                    catalog: {
                      ...draft.catalog,
                      [newEvent]: {
                        fields: { object_id: { type: 'string', source: 'API', required: true } },
                      },
                    },
                  })
                  setNewEvent('')
                }}
              >
                Добавить тип
              </button>
            </div>
            <div className="actions">
              <button className="primary" disabled={pending}>{pending ? 'Сохраняем…' : 'Сохранить каталог'}</button>
              <button type="button" onClick={() => setDraft(null)}>
                Закрыть
              </button>
            </div>
          </form>
        )}
        <Connections apps={apps} onSaved={load} active={tab==='sources'}/>
        {tab === 'demo' && (
          <section className="card danger-zone">
            <h2>Вернуть учебное демо</h2>
            <p className="muted">
              Текущие заявки сохранятся в архиве базы данных. Появятся исходные учебные заявки,
              незавершённые попытки отменятся. Журнал и настройки правил останутся; новая история
              расчётов начнётся с момента возврата. Введите «Вернуть учебное демо» для выполнения.
            </p>
            <div className="toolbar">
              <label>
                Подтверждение возврата
                <input value={resetPhrase} onChange={(e) => setResetPhrase(e.target.value)} />
              </label>
              <button
                disabled={resetPhrase !== 'Вернуть учебное демо'}
                onClick={async () => {
                  if (busy.current) return
                  busy.current=true;setPending(true)
                  setError('')
                  try {
                    const result = await api<{ message: string }>('/demo/reset', 'POST', {
                      confirmation: resetPhrase,
                    })
                    setNotice(result.message)
                    setResetPhrase('')
                  } catch (e) {
                    setError((e as Error).message)
                  } finally {
                    busy.current=false;setPending(false)
                  }
                }}
              >
                Вернуть демо
              </button>
            </div>
          </section>
        )}
      </div>
    </>
  )
}
