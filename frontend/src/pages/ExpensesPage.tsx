import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Navigate } from 'react-router'
import { api, label, money, type Decision, type Expense, type ExpensePage } from '../api'
import { DecisionCard } from '../components/DecisionCard'
import { SidePanel } from '../components/SidePanel'
import { useSession } from '../session'

const initial = () => ({ amount: '500.00', recipient: '', receipt: '', vendor: '', purchase_date: new Date().toLocaleDateString('sv-SE'), title: '', category: 'other' })
const requestLabel = (status: string) => status === 'APPROVED' ? 'Согласовано руководителем' : label(status)
const actionLabel: Record<string, string> = { submit: 'Отправить на согласование', approve: 'Согласовать', reject: 'Отклонить заявку', pay: 'Отметить условную выплату', export: 'Выгрузить реестр' }
type Execution = { request?: Expense; records?: Expense[]; event_delivery?: { pending?: boolean } }
type Result = { decision: Decision; execution: Execution | null }

function nextStep(row: Expense, role: string) {
  if (row.status === 'PAID') return 'Условная выплата сохранена'
  const d = row.decision
  if (d && !d.executed_at) {
    if (d.state === 'PENDING_REVIEW') return 'Ожидается специалист антифрода'
    if (d.state === 'PENDING_CONFIRMATION') return 'Подтвердите параметры действия'
    if (d.state === 'APPROVED') return 'Можно завершить: ' + label(d.action).toLocaleLowerCase('ru')
    if (['EXPIRED', 'CANCELLED', 'REJECTED'].includes(d.state)) return (d.reasons[0] ?? label(d.state)) + '. Откройте проверку для разбора'
  }
  if (row.status === 'SUBMITTED') return role === 'manager' ? 'Примите решение по расходу' : 'Следующий этап — решение руководителя'
  if (row.status === 'APPROVED') return role === 'accountant' ? 'Можно отметить условную выплату' : 'Следующий этап — бухгалтер'
  return 'Автор может изменить и отправить заявку'
}

