import {kinds} from '../rule-presets'
import {fieldLabel} from '../api'
const operations: Record<string, string> = {eq: 'равно', ne: 'не равно', gt: 'больше', ge: 'не меньше', lt: 'меньше', le: 'не больше', in: 'входит в список'}
function valueText(value: unknown): string {return Array.isArray(value) ? value.map(valueText).join(', ') : typeof value === 'boolean' ? value ? 'да' : 'нет' : value === null || value === undefined ? '—' : String(value)}
export function Explanation({trace}: {trace: unknown}) {
  if (!trace || typeof trace !== 'object') return <p className="muted">Проверка не выполнена.</p>
  const t = trace as Record<string, unknown>
  if (t.excluded) return <p>Ограничение пропущено: сработало исключение этого правила.</p>
  const children = Array.isArray(t.children) ? t.children : []
  const history = Array.isArray(t.event_ids) ? t.event_ids : []
  return <div className="explanation"><strong>{kinds[String(t.kind)] ?? 'Проверка'} · {t.matched ? 'условие выполнено' : 'условие не выполнено'}</strong>{children.length > 0 ? children.map((child, i) => <Explanation trace={child} key={i} />) : <>
    <p>{t.field ? 'Поле «' + fieldLabel(String(t.field)) + '»: ' : 'Полученное значение: '}{valueText(t.actual)}{t.op ? ' ' + operations[String(t.op)] + ' ' + valueText(t.expected ?? t.threshold) : ''}</p>
    {t.history_state && <p>История: {({EMPTY: 'событий сущности ещё нет', NEW: 'значение новое для сущности', KNOWN: 'значение уже встречалось'} as Record<string, string>)[String(t.history_state)]}</p>}
    {t.missing_required_event && <p>Нужное предыдущее событие с актуальными значениями не найдено.</p>}
    {t.period_seconds !== undefined && <p className="muted">Период: {t.period_seconds ? valueText(t.period_seconds) + ' с' : 'вся история'}. Группировка: {valueText(t.group_by)}. Учитываемые статусы: {valueText(t.statuses)}. Событий: {history.length}.{t.include_current ? ' Текущая операция учитывается один раз, если проходит фильтр и ещё отсутствует в истории.' : ''}</p>}
  </>}</div>
}
