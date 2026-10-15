export type Account = { id: string; name: string; username: string; role: string }
export type Field = {
  type: 'string' | 'number' | 'boolean'
  required: boolean
  source: 'API' | 'DB'
}
export type Application = {
  id: string
  name: string
  ttl_seconds: number
  catalog: Record<string, { fields: Record<string, Field> }>
}
export type Expression = {
  kind: string
  field?: string
  op?: string
  value?: string | number | boolean | Array<string | number | boolean>
  value_type?: string
  children?: Expression[]
  child?: Expression
  period_seconds?: number
  group_by?: string[]
  match_fields?: string[]
  event_types?: string[]
  statuses?: string[]
  aggregate?: string
  sequence?: string[]
  right_field?: string
  relation?: string
  include_current?: boolean
  on_empty?: boolean
  filter?: Expression
  list_id?: string
}
export type Rule = {
  id: string
  application_id: string
  name: string
  action: string
  expression: Expression
  reaction: string
  enabled: boolean
  exception: Expression | null
  version: number
}
export type RuleTemplate = Partial<Rule> & {
  id: string
  name: string
  kind: string
  builtin: boolean
}
export type EventView = {
  event_id: string
  event_at: string
  action: string
  actor: string
  status: string
  fields: Record<string, unknown>
}
export type Decision = {
  id: string
  application_id: string
  operation_id: string
  action: string
  initiator: string
  record_key: string
  checked_values: Record<string, unknown>
  state: string
  remaining_steps: string[]
  created_at: string
  expires_at: string
  executed_at: string | null
  reasons: Array<{
    name?: string
    reaction?: string
    matched?: boolean
    message?: string
    trace?: unknown
    exception_trace?: unknown
  }>
  transitions?: Array<{ before: string; after: string; actor: string; comment: string; at: string }>
  events?: EventView[]
  related_events?: EventView[]
  related_events_count?: number
}
export type Expense = {
  id: string
  author: string
  amount: string
  recipient: string
  receipt: string
  vendor: string
  purchase_date: string
  title: string
  version: number
  status: string
  approver: string | null
  approved_version: number | null
  history: Array<Record<string, unknown>>
  category: string
  decision?: DecisionSummary | null
}
export type DecisionSummary = { id: string; state: string; action: string; executed_at: string | null; reasons: string[] }
export type ExpensePage = { items: Expense[]; total: number; offset: number; limit: number }
export type Watchlist = {
  id: string
  application_id: string
  name: string
  values: Array<string | number | boolean>
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

export async function api<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch('/api' + path, {
      method,
      credentials: 'same-origin',
      ...(signal ? { signal } : {}),
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'antifraud-ui' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new Error('Нет связи с сервером. Проверьте подключение и повторите попытку.', { cause: error })
  }
  let result
  try {
    result = await response.json()
  } catch {
    throw new ApiError(
      'Сервер не вернул ответ. Повторите попытку; введённые данные сохранены.',
      response.status,
    )
  }
  if (!response.ok) {
    const names: Record<string, string> = {
      username: 'аккаунт',
      password: 'пароль',
      amount: 'сумма',
      recipient: 'получатель',
      receipt: 'номер чека',
      vendor: 'продавец',
      purchase_date: 'дата покупки',
      title: 'назначение',
      name: 'название',
      ttl_seconds: 'срок решения',
    }
    const fields = Array.isArray(result.fields)
      ? result.fields
          .map((field: string) => {
            const key = field.split('.').at(-1) ?? field
            return names[key] ?? key
          })
          .join(', ')
      : ''
    throw new ApiError(
      (result.message ?? 'Не удалось выполнить запрос') +
        (fields ? '. Проверьте поля: ' + fields : ''),
      response.status,
    )
  }
  return result as T
}
export const labels: Record<string, string> = {
  admin: 'Администратор',
  specialist: 'Специалист',
  employee: 'Сотрудник',
  manager: 'Руководитель',
  accountant: 'Бухгалтер',
  PENDING_REVIEW: 'Ручная проверка',
  PENDING_CONFIRMATION: 'Ожидает подтверждения',
  APPROVED: 'Разрешено',
  REJECTED: 'Отклонено',
  CANCELLED: 'Отменено',
  EXPIRED: 'Срок истёк',
  DRAFT: 'Черновик',
  SUBMITTED: 'Ожидает согласования руководителя',
  PAID: 'Выплачено условно',
  BLOCK: 'Запрет',
  REVIEW: 'Ручная проверка',
  CONFIRM: 'Подтверждение',
  LOG: 'Только запись',
  created: 'Создание заявки',
  edited: 'Изменение заявки',
  SUCCESS: 'Успешно',
  FAILED: 'Ошибка',
  submit: 'Отправка на согласование',
  approve: 'Согласование',
  reject: 'Отклонение',
  pay: 'Условная выплата',
  export: 'Выгрузка реестра',
  category: 'Категория',
  office: 'Канцелярия', transport: 'Рабочий транспорт', other: 'Другое',
  business_review: 'Решение руководителя по исключению',
}
export const label = (value: string) => labels[value] ?? value
export const fieldNames: Record<string, string> = { amount: 'Сумма', recipient: 'Получатель', author: 'Автор', initiator: 'Инициатор', approver: 'Согласовавший', request_id: 'Заявка', receipt: 'Номер чека', vendor: 'Продавец', purchase_date: 'Дата покупки', title: 'Назначение', category: 'Категория', version: 'Версия заявки', record_count: 'Строк в реестре', registry_snapshot: 'Снимок реестра', registry_version: 'Версия реестра' }
export const fieldLabel = (value: string) => fieldNames[value] ?? value
export const money = (value: string) =>
  Number(value).toLocaleString('ru-RU', { style: 'currency', currency: 'RUB' })
