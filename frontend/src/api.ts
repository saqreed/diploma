export type Account = {id: string; name: string; username: string; role: string}
export type Field = {type: 'string' | 'number' | 'boolean'; required: boolean; source: 'API' | 'DB'}
export type Application = {id: string; name: string; ttl_seconds: number; catalog: Record<string, {fields: Record<string, Field>}>}
export type Expression = {kind: string; field?: string; op?: string; value?: string | number | boolean | Array<string | number | boolean>; value_type?: string; children?: Expression[]; child?: Expression; period_seconds?: number; group_by?: string[]; match_fields?: string[]; event_types?: string[]; statuses?: string[]; aggregate?: string; sequence?: string[]; right_field?: string; relation?: string; include_current?: boolean; on_empty?: boolean; filter?: Expression; list_id?: string}
export type Rule = {id: string; application_id: string; name: string; action: string; expression: Expression; reaction: string; enabled: boolean; exception: Expression | null; version: number}
export type RuleTemplate = Partial<Rule> & {id: string; name: string; kind: string; builtin: boolean}
export type EventView = {event_id: string; event_at: string; action: string; actor: string; status: string; fields: Record<string, unknown>}
export type Decision = {id: string; application_id: string; operation_id: string; action: string; initiator: string; record_key: string; checked_values: Record<string, unknown>; state: string; remaining_steps: string[]; created_at: string; expires_at: string; executed_at: string | null; reasons: Array<{name?: string; reaction?: string; matched?: boolean; message?: string; trace?: unknown; exception_trace?: unknown}>; transitions?: Array<{before: string; after: string; actor: string; comment: string; at: string}>; events?: EventView[]; related_events?: EventView[]; related_events_count?: number}
export type Expense = {id: string; author: string; amount: string; recipient: string; receipt: string; vendor: string; purchase_date: string; title: string; version: number; status: string; approver: string | null; approved_version: number | null; history: Array<Record<string, unknown>>}
export type Watchlist = {id: string; application_id: string; name: string; values: Array<string | number | boolean>}

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch('/api' + path, {method, credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'antifraud-ui'}, ...(body === undefined ? {} : {body: JSON.stringify(body)})})
  } catch { throw new Error('Нет связи с сервером. Проверьте подключение и повторите попытку.') }
  const result = await response.json()
  if (!response.ok) {
    const names: Record<string, string> = {username: 'аккаунт', password: 'пароль', amount: 'сумма', recipient: 'получатель', receipt: 'номер чека', vendor: 'продавец', purchase_date: 'дата покупки', title: 'назначение', name: 'название', ttl_seconds: 'срок решения'}
    const fields = Array.isArray(result.fields) ? result.fields.map((field: string) => {const key = field.split('.').at(-1) ?? field; return names[key] ?? key}).join(', ') : ''
    throw new Error((result.message ?? 'Не удалось выполнить запрос') + (fields ? '. Проверьте поля: ' + fields : ''))
  }
  return result as T
}
export const labels: Record<string, string> = {admin: 'Администратор', specialist: 'Специалист', employee: 'Сотрудник', manager: 'Руководитель', accountant: 'Бухгалтер', PENDING_REVIEW: 'Ручная проверка', PENDING_CONFIRMATION: 'Ожидает подтверждения', APPROVED: 'Разрешено', REJECTED: 'Отклонено', CANCELLED: 'Отменено', EXPIRED: 'Срок истёк', DRAFT: 'Черновик', SUBMITTED: 'На согласовании', PAID: 'Выплачено условно', BLOCK: 'Запрет', REVIEW: 'Ручная проверка', CONFIRM: 'Подтверждение', LOG: 'Только запись', created: 'Создание заявки', edited: 'Изменение заявки', SUCCESS: 'Успешно', FAILED: 'Ошибка', submit: 'Отправка на согласование', approve: 'Согласование', reject: 'Отклонение', pay: 'Условная выплата', export: 'Выгрузка реестра'}
export const label = (value: string) => labels[value] ?? value
export const money = (value: string) => Number(value).toLocaleString('ru-RU', {style: 'currency', currency: 'RUB'})
