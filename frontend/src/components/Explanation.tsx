import {kinds} from '../rule-presets'
import {fieldLabel, label, valueText, type Expression} from '../api'
import {comparisons, periodText, ruleText} from '../rule-text'

export function Explanation({trace, node}: {trace: unknown; node?: Expression | undefined}) {
  if (!trace || typeof trace !== 'object') return <p className="muted">Проверка не выполнена.</p>
  const t = trace as Record<string, unknown>
  if (t.excluded) return <p>Ограничение пропущено: сработало исключение этого правила.</p>
  const children = Array.isArray(t.children) ? t.children : t.child ? [t.child] : []
  const history = Array.isArray(t.event_ids) ? t.event_ids : []
  const kind = String(t.kind)
  const numeric = ['count','aggregate','sequence','previous','duplicate'].includes(kind) || node?.value_type === 'number'
  const format = (v: unknown) => numeric && v !== null && v !== undefined && Number.isFinite(Number(v)) ? Number(v).toLocaleString('ru-RU') : valueText(v)
  const actual = format(t.actual)
  const subject = kind === 'count' ? 'Количество событий' : kind === 'aggregate' ? node?.aggregate === 'unique' ? 'Разных значений' : 'Накопленная сумма' : kind === 'sequence' ? 'Найдено шагов' : kind === 'previous' ? 'Подходящих предыдущих событий' : t.field || node?.field ? fieldLabel(String(t.field ?? node?.field)) : 'Результат'
  return <div className={'explanation ' + (t.matched ? 'matched' : '')}>
    <div className="explanation-heading"><strong>{kinds[kind] ?? 'Проверка'}</strong><span>{t.matched ? 'Условие выполнено' : 'Условие не выполнено'}</span></div>
    {children.length ? children.map((child,i) => <Explanation trace={child} node={node?.children?.[i] ?? node?.child} key={i}/>) : <>
      {node && <p className="condition-sentence">{ruleText(node)}</p>}
      <p className="measurement"><span>{subject}</span><strong>{actual}</strong>{t.op ? <span>{comparisons[String(t.op)]} {format(t.expected ?? t.threshold)}</span> : null}</p>
      {t.history_state ? <p>{({EMPTY:'Событий этой сущности ещё нет.',NEW:'Значение новое для этой сущности.',KNOWN:'Значение уже встречалось у этой сущности.'} as Record<string,string>)[String(t.history_state)]}</p> : null}
      {t.missing_required_event ? <p>Нужное предыдущее событие с актуальными значениями не найдено.</p> : null}
      {t.statuses ? <div className="history-context"><span>Период: {periodText(Number(t.period_seconds))}</span><span>Группа: {(Array.isArray(t.group_by) ? t.group_by.map(v=>fieldLabel(String(v))).join(', ') : '') || 'все события'}</span><span>Статусы: {Array.isArray(t.statuses) ? t.statuses.map(v=>label(String(v))).join(', ') : valueText(t.statuses)}</span><span>В истории: {String(t.history_count ?? history.length)}</span>{t.include_current ? <span>Текущая операция учитывается один раз, если проходит фильтр.</span> : null}</div> : null}
    </>}
  </div>
}
