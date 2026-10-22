import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Navigate } from 'react-router'
import { api, label, type Application, type Decision, type EventView, type JournalItem } from '../api'
import { DecisionCard } from '../components/DecisionCard'
import { SidePanel } from '../components/SidePanel'
import { useSession } from '../session'
import { Values } from '../components/Values'

const pageSize = 50
const date = (value: string) => new Date(value).toLocaleString('ru-RU')
function Events({ rows }: { rows: EventView[] }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Время / событие</th>
            <th>Действие / инициатор</th>
            <th>Результат</th>
            <th>Значения</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.event_id}>
              <td>
                {date(row.event_at)}
                <small>{row.event_id}</small>
              </td>
              <td>
                {label(row.action)}
                <small>{row.actor}</small>
              </td>
              <td>{label(row.status)}</td>
              <td>
                <details>
                  <summary>Показать значения</summary>
                  <Values values={row.fields}/>
                </details>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
export function JournalPage() {
  const { account } = useSession()
  const [rows, setRows] = useState<JournalItem[]>([])
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<Decision | null>(null)
  const [filters, setFilters] = useState({
    application_id: '',
    action: '',
    initiator: '',
    state: account?.role === 'specialist' ? 'PENDING_REVIEW' : '',
    operation_id: '',
    start: '',
    end: '',
  })
  const [error, setError] = useState('')
  const [comment, setComment] = useState('')
  const [pending, setPending] = useState(false)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [apps, setApps] = useState<Application[]>([])
  const [applied, setApplied] = useState(filters)
  const [returnFocus, setReturnFocus] = useState<HTMLElement | null>(null)
  const revision = useRef(0)
  const busy = useRef(false)
  const selectedId=selected?.id
  const [refreshError,setRefreshError]=useState('')
  useEffect(() => {
    if (account && ['admin', 'specialist'].includes(account.role)) {
      const controller = new AbortController()
      const current = ++revision.current
      Promise.all([api<JournalItem[]>('/journal?brief=true&limit=' + pageSize + (account.role === 'specialist' ? '&state=PENDING_REVIEW' : ''), 'GET', undefined, controller.signal), api<Application[]>('/admin/applications', 'GET', undefined, controller.signal)])
        .then(([decisions, applications]) => {if (current === revision.current) {setRows(decisions); setApps(applications)}})
        .catch((e) => {if (!controller.signal.aborted && current === revision.current) setError(e.message)})
        .finally(() => {if (!controller.signal.aborted && current === revision.current) setLoading(false)})
      return () => {controller.abort()}
    }
  }, [account])
  useEffect(() => {
    if (!selectedId) return
    const controller=new AbortController()
    let timer:ReturnType<typeof setTimeout>
    const refresh=async()=>{
      try {
        const fresh=await api<Decision>('/decisions/'+selectedId,'GET',undefined,controller.signal)
        if (!controller.signal.aborted) {
          setSelected(current=> current?.id === selectedId ? {...fresh,...((current.related_events?.length ?? 0) > (fresh.related_events?.length ?? 0) ? {related_events:current.related_events!} : {})} : current)
          setRefreshError('')
        }
      } catch(e) {if(!controller.signal.aborted) setRefreshError((e as Error).message)}
      finally {if(!controller.signal.aborted) timer=setTimeout(refresh,2000)}
    }
    timer=setTimeout(refresh,2000)
    return ()=>{controller.abort();clearTimeout(timer)}
  },[selectedId])
  if (!account) return <Navigate to="/login" replace />
  if (!['admin', 'specialist'].includes(account.role))
    return <p>Журнал доступен администратору и специалисту.</p>
  async function load(nextOffset = offset, nextFilters = applied) {
    const current = ++revision.current
    setError('')
    setLoading(true)
    const query = new URLSearchParams({ brief:'true', limit: String(pageSize), offset: String(nextOffset) })
    Object.entries(nextFilters).forEach(([key, value]) => {
      if (value)
        query.set(key, key === 'start' || key === 'end' ? new Date(value).toISOString() : value)
    })
    try {
      const result = await api<JournalItem[]>('/journal?' + query)
      if (current === revision.current) {setRows(result);setOffset(nextOffset);setApplied(nextFilters)}
    } catch (e) {
      if (current === revision.current) {setError((e as Error).message);setRows([])}
    } finally {
      if (current === revision.current) setLoading(false)
    }
  }
  async function filter(e: FormEvent) {
    e.preventDefault()
    if (filters.start && filters.end && filters.start > filters.end) {setError('Дата начала должна быть раньше даты окончания.');return}
    await load(0, filters)
  }
  async function select(id: string) {
    if (!selected && document.activeElement instanceof HTMLElement) setReturnFocus(document.activeElement)
    setComment('')
    setDetailLoading(true)
    try {
      setSelected(await api<Decision>('/decisions/' + id))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setDetailLoading(false)
    }
  }
  async function moreEvents() {
    if (!selected) return
    setPending(true)
    try {
      const extra = await api<EventView[]>(
        '/decisions/' +
          selected.id +
          '/related-events?offset=' +
          (selected.related_events?.length ?? 0),
      )
      setSelected({ ...selected, related_events: [...(selected.related_events ?? []), ...extra] })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPending(false)
    }
  }
  async function review(approve: boolean) {
    if (!selected || busy.current) return
    busy.current = true
    setPending(true)
    setError('')
    try {
      await api('/decisions/' + selected.id + '/review', 'POST', { approve, comment })
      await select(selected.id)
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      busy.current = false
      setPending(false)
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>{account.role === 'specialist' && applied.state === 'PENDING_REVIEW' ? 'Очередь рассмотрения' : 'Журнал проверок'}</h1>
          <p className="muted">Причины, проверенные значения и история переходов.</p>
        </div>
        <button onClick={() => load()}>Обновить</button>
      </div>
      {error && (
        <div className="error" role="alert" hidden={Boolean(selected)}>
          {error}
        </div>
      )}
      {loading && <p role="status">Загружаем проверки…</p>}
      {detailLoading && <p role="status">Открываем проверку…</p>}
      <div className="filter-tabs" role="group" aria-label="Представление журнала"><button aria-pressed={applied.state === 'PENDING_REVIEW'} disabled={loading} onClick={() => {const next={...filters,state:'PENDING_REVIEW'};setFilters(next);void load(0,next)}}>Ожидают специалиста</button><button aria-pressed={!applied.state} disabled={loading} onClick={() => {const next={...filters,state:''};setFilters(next);void load(0,next)}}>Все проверки</button></div>
      <form className="card journal-filters" onSubmit={filter}>
        <div className="toolbar">
          <label>Приложение<select aria-label="Приложение" value={filters.application_id} onChange={e => setFilters({...filters,application_id:e.target.value,action:''})}><option value="">Все приложения</option>{apps.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
          <label>Действие<select aria-label="Действие" value={filters.action} onChange={e => setFilters({...filters,action:e.target.value})}><option value="">Все действия</option>{Array.from(new Set(apps.filter(a => !filters.application_id || a.id === filters.application_id).flatMap(a => Object.keys(a.catalog)))).map(action => <option key={action} value={action}>{label(action)}</option>)}</select></label>
          <label>
            Состояние
            <select
              value={filters.state}
              onChange={(e) => setFilters({ ...filters, state: e.target.value })}
            >
              <option value="">Все состояния</option>
              {[
                'PENDING_REVIEW',
                'PENDING_CONFIRMATION',
                'APPROVED',
                'REJECTED',
                'CANCELLED',
                'EXPIRED',
              ].map((s) => (
                <option key={s} value={s}>
                  {label(s)}
                </option>
              ))}
            </select>
          </label>
          <button className="primary" disabled={loading}>
            Применить фильтры
          </button>
        </div>
        <details>
          <summary>Дополнительные фильтры</summary>
          <div className="form-grid">
            {Object.entries({
              initiator: 'Инициатор',
              operation_id: 'Идентификатор операции',
              start: 'С даты',
              end: 'До даты',
            }).map(([key, text]) => (
              <label key={key}>
                {text}
                <input
                  type={key === 'start' || key === 'end' ? 'datetime-local' : 'text'}
                  value={filters[key as keyof typeof filters]}
                  onChange={(e) => setFilters({ ...filters, [key]: e.target.value })}
                />
              </label>
            ))}
          </div>
        </details>
      </form>
      {JSON.stringify(applied) !== JSON.stringify(filters) && <p className="filter-hint" role="status">Фильтры изменены. Нажмите «Применить фильтры», чтобы обновить результаты.</p>}
      <section className="card table-card">
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Время</th>
                <th>Операция</th>
                <th>Действие / инициатор</th>
                <th>Решение</th>
                <th>Сработавшие правила</th>
                <th>Выполнение</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {!loading && rows.map((r) => (
                <tr key={r.id}>
                  <td className="nowrap">{date(r.created_at)}</td>
                  <td>
                    <strong>{r.operation_title ?? apps.find(a=>a.id === r.application_id)?.name ?? r.application_id}</strong>
                    <small className="id-ref" title={r.operation_id}>
                      {r.operation_id}
                    </small>
                  </td>
                  <td>
                    {label(r.action)}
                    <small>{r.initiator}</small>
                  </td>
                  <td>
                    <span className={'badge ' + r.state}>{label(r.state)}</span>
                  </td>
                  <td>
                    {r.reasons
                      .filter((reason) => reason.matched || reason.error)
                      .map((reason) => reason.message ?? reason.name)
                      .join(', ') || 'Нет ограничений'}
                  </td>
                  <td>{r.executed_at ? 'Сохранено' : 'Не выполнено'}</td>
                  <td>
                    <button disabled={loading || detailLoading} onClick={() => select(r.id)}>
                      Подробнее
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && !rows.length && (
            <p className="empty">По этим фильтрам проверки не найдены.</p>
          )}
        </div>
        <div className="pagination">
          <span>До {pageSize} проверок на странице</span>
          <div>
            <button
              disabled={!offset || loading}
              onClick={() => load(Math.max(0, offset - pageSize))}
            >
              Предыдущие
            </button>
            <span>Страница {offset / pageSize + 1}</span>
            <button
              disabled={rows.length < pageSize || loading}
              onClick={() => load(offset + pageSize)}
            >
              Следующие
            </button>
          </div>
        </div>
      </section>
      {selected && (
        <SidePanel returnFocus={returnFocus} title="Проверка операции" onClose={() => setSelected(null)}>
          {refreshError && <div className="error" role="alert">Не удалось обновить состояние: {refreshError}</div>}
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          <DecisionCard decision={selected}>
            {account.role === 'specialist' && selected.state === 'PENDING_REVIEW' && (
              <>
                <label>
                  Комментарий специалиста
                  <textarea value={comment} onChange={(e) => setComment(e.target.value)} />
                </label>
                <div className="actions">
                  <button className="primary" disabled={pending} onClick={() => review(true)}>
                    Одобрить
                  </button>
                  <button disabled={pending} onClick={() => review(false)}>
                    Отклонить
                  </button>
                </div>
                <p className="muted">
                  Если требуется подтверждение инициатора, оно остаётся обязательным после
                  одобрения.
                </p>
              </>
            )}
          </DecisionCard>
          <section className="card">
            <h2>История решения</h2>
            {selected.transitions?.map((t, i) => (
              <div className="history-row" key={i}>
                <strong>{label(t.after)}</strong> · {t.actor} · {date(t.at)}
                <p>{t.comment}</p>
              </div>
            ))}
            <h3>Фактические события этой операции</h3>
            {selected.events?.length ? (
              <Events rows={selected.events} />
            ) : (
              <p className="muted">Событие о выполнении ещё не доставлено.</p>
            )}
            <h3>События, использованные правилами ({selected.related_events_count ?? 0})</h3>
            {selected.related_events?.length ? (
              <Events rows={selected.related_events} />
            ) : (
              <p className="muted">В этой проверке исторические события не использовались.</p>
            )}
            {(selected.related_events_count ?? 0) > (selected.related_events?.length ?? 0) && (
              <button disabled={pending} onClick={moreEvents}>
                Показать ещё события
              </button>
            )}
          </section>
        </SidePanel>
      )}
    </>
  )
}
