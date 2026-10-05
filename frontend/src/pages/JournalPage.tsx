import {useEffect, useState, type FormEvent} from 'react'
import {Navigate} from 'react-router'
import {api, label, type Decision, type EventView} from '../api'
import {DecisionCard} from '../components/DecisionCard'
import {useSession} from '../session'

const pageSize = 50
const date = (value: string) => new Date(value).toLocaleString('ru-RU')
function Events({rows}: {rows: EventView[]}) {
  return <div className="table-scroll"><table><thead><tr><th>Время / событие</th><th>Действие / инициатор</th><th>Результат</th><th>Значения</th></tr></thead><tbody>{rows.map(row => <tr key={row.event_id}><td>{date(row.event_at)}<small>{row.event_id}</small></td><td>{label(row.action)}<small>{row.actor}</small></td><td>{label(row.status)}</td><td><details><summary>Показать значения</summary><dl className="value-list">{Object.entries(row.fields).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl></details></td></tr>)}</tbody></table></div>
}
export function JournalPage() {
  const {account} = useSession()
  const [rows, setRows] = useState<Decision[]>([])
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<Decision | null>(null)
  const [filters, setFilters] = useState({application_id: '', action: '', initiator: '', state: '', operation_id: '', start: '', end: ''})
  const [error, setError] = useState('')
  const [comment, setComment] = useState('')
  const [pending, setPending] = useState(false)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    if (account && ['admin', 'specialist'].includes(account.role)) {
      api<Decision[]>('/journal?limit=' + pageSize).then(setRows).catch(e => setError(e.message)).finally(() => setLoading(false))
    }
  }, [account])
  if (!account) return <Navigate to="/login" replace />
  if (!['admin', 'specialist'].includes(account.role)) return <p>Журнал доступен администратору и специалисту.</p>
  async function load(nextOffset = offset) {
    setError('')
    setLoading(true)
    const query = new URLSearchParams({limit: String(pageSize), offset: String(nextOffset)})
    Object.entries(filters).forEach(([key, value]) => {if (value) query.set(key, key === 'start' || key === 'end' ? new Date(value).toISOString() : value)})
    try {setRows(await api<Decision[]>('/journal?' + query)); setOffset(nextOffset)} catch (e) {setError((e as Error).message)} finally {setLoading(false)}
  }
  async function filter(e: FormEvent) {e.preventDefault(); await load(0)}
  async function select(id: string) {setComment(''); setLoading(true); try {setSelected(await api<Decision>('/decisions/' + id))} catch (e) {setError((e as Error).message)} finally {setLoading(false)}}
  async function moreEvents() {
    if (!selected) return
    setPending(true)
    try {
      const extra = await api<EventView[]>('/decisions/' + selected.id + '/related-events?offset=' + (selected.related_events?.length ?? 0))
      setSelected({...selected, related_events: [...(selected.related_events ?? []), ...extra]})
    } catch (e) {setError((e as Error).message)} finally {setPending(false)}
  }
  async function review(approve: boolean) {
    if (!selected) return
    setPending(true); setError('')
    try {await api('/decisions/' + selected.id + '/review', 'POST', {approve, comment}); await select(selected.id); await load()}
    catch (e) {setError((e as Error).message)} finally {setPending(false)}
  }
  return <>
    <div className="page-heading"><div><span className="eyebrow">ПРОЗРАЧНЫЕ РЕШЕНИЯ</span><h1>Журнал проверок</h1><p className="muted">Причины, проверенные значения и история переходов.</p></div><button onClick={() => load()}>Обновить</button></div>
    {error && <div className="error" role="alert">{error}</div>}
    {loading && <p role="status">Загружаем проверки…</p>}
    <form className="card form-grid" onSubmit={filter}>
      {Object.entries({application_id: 'Приложение', action: 'Действие', initiator: 'Инициатор', operation_id: 'Идентификатор операции', start: 'С даты', end: 'До даты'}).map(([key, text]) => <label key={key}>{text}<input type={key === 'start' || key === 'end' ? 'datetime-local' : 'text'} value={filters[key as keyof typeof filters]} onChange={e => setFilters({...filters, [key]: e.target.value})} /></label>)}
      <label>Состояние<select value={filters.state} onChange={e => setFilters({...filters, state: e.target.value})}><option value="">Все состояния</option>{['PENDING_REVIEW', 'PENDING_CONFIRMATION', 'APPROVED', 'REJECTED', 'CANCELLED', 'EXPIRED'].map(s => <option key={s} value={s}>{label(s)}</option>)}</select></label>
      <div className="actions"><button className="primary">Применить фильтры</button></div>
    </form>
    <section className="card table-card"><div className="table-scroll"><table><thead><tr><th>Время</th><th>Операция</th><th>Действие / инициатор</th><th>Решение</th><th>Сработавшие правила</th><th>Выполнение</th><th/></tr></thead><tbody>{rows.map(r => <tr key={r.id}><td className="nowrap">{date(r.created_at)}</td><td><strong>{r.application_id}</strong><small>{r.operation_id}</small></td><td>{label(r.action)}<small>{r.initiator}</small></td><td><span className={'badge ' + r.state}>{label(r.state)}</span></td><td>{r.reasons.filter(reason => reason.matched).map(reason => reason.name).join(', ') || 'Нет'}</td><td>{r.executed_at ? 'Сохранено' : 'Не выполнено'}</td><td><button onClick={() => select(r.id)}>Подробнее</button></td></tr>)}</tbody></table>{!rows.length && <p className="empty">По этим фильтрам проверки не найдены.</p>}</div>
      <div className="actions"><button disabled={!offset} onClick={() => load(Math.max(0, offset - pageSize))}>Предыдущие</button><span>Страница {offset / pageSize + 1}</span><button disabled={rows.length < pageSize} onClick={() => load(offset + pageSize)}>Следующие</button></div>
    </section>
    {selected && <><DecisionCard decision={selected}>{account.role === 'specialist' && selected.state === 'PENDING_REVIEW' && <><label>Комментарий специалиста<textarea value={comment} onChange={e => setComment(e.target.value)} /></label><div className="actions"><button className="primary" disabled={pending} onClick={() => review(true)}>Одобрить</button><button disabled={pending} onClick={() => review(false)}>Отклонить</button></div><p className="muted">Если требуется подтверждение инициатора, оно остаётся обязательным после одобрения.</p></>}</DecisionCard>
      <section className="card"><h2>История решения</h2>{selected.transitions?.map((t, i) => <div className="history-row" key={i}><strong>{label(t.after)}</strong> · {t.actor} · {date(t.at)}<p>{t.comment}</p></div>)}
        <h3>Фактические события этой операции</h3>{selected.events?.length ? <Events rows={selected.events} /> : <p className="muted">Событие о выполнении ещё не доставлено.</p>}
        <h3>События, использованные правилами ({selected.related_events_count ?? 0})</h3>{selected.related_events?.length ? <Events rows={selected.related_events} /> : <p className="muted">В этой проверке исторические события не использовались.</p>}
        {(selected.related_events_count ?? 0) > (selected.related_events?.length ?? 0) && <button disabled={pending} onClick={moreEvents}>Показать ещё события</button>}
      </section></>}
  </>
}
