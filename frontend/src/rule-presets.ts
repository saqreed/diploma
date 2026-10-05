import type {Application, Expression} from './api'
export const kinds: Record<string, string> = {field: 'Условие по полю', duplicate: 'Поиск повторов', count: 'Количество событий', aggregate: 'Сумма / уникальные значения', sequence: 'Последовательность событий', previous: 'Обязательное предыдущее событие', related: 'Сравнение связанных данных', novelty: 'Новизна значения', all: 'Все условия (И)', any: 'Любое условие (ИЛИ)', not: 'Обратное условие (НЕ)'}
export function baseNode(kind: string, app: Application, action: string): Expression {
  const config = app.catalog[action]
  if (!config) throw new Error('Тип события не найден')
  const names = Object.keys(config.fields)
  const first = names[0] ?? 'object_id'
  const numeric = names.find(n => config.fields[n]?.type === 'number') ?? first
  const leaf: Expression = {kind: 'field', field: numeric, op: config.fields[numeric]?.type === 'number' ? 'gt' : 'eq', value: config.fields[numeric]?.type === 'number' ? 10000 : config.fields[numeric]?.type === 'boolean' ? false : ''}
  if (kind === 'all' || kind === 'any') return {kind, children: [leaf]}
  if (kind === 'not') return {kind, child: leaf}
  if (kind === 'field') return leaf
  const history = {kind, period_seconds: 86400, group_by: [first], event_types: [action], statuses: ['SUCCESS']}
  if (kind === 'duplicate' || kind === 'previous') return {...history, match_fields: [numeric]}
  if (kind === 'count') return {...history, op: 'ge', value: 3, include_current: true}
  if (kind === 'aggregate') return {...history, aggregate: 'sum', field: numeric, op: 'gt', value: 10000, include_current: true}
  if (kind === 'related') return {...history, field: numeric, right_field: numeric, op: 'ne'}
  if (kind === 'sequence') return {...history, event_types: Object.keys(app.catalog), sequence: Object.keys(app.catalog).slice(0, 2)}
  return {...history, field: first, on_empty: false}
}