export function ExpensesPage() {
  const { account } = useSession()
  const [resultPage, setPage] = useState<ExpensePage | null>(null)
  const [loadedQuery, setLoadedQuery] = useState('')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [queue, setQueue] = useState(account?.role === 'manager' ? 'business' : account?.role === 'accountant' ? 'payment' : 'all')
  const [offset, setOffset] = useState(0)
  const [form, setForm] = useState(initial)
  const [editing, setEditing] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [selected, setSelected] = useState<Expense | null>(null)
  const [returnFocus, setReturnFocus] = useState<HTMLElement | null>(null)
  const [decision, setDecision] = useState<Decision | null>(null)
  const [exportDecision, setExportDecision] = useState<Decision | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const attempts = useRef(new Map<string, string>())
  const revision = useRef(0)
  const selectedId = selected?.id
  const exportId = exportDecision?.id
  const allowed = account && ['employee', 'manager', 'accountant'].includes(account.role)
  const query = new URLSearchParams({ limit: '50', offset: String(offset), search, status, queue }).toString()
  const loading = loadedQuery !== query
  const page = loading ? null : resultPage
  const load = useCallback(async (signal?: AbortSignal) => {
    const current = ++revision.current
    const result = await api<ExpensePage>('/demo/requests/page?' + query, 'GET', undefined, signal)
    if (current === revision.current && !signal?.aborted) { setPage(result); setLoadedQuery(query) }
  }, [query])
  useEffect(() => {
    if (!allowed) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const refresh = async () => {
      try { await load(controller.signal) } catch (e) { if (!controller.signal.aborted) { setError((e as Error).message); setPage(null); setLoadedQuery(query) } }
      finally { if (!controller.signal.aborted) timer = setTimeout(refresh, 5000) }
    }
    timer = setTimeout(refresh, 250)
    return () => { controller.abort(); clearTimeout(timer) }
  }, [allowed, account?.id, load, query])
  useEffect(() => {
    const id = exportId ?? selectedId
    if (!id || !account) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const refresh = async () => {
      try {
        if (exportId) {
          const result = await api<Decision>('/decisions/' + id, 'GET', undefined, controller.signal)
          if (!controller.signal.aborted) setExportDecision(result)
        } else {
          const row = await api<Expense>('/demo/requests/' + id, 'GET', undefined, controller.signal)
          const result = row.decision ? await api<Decision>('/decisions/' + row.decision.id, 'GET', undefined, controller.signal) : null
          if (!controller.signal.aborted) { setSelected(row); setDecision(result) }
        }
      } catch (e) { if (!controller.signal.aborted) setError((e as Error).message) }
      finally { if (!controller.signal.aborted) timer = setTimeout(refresh, 2000) }
    }
    void refresh()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [selectedId, exportId, account])
  if (!account) return <Navigate to="/login" replace />
  if (!allowed) return <p>Демо доступно сотруднику, руководителю и бухгалтеру.</p>

  async function run(task: () => Promise<void>) {
    setPending(true); setError(''); setNotice('')
    try { await task() } catch (e) { setError((e as Error).message) } finally { setPending(false) }
  }
  function download(records: Expense[]) {
    const csv = ['id;автор;сумма;получатель;статус', ...records.map(row => [row.id, row.author, row.amount, row.recipient, row.status].map(v => '"' + String(v).replaceAll('"', '""') + '"').join(';'))].join('\r\n')
    const url = URL.createObjectURL(new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a'); link.href = url; link.download = 'реестр.csv'; link.click(); URL.revokeObjectURL(url)
  }
  async function showResult(result: Result, row?: Expense) {
    if (row) { setSelected(result.execution?.request ?? row); setDecision(result.decision) }
    else { setSelected(null); setDecision(null); setExportDecision(result.decision) }
    if (result.execution) {
      if (result.execution.records) download(result.execution.records)
      setNotice(result.execution.event_delivery?.pending ? 'Действие сохранено. Доставка события задержана; повтор не выполнит действие ещё раз.' : actionLabel[result.decision.action] + ': действие сохранено.')
    } else setNotice('Результат проверки сохранён. Причина и следующий шаг — в карточке.')
    await load()
  }
  async function act(row: Expense, action: string) {
    if (!selected && document.activeElement instanceof HTMLElement) setReturnFocus(document.activeElement)
    const key = row.id + ':' + row.version + ':' + action
    if (!attempts.current.has(key)) attempts.current.set(key, crypto.randomUUID())
    const result = await api<Result>('/demo/requests/' + row.id + '/action', 'POST', { action, version: row.version, operation_id: attempts.current.get(key) })
    if (['REJECTED', 'CANCELLED', 'EXPIRED'].includes(result.decision.state)) attempts.current.delete(key)
    await showResult(result, row)
  }
  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const send = (e.nativeEvent as SubmitEvent).submitter?.getAttribute('value') === 'send'
    await run(async () => {
      const row = await api<Expense>('/demo/requests' + (editing ? '/' + editing : ''), editing ? 'PUT' : 'POST', form)
      setEditing(row.id)
      if (send) await act(row, 'submit')
      else { await load(); setNotice('Черновик сохранён. Затем отправьте его на согласование.') }
      setShowForm(false); setEditing(null); setForm(initial())
    })
  }
  async function open(row: Expense) {
    if (document.activeElement instanceof HTMLElement) setReturnFocus(document.activeElement)
    await run(async () => {
      const full = await api<Expense>('/demo/requests/' + row.id)
      const result = full.decision ? await api<Decision>('/decisions/' + full.decision.id) : null
      setSelected(full); setDecision(result)
    })
  }
  async function finish(current: Decision, approve?: boolean) {
    await run(async () => {
      let result = current
      if (approve !== undefined) result = await api<Decision>('/demo/decisions/' + current.id + '/confirm', 'POST', { approve, operation_id: current.operation_id, checked_values: current.checked_values })
      if (result.state === 'APPROVED') {
        const execution = await api<Execution>('/demo/execute', 'POST', { operation_id: result.operation_id, decision_id: result.id })
        result = await api<Decision>('/decisions/' + result.id)
        await showResult({ decision: result, execution }, current.action === 'export' ? undefined : selected ?? undefined)
      } else {
        if (current.action === 'export') setExportDecision(result); else setDecision(result)
        setNotice('Попытка отменена. Действие не выполнено.'); await load()
      }
    })
  }
  async function cancel(current: Decision) {
    await run(async () => {
      const result = await api<Decision>('/demo/decisions/' + current.id + '/cancel', 'POST')
      if (current.action === 'export') setExportDecision(result); else setDecision(result)
      attempts.current.clear(); await load()
    })
  }
  async function exportRegistry() {
    if (document.activeElement instanceof HTMLElement) setReturnFocus(document.activeElement)
    await run(async () => {
      const key = 'export'
      if (!attempts.current.has(key)) attempts.current.set(key, crypto.randomUUID())
      const result = await api<Result>('/demo/export/action', 'POST', { operation_id: attempts.current.get(key) })
      if (result.execution || ['REJECTED', 'CANCELLED', 'EXPIRED'].includes(result.decision.state)) attempts.current.delete(key)
      await showResult(result)
    })
  }
  function controls(current: Decision) {
    if (current.executed_at) return current.action === 'export' ? <button disabled={pending} onClick={() => finish(current)}>Скачать сохранённый реестр</button> : <p>Действие сохранено в базе. Следующий бизнес-этап выполняет соответствующая роль.</p>
    return <div className="actions">
      {current.state === 'APPROVED' && <button className="primary" disabled={pending} onClick={() => finish(current)}>Завершить: {label(current.action).toLocaleLowerCase('ru')}</button>}
      {current.state === 'PENDING_CONFIRMATION' && <><button className="primary" disabled={pending} onClick={() => finish(current, true)}>Подтверждаю эти значения и действие</button><button disabled={pending} onClick={() => finish(current, false)}>Отказаться</button></>}
      {['APPROVED', 'PENDING_REVIEW', 'PENDING_CONFIRMATION'].includes(current.state) && <button disabled={pending} onClick={() => cancel(current)}>Отменить попытку</button>}
    </div>
  }
  const actions = (row: Expense) => {
    if (row.decision && !row.decision.executed_at && ['APPROVED', 'PENDING_REVIEW', 'PENDING_CONFIRMATION'].includes(row.decision.state)) return []
    return [...(row.author === account.id && ['DRAFT', 'REJECTED'].includes(row.status) ? ['submit'] : []), ...(account.role === 'manager' && row.author !== account.id && row.status === 'SUBMITTED' ? ['approve', 'reject'] : []), ...(account.role === 'accountant' && row.status === 'APPROVED' && row.approved_version === row.version ? ['pay'] : [])]
  }
  return <>
    <div className="page-heading"><div><h1>Возмещение расходов</h1><p className="muted">{account.role === 'employee' ? 'Создайте заявку и отправьте руководителю. Проверка правил выполняется автоматически.' : account.role === 'manager' ? 'Согласуйте расход или отклоните его. Правила антифрода проверяются автоматически; специалист нужен только при соответствующей реакции.' : 'Отметьте условную выплату по согласованной заявке. Сначала система проверит правила и обязательные этапы.'}</p></div><div className="actions">
      {account.role === 'accountant' && <button disabled={pending} onClick={exportRegistry}>Выгрузить реестр</button>}
      <button className="primary" onClick={() => { if (!showForm) { setForm(initial()); setEditing(null) }; setShowForm(true) }}>+ Новая заявка</button>
    </div></div>
    {error && <div className="error" role="alert">{error}</div>}{notice && <div className="notice" role="status">{notice}</div>}
    <div className="filter-tabs" role="group" aria-label="Очередь заявок"><button aria-pressed={queue === 'all'} onClick={() => { setQueue('all'); setOffset(0) }}>Все доступные</button>{account.role === 'manager' && <button aria-pressed={queue === 'business'} onClick={() => { setQueue('business'); setOffset(0) }}>Нужно моё решение</button>}{account.role === 'accountant' && <button aria-pressed={queue === 'payment'} onClick={() => { setQueue('payment'); setOffset(0) }}>Готовы к выплате</button>}<button aria-pressed={queue === 'confirmation'} onClick={() => { setQueue('confirmation'); setOffset(0) }}>Нужно моё подтверждение</button><button aria-pressed={queue === 'review'} onClick={() => { setQueue('review'); setOffset(0) }}>Ожидают специалиста</button></div>
    <label>Статус заявки<select value={status} onChange={e => { setStatus(e.target.value); setOffset(0) }}><option value="">Все статусы</option>{['DRAFT', 'SUBMITTED', 'APPROVED', 'PAID', 'REJECTED'].map(value => <option key={value} value={value}>{requestLabel(value)}</option>)}</select></label>
    {showForm && <form className="card" onSubmit={save}><div className="section-heading"><h2>{editing ? 'Редактировать заявку' : 'Новая заявка'}</h2><button type="button" className="quiet" onClick={() => setShowForm(false)}>Закрыть</button></div><div className="form-grid">{Object.entries({ title: 'Назначение', amount: 'Сумма, ₽', recipient: 'Получатель', receipt: 'Номер чека', vendor: 'Продавец', purchase_date: 'Дата покупки' }).map(([key, name]) => <label key={key}>{name}<input required maxLength={key === 'title' ? 200 : key === 'purchase_date' || key === 'amount' ? undefined : 100} type={key === 'amount' ? 'number' : key === 'purchase_date' ? 'date' : 'text'} min={key === 'amount' ? '0.01' : undefined} step={key === 'amount' ? '.01' : undefined} value={form[key as keyof typeof form]} onChange={e => setForm({ ...form, [key]: e.target.value })}/></label>)}</div><div className="actions"><button type="submit" value="send" className="primary" disabled={pending}>Сохранить и отправить</button><button type="submit" value="draft" disabled={pending}>Сохранить черновик</button></div></form>}
    <section className="card table-card"><div className="section-heading"><h2>Заявки</h2><button disabled={pending} onClick={() => run(() => load())}>Обновить список</button></div><div className="table-tools"><label>Поиск заявок<input type="search" placeholder="Назначение, получатель, автор, чек или ID" value={search} onChange={e => { setSearch(e.target.value); setOffset(0) }}/></label><p role="status">{loading ? 'Загружаем заявки…' : 'Показано ' + (page?.items.length ?? 0) + ' из ' + (page?.total ?? 0)}</p></div><div className="table-scroll"><table><thead><tr><th>Назначение / автор</th><th className="money">Сумма</th><th>Статус заявки</th><th>Антифрод / следующий шаг</th><th>Действия</th></tr></thead><tbody>{page?.items.map(row => <tr key={row.id}><td><strong>{row.title}</strong><small>{row.author} · версия {row.version}</small></td><td className="money nowrap">{money(row.amount)}</td><td><span className={'badge ' + row.status}>{requestLabel(row.status)}</span></td><td>{row.decision && <small>{row.decision.executed_at ? 'Проверенное действие сохранено' : label(row.decision.state)}</small>}{nextStep(row, account.role)}</td><td><div className="row-actions"><button className="quiet" disabled={pending} onClick={() => open(row)}>Подробнее</button>{row.author === account.id && row.status !== 'PAID' && <button onClick={() => { setEditing(row.id); setForm({ amount: row.amount, recipient: row.recipient, receipt: row.receipt, vendor: row.vendor, purchase_date: row.purchase_date, title: row.title, category: row.category }); setShowForm(true) }}>Изменить</button>}{actions(row).map(action => <button key={action} disabled={pending} onClick={() => run(() => act(row, action))}>{actionLabel[action]}</button>)}</div></td></tr>)}</tbody></table>{!loading && !page?.items.length && <p className="empty">По выбранным условиям заявок нет.</p>}</div><div className="actions pagination"><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Назад</button><span>Страница {Math.floor(offset / 50) + 1}</span><button disabled={!page || offset + 50 >= page.total} onClick={() => setOffset(offset + 50)}>Далее</button></div></section>
    {selected && <SidePanel returnFocus={returnFocus} title={selected.title} onClose={() => { setSelected(null); setDecision(null) }}>{error && <div className="error" role="alert">{error}</div>}{notice && <div className="notice" role="status">{notice}</div>}<section className="card"><h2>Заявка: {requestLabel(selected.status)}</h2><p>{nextStep(selected, account.role)}</p><dl className="value-list">{Object.entries({ 'Сумма': money(selected.amount), 'Получатель': selected.recipient, 'Продавец': selected.vendor, 'Дата покупки': selected.purchase_date, 'Номер чека': selected.receipt, 'Автор': selected.author, 'Согласование руководителя': selected.approver ? selected.approver + ' · версия ' + selected.approved_version : 'Пока отсутствует', 'Условная выплата': selected.status === 'PAID' ? 'Сохранена в базе демо' : 'Не выполнена' }).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>{actions(selected).map(action => <button key={action} disabled={pending} onClick={() => run(() => act(selected, action))}>{actionLabel[action]}</button>)}</section>{decision && <DecisionCard decision={decision}>{controls(decision)}</DecisionCard>}<section className="card"><h2>История заявки</h2>{selected.history?.map((item, i) => <div className="history-row" key={i}><strong>{label(String(item.action))}</strong> · {String(item.actor)} · версия {String(item.version)} {item.at ? new Date(String(item.at)).toLocaleString('ru-RU') : ''}{item.before ? <details><summary>Значения до изменения</summary><pre>{JSON.stringify(item.before, null, 2)}</pre></details> : null}</div>)}</section></SidePanel>}
    {exportDecision && <SidePanel returnFocus={returnFocus} title="Выгрузка реестра" onClose={() => setExportDecision(null)}>{error && <div className="error" role="alert">{error}</div>}<DecisionCard decision={exportDecision}>{controls(exportDecision)}</DecisionCard></SidePanel>}
  </>
}
