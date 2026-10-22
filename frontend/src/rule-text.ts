import {fieldLabel, label, type Expression} from './api'
export const comparisons: Record<string, string> = {eq: '=', ne: '≠', gt: '>', ge: '≥', lt: '<', le: '≤', in: 'в списке'}
export const mechanismHelp: Record<string, string> = {
  field: 'Сравнить значение операции с порогом или списком наблюдения.',
  duplicate: 'Найти уже выполненную операцию с теми же выбранными полями.',
  count: 'Ограничить частоту действий одной сущности за период.',
  aggregate: 'Найти накопленную сумму или число разных значений за период.',
  sequence: 'Найти события в заданном порядке. Между ними допустимы другие события; текущая попытка не становится шагом истории.',
  previous: 'Сработать при отсутствии нужного события с актуальными полями. Последующий отзыв не вычисляется: действующее бизнес-согласование контролирует приложение.',
  related: 'Сравнить поля операции либо значение последнего подходящего события. Без события сравнение завершится ошибкой; используйте исключение для пустой истории.',
  novelty: 'Проверить, встречалось ли значение у выбранной сущности. Пустая история отличается от нового значения.',
  all: 'Сработает, если выполнены все условия. Все ветви вычисляются, включая сравнения связанных данных.',
  any: 'Сработает, если выполнено хотя бы одно условие. Все ветви вычисляются.',
  not: 'Обратить результат вложенного условия.',
}
export function periodText(seconds?: number): string {
  if (!seconds) return 'всю историю'
  if (seconds % 86400 === 0) return `${seconds / 86400} дн.`
  if (seconds % 3600 === 0) return `${seconds / 3600} ч`
  if (seconds % 60 === 0) return `${seconds / 60} мин`
  return `${seconds} с`
}
const value = (v: unknown): string => Array.isArray(v) ? v.map(value).join(', ') : typeof v === 'boolean' ? v ? 'да' : 'нет' : typeof v === 'number' ? v.toLocaleString('ru-RU') : String(v ?? '…')
export function ruleText(n: Expression): string {
  if (n.kind === 'all' || n.kind === 'any') return (n.children ?? []).map(c => `(${ruleText(c)})`).join(n.kind === 'all' ? ' И ' : ' ИЛИ ')
  if (n.kind === 'not') return `НЕ (${n.child ? ruleText(n.child) : '…'})`
  const field = fieldLabel(n.field ?? '')
  const comparison = `${comparisons[n.op ?? 'eq']} ${n.list_id ? 'список наблюдения' : value(n.value)}`
  if (n.kind === 'field') return `${field} ${comparison}`
  if (n.kind === 'related') return `${field} ${comparisons[n.op ?? 'ne']} ${fieldLabel(n.right_field ?? '')} (${n.relation === 'current' ? 'эта операция' : 'последнее событие'})`
  const group = (n.group_by ?? []).map(fieldLabel).join(', ')
  const window = `за ${periodText(n.period_seconds)}${group ? ' · ' + group : ''}`
  if (n.kind === 'aggregate') return `${n.aggregate === 'unique' ? 'Разных значений' : 'Сумма'} «${field}» ${comparison} ${window}`
  if (n.kind === 'count') return `Количество ${comparison} ${window}`
  if (n.kind === 'novelty') return `Новое значение «${field}» ${window}`
  if (n.kind === 'sequence') return `${(n.sequence ?? []).map(label).join(' → ')} ${window}`
  return `${n.kind === 'previous' ? 'Нет обязательного события' : 'Повтор по полям'}: ${(n.match_fields ?? []).map(fieldLabel).join(', ')} ${window}`
}
