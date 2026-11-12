import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Navigate } from 'react-router'
import { api, label, type Application, type Rule, type RuleTemplate, type Watchlist } from '../api'
import { RuleBuilder } from '../components/RuleBuilder'
import { TabBar } from '../components/TabBar'
import { baseNode, kinds } from '../rule-presets'
import { useSession } from '../session'
import { mechanismHelp, ruleText } from '../rule-text'
import {ValueItems} from '../components/FormControls'
import {useMemoryDraft} from '../drafts'
import {ruleIssues} from '../rule-validation'
export function RulesPage() {
  const { account } = useSession()
  const [apps, setApps] = useState<Application[]>([])
  const [appId, setAppId] = useMemoryDraft('rules-app', 'demo')
  const [rules, setRules] = useState<Rule[]>([])
  const [lists, setLists] = useState<Watchlist[]>([])
  const [draft, setDraft] = useMemoryDraft<Rule | null>('rule-draft', null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [pending, setPending] = useState(false)
  const [listName, setListName] = useState('')
  const [listValues, setListValues] = useState<Array<string|number|boolean>>([])
  const [listId, setListId] = useState<string | null>(null)
  const [listType, setListType] = useState('string')
  const [templates, setTemplates] = useState<RuleTemplate[]>([])
  const [editingTemplate, setEditingTemplate] = useMemoryDraft('rule-is-template', false)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState('rules')
  const [search, setSearch] = useState('')
  const [ruleState, setRuleState] = useState('enabled')
  const [actionFilter, setActionFilter] = useState('')
  const busy = useRef(false)
  const appDrafts = useRef(new Map<string,{draft:Rule|null;editingTemplate:boolean;listId:string|null;listName:string;listValues:Array<string|number|boolean>;listType:string}>())
  const load = useCallback(async () => {
    const [a, r, l, t] = await Promise.all([
      api<Application[]>('/admin/applications'),
      api<Rule[]>('/admin/rules?application_id=' + appId),
      api<Watchlist[]>('/admin/watchlists?application_id=' + appId),
      api<RuleTemplate[]>('/admin/templates?application_id=' + appId),
    ])
    setApps(a)
    setRules(r)
    setLists(l)
    setTemplates(t)
    setLoading(false)
  }, [appId])
  useEffect(() => {
    let active = true
    if (account?.role === 'admin')
      void Promise.all([
        api<Application[]>('/admin/applications'),
        api<Rule[]>('/admin/rules?application_id=' + appId),
        api<Watchlist[]>('/admin/watchlists?application_id=' + appId),
        api<RuleTemplate[]>('/admin/templates?application_id=' + appId),
      ])
        .then(([a, r, l, t]) => {
          if (!active) return
          setApps(a)
          setRules(r)
          setLists(l)
          setTemplates(t)
          setLoading(false)
        })
        .catch((e) => { if (active) setError(e.message) })
        .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [account, appId])
  if (!account) return <Navigate to="/login" replace />
  if (account.role !== 'admin') return <p>Настройка правил доступна администратору.</p>
  const app = apps.find((a) => a.id === appId)
  const issues=draft&&app?[...ruleIssues(draft.expression,app,draft.action),...(draft.exception?ruleIssues(draft.exception,app,draft.action):[])]:[]
  function closeDraft() {
    appDrafts.current.delete(appId)
    setDraft(null)
  }
  function fresh(kind = 'field') {
    setTab('rules')
    setEditingTemplate(false)
    if (!app) return
    const action = Object.keys(app.catalog)[0]
    if (!action) return
    setDraft({
      id: '',
      application_id: app.id,
      name: '',
      action,
      expression: baseNode(kind, app, action),
      exception: null,
      reaction: 'REVIEW',
      enabled: true,
      version: 1,
    })
  }
  function fromTemplate(template: RuleTemplate, edit: boolean) {
    if (template.builtin) {
      fresh(template.kind)
      return
    }
    if (!template.action || !template.expression || !template.reaction || !template.application_id)
      return
    setTab('rules')
    setEditingTemplate(edit)
    setDraft({
      id: edit ? template.id : '',
      name: template.name + (edit ? '' : ' · копия'),
      action: template.action,
      expression: structuredClone(template.expression),
      application_id: template.application_id,
      reaction: template.reaction,
      exception: structuredClone(template.exception ?? null),
      enabled: true,
      version: template.version ?? 1,
    })
  }
  async function run(task: () => Promise<void>) {
    if (busy.current) return
    busy.current = true
    setError('')
    setPending(true)
    try {
      await task()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      busy.current = false
      setPending(false)
    }
  }
  async function save(e: FormEvent) {
    e.preventDefault()
    if (!draft) return
    if(issues.length){setError(issues.join('. '));return}
    await run(async () => {
      const { id, version, ...payload } = draft
      void version
      await api(
        (editingTemplate ? '/admin/templates' : '/admin/rules') + (id ? '/' + id : ''),
        id ? 'PUT' : 'POST',
        payload,
      )
      closeDraft()
      setTab(editingTemplate ? 'templates' : 'rules')
      setRuleState('all')
      setSearch('')
      await load()
      setNotice(
        editingTemplate
          ? 'Шаблон сохранён. Существующие правила не изменены.'
          : 'Правило сохранено. Следующие проверки используют эту версию.',
      )
    })
  }
  async function asTemplate() {
    if (!draft) return
    await run(async () => {
      const { id, version, ...payload } = draft
      void id
      void version
      await api('/admin/templates', 'POST', payload)
      await load()
      setNotice('Создан самостоятельный шаблон.')
    })
  }
  const visibleRules = rules
    .filter(
      (rule) =>
        (ruleState === 'all' || rule.enabled === (ruleState === 'enabled')) && (!actionFilter || rule.action === actionFilter) &&
        [rule.name, label(rule.action), ruleText(rule.expression)].some((value) =>
          value?.toLocaleLowerCase('ru').includes(search.toLocaleLowerCase('ru')),
        ),
    )
    .sort((a, b) => Number(b.enabled) - Number(a.enabled) || a.name.localeCompare(b.name, 'ru'))
  const applicationSelect = (
<label>
          Приложение
          <select
            aria-label="Приложение"
            value={appId} disabled={pending}
            onChange={(e) => {
              const nextId=e.target.value
              if(nextId === appId) return
              appDrafts.current.set(appId,{draft,editingTemplate,listId,listName,listValues,listType})
              const cached=appDrafts.current.get(nextId)
              setAppId(nextId)
              setLoading(true)
              setRules([]); setLists([]); setTemplates([]); setActionFilter('')
              setDraft(cached?.draft ?? null);setEditingTemplate(cached?.editingTemplate ?? false)
              setListId(cached?.listId ?? null);setListName(cached?.listName ?? '');setListValues(cached?.listValues ?? []);setListType(cached?.listType ?? 'string')
              setSearch('')
              setRuleState('enabled')
            }}
          >
            {apps.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
  )
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>{draft && tab === 'rules' ? editingTemplate ? 'Изменение шаблона' : draft.id ? 'Изменение правила' : 'Новое правило' : 'Правила антифрода'}</h1>
          <p className="muted">Условия, история и реакция в одном правиле.</p>
        </div>
        {!(draft && tab === 'rules') && <button className="primary" disabled={!app || pending} onClick={() => fresh()}>
          + Новое правило</button>}
        {draft && tab === 'rules' && <button type="button" onClick={closeDraft}>Закрыть</button>}
      </div>
      {loading && <p role="status">Загружаем правила…</p>}
      {error && !(draft && tab === 'rules') && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="notice" role="status">
          {notice}
        </div>
      )}
      {tab !== 'rules' && <div className="toolbar">{applicationSelect}</div>}
      <TabBar
        id="rules"
        label="Разделы правил"
        active={tab}
        onChange={setTab}
        items={[
          { id: 'rules', label: 'Правила' },
          { id: 'templates', label: 'Шаблоны' },
          { id: 'lists', label: 'Списки наблюдения' },
        ]}
      />
      <div role="tabpanel" id="rules-panel" aria-labelledby={'rules-tab-' + tab}>
        {!draft && tab === 'rules' && (
          <section className="card table-card">
            <div className="section-heading">
              <h2>Активные настройки</h2>
              <span className="muted">{rules.filter((r) => r.enabled).length} включено</span>
            </div>
            <div className="table-tools">{applicationSelect}
              <label>
                Поиск правил
                <input
                  type="search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Название, действие или механизм"
                />
              </label>
              <label className="filter-select">
                Действие правила
                <select value={actionFilter} onChange={e => setActionFilter(e.target.value)}><option value="">Все действия</option>{Object.keys(app?.catalog ?? {}).map(action => <option key={action} value={action}>{label(action)}</option>)}</select>
              </label>
              <label className="filter-select">
                Состояние правил
                <select value={ruleState} onChange={(e) => setRuleState(e.target.value)}>
                  <option value="enabled">Включённые</option>
                  <option value="all">Все правила</option>
                  <option value="disabled">Отключённые</option>
                </select>
              </label>
              <p>
                {visibleRules.length} из {rules.length}
              </p>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Правило</th>
                    <th>Действие</th>
                    <th>Реакция</th>
                    <th>Состояние</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {visibleRules.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <strong>{r.name}</strong>
                        <small className="rule-description">{ruleText(r.expression)}</small>
                        <small>{app?.name} · версия {r.version}</small>
                      </td>
                      <td>{label(r.action)}</td>
                      <td><span className={'badge ' + r.reaction}>{label(r.reaction)}</span></td>
                      <td>
                        <span className={'badge ' + (r.enabled ? 'enabled' : 'disabled')}>
                          {r.enabled ? 'Включено' : 'Отключено'}
                        </span>
                      </td>
                      <td>
                        <button
                          onClick={() => {
                            setEditingTemplate(false)
                            setDraft(structuredClone(r))
                          }}
                        >
                          Настроить
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!loading && !visibleRules.length && (
                <p className="empty">
                  {rules.length
                    ? 'По выбранным условиям правил нет. Измените поиск или состояние.'
                    : 'Правил пока нет. Создайте правило или выберите механизм во вкладке «Шаблоны».'}
                </p>
              )}
            </div>
          </section>
        )}
        {tab === 'templates' && (
          <section className="card">
            <h2>Шаблоны механизмов</h2>
            <p className="muted">
              Шаблон создаёт самостоятельное правило. Параметры можно изменить.
            </p>
            <div className="template-grid">
              {Object.entries(kinds)
                .filter(([k]) => !['all', 'any', 'not'].includes(k))
                .map(([k, name]) => (
                  <button key={k} disabled={!app} onClick={() => fresh(k)}>
                    <strong>{name}</strong><small>{mechanismHelp[k]}</small>
                  </button>
                ))}
            </div>
          </section>
        )}
        {tab === 'templates' && templates.filter((t) => !t.builtin).length > 0 && (
          <section className="card">
            <h2>Сохранённые шаблоны</h2>
            {templates
              .filter((t) => !t.builtin)
              .map((t) => (
                <div className="list-row" key={t.id}>
                  <strong>{t.name}</strong>
                  <span>Версия {t.version}</span>
                  <button onClick={() => fromTemplate(t, false)}>Создать правило</button>
                  <button onClick={() => fromTemplate(t, true)}>Изменить шаблон</button>
                  <button
                    onClick={() =>
                      run(async () => {
                        await api('/admin/templates/' + t.id, 'DELETE')
                        await load()
                      })
                    }
                  >
                    Удалить
                  </button>
                </div>
              ))}
          </section>
        )}
        {draft && app && tab === 'rules' && (
          <form className="rule-editor" onSubmit={save} aria-busy={pending}>
            <section className="card editor-main">
            {error && <div className="error" role="alert">{error}</div>}
            <h3>1. Действие и реакция</h3>
            <div className="form-grid">{applicationSelect}
              <label>
                Название
                <input
                  required
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                />
              </label>
              <label>
                Проверяемое действие
                <select
                  aria-label="Проверяемое действие"
                  value={draft.action}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      action: e.target.value,

                    })
                  }
                >
                  {Object.keys(app.catalog).map((n) => (
                    <option key={n} value={n}>
                      {label(n)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Реакция
                <select
                  aria-label="Реакция"
                  value={draft.reaction}
                  onChange={(e) => setDraft({ ...draft, reaction: e.target.value })}
                >
                  {['BLOCK', 'REVIEW', 'CONFIRM', 'LOG'].map((r) => (
                    <option key={r} value={r}>
                      {label(r)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={draft.enabled}
                  onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
                />
                Правило включено
              </label>
            </div>
            <h3>2. Условия срабатывания</h3>
            {issues.length>0&&<div className="warning" role="alert"><strong>Проверьте совместимость перед сохранением</strong><ul>{issues.map((issue,i)=><li key={i}>{issue}</li>)}</ul><p>Существующие условия сохранены. Исправьте перечисленные настройки.</p></div>}
            <RuleBuilder
              node={draft.expression}
              app={app}
              action={draft.action}
              lists={lists}
              onChange={(expression) => setDraft({ ...draft, expression })}
            />
            <details open={Boolean(draft.exception)}><summary>Дополнительно: исключение для правила</summary>
            <label className="check">
              <input
                type="checkbox"
                checked={Boolean(draft.exception)}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    exception: e.target.checked ? baseNode('field', app, draft.action) : null,
                  })
                }
              />
              Исключение для этого правила
            </label>
            {draft.exception && (
              <RuleBuilder
                node={draft.exception}
                app={app}
                action={draft.action}
                lists={lists}
                onChange={(exception) => setDraft({ ...draft, exception })}
              />
            )}
            </details></section>
            <aside className="card editor-summary"><h2>Как сработает правило</h2><p className="rule-sentence">{ruleText(draft.expression)}</p><h3>Следующий этап</h3><span className={'badge ' + draft.reaction}>{label(draft.reaction)}</span><p>{({REVIEW:'Специалист рассмотрит операцию до выполнения.',CONFIRM:'Инициатор отдельно подтвердит проверенные значения.',BLOCK:'Действие не будет выполнено.',LOG:'Срабатывание сохранится без остановки действия.'} as Record<string,string>)[draft.reaction]}</p><hr/><p>{draft.enabled ? '● Правило включено' : '○ Правило отключено'}</p><small>Черновик сохраняется при переключении вкладок. Изменения применятся после сохранения.</small></aside>
            <div className="actions editor-actions">
              <button className="primary" disabled={pending}>
                {editingTemplate ? 'Сохранить шаблон' : 'Сохранить правило'}
              </button>
              {!editingTemplate && (
                <button type="button" disabled={pending} onClick={asTemplate}>
                  Сохранить как новый шаблон
                </button>
              )}
              <button type="button" onClick={closeDraft}>
                Отмена
              </button>
            </div>
          </form>
        )}
        {tab === 'lists' && (
          <section className="card">
            <h2>Списки наблюдения</h2>
            {lists.map((l) => (
              <div key={l.id} className="list-row">
                <strong>{l.name}</strong>
                <span>{l.values.map(String).join(', ')}</span>
                <button
                  onClick={() => {
                    setListId(l.id)
                    setListName(l.name)
                    setListValues(l.values)
                    setListType(
                      typeof l.values[0] === 'number'
                        ? 'number'
                        : typeof l.values[0] === 'boolean'
                          ? 'boolean'
                          : 'string',
                    )
                  }}
                >
                  Изменить
                </button>
                <button
                  onClick={() =>
                    run(async () => {
                      await api('/admin/watchlists/' + l.id, 'DELETE')
                      await load()
                    })
                  }
                >
                  Удалить
                </button>
              </div>
            ))}
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void run(async () => {
                  const values = listValues
                  await api(
                    '/admin/watchlists' + (listId ? '/' + listId : ''),
                    listId ? 'PUT' : 'POST',
                    { name: listName, values, ...(listId ? {} : { application_id: appId }) },
                  )
                  setListName('')
                  setListValues([])
                  setListId(null)
                  await load()
                })
              }}
              className="toolbar"
            >
              <label>
                Название
                <input required value={listName} onChange={(e) => setListName(e.target.value)} />
              </label>
              <label>
                Тип значений
                <select
                  aria-label="Тип значений"
                  value={listType}
                  onChange={(e) => setListType(e.target.value)}
                >
                  <option value="string">Строки</option>
                  <option value="number">Числа</option>
                  <option value="boolean">Логические</option>
                </select>
              </label>
              <ValueItems title="Элементы списка" value={listValues} type={listType} onChange={setListValues}/>
              <button disabled={pending}>{listId ? 'Сохранить список' : 'Добавить список'}</button>
              {listId && (
                <button
                  type="button"
                  onClick={() => {
                    setListId(null)
                    setListName('')
                    setListValues([])
                  }}
                >
                  Отмена
                </button>
              )}
            </form>
          </section>
        )}
      </div>
    </>
  )
}
