import { fieldNames, label, type Decision } from '../api'
import { Explanation } from './Explanation'

const states: Record<string, string> = {
  PENDING_REVIEW: 'Требуется рассмотрение специалистом',
  PENDING_CONFIRMATION: 'Требуется подтверждение инициатора',
  APPROVED: 'Антифрод разрешил действие',
  REJECTED: 'Действие отклонено',
  CANCELLED: 'Попытка отменена',
  EXPIRED: 'Срок решения истёк',
}
function Reason({ reason }: { reason: Decision['reasons'][number] }) {
  return (
    <div>
      <strong>{reason.message ?? reason.name}</strong>
      <span>
        {reason.matched ? 'Сработало' : 'Не сработало'} ·{' '}
        {reason.reaction ? label(reason.reaction) : 'Ошибка проверки'}
      </span>
      {reason.trace ? (
        <details open={Boolean(reason.matched)}>
          <summary>Объяснение</summary>
          <Explanation trace={reason.trace} />
          {reason.exception_trace ? (
            <>
              <h3>Проверка исключения</h3>
              <Explanation trace={reason.exception_trace} />
            </>
          ) : null}
        </details>
      ) : null}
    </div>
  )
}
export function DecisionCard({
  decision,
  children,
}: {
  decision: Decision
  children?: React.ReactNode
}) {
  const important = decision.reasons.filter((reason) => reason.matched || reason.message)
  const other = decision.reasons.filter((reason) => !reason.matched && !reason.message)
  return (
    <section className="card decision">
      <div className="section-heading">
        <h2>Решение антифрода</h2>
        <span className={'badge ' + decision.state}>{label(decision.state)}</span>
      </div>
      <p className="decision-meta">
        {label(decision.action)} / {decision.initiator}
      </p>
      <div className={'decision-state ' + decision.state}>
        <strong>{decision.executed_at ? 'Действие уже сохранено' : states[decision.state]}</strong>
        {decision.remaining_steps.length > 0 && (
          <p>Обязательные этапы: {decision.remaining_steps.map(label).join(', ')}</p>
        )}
        <p className="small">
          {decision.executed_at || ['REJECTED', 'CANCELLED', 'EXPIRED'].includes(decision.state) ? 'Исходный срок проверки: до ' : 'Действует до '}
          {new Date(decision.expires_at).toLocaleString('ru-RU')}.
        </p>
      </div>
      {!decision.executed_at && <p className="muted">{({
        PENDING_REVIEW: 'Специалист примет решение в журнале. Действие ещё не выполнено.',
        PENDING_CONFIRMATION: 'Сверьте проверенные значения и подтвердите именно это действие или откажитесь.',
        REJECTED: 'Действие не выполнено. Разберите причину; после исправления данных или настройки источника можно начать новую попытку.',
        CANCELLED: 'Действие не выполнено. Чтобы продолжить, начните новую попытку по актуальным данным.',
        EXPIRED: 'Действие не выполнено. Начните новую попытку: система проверит актуальные данные и правила.',
      } as Record<string, string>)[decision.state]}</p>}
      {decision.application_id === 'demo' && decision.action === 'pay' && (
        <p className="muted small">Для выплаты также нужно согласование актуальной заявки руководителем. Разрешение антифрода и факт выплаты учитываются отдельно.</p>
      )}
      <h3>Причины решения</h3>
      {important.length === 0 && decision.state === 'APPROVED' && (
        <p>Сработавших ограничений нет.</p>
      )}
      <div className="reason-list">
        {important.map((reason, index) => (
          <Reason key={index} reason={reason} />
        ))}
      </div>
      {other.length > 0 && (
        <details>
          <summary>Правила без срабатывания ({other.length})</summary>
          <div className="reason-list">
            {other.map((reason, index) => (
              <Reason key={index} reason={reason} />
            ))}
          </div>
        </details>
      )}
      <details open={decision.state === 'PENDING_CONFIRMATION'}>
        <summary>Проверенные значения</summary>
        <dl>
          {Object.entries(decision.checked_values).map(([key, value]) => (
            <div key={key}>
              <dt>{fieldNames[key] ?? key}</dt>
              <dd>
                {typeof value === 'object' && value !== null
                  ? JSON.stringify(value, null, 2)
                  : String(value)}
              </dd>
            </div>
          ))}
        </dl>
      </details>
      {children}
      <details>
        <summary>Идентификаторы проверки</summary>
        <dl>
          <div>
            <dt>Приложение</dt>
            <dd>{decision.application_id}</dd>
          </div>
          <div>
            <dt>Операция</dt>
            <dd>
              <code>{decision.operation_id}</code>
            </dd>
          </div>
          <div>
            <dt>Решение</dt>
            <dd>
              <code>{decision.id}</code>
            </dd>
          </div>
        </dl>
      </details>
    </section>
  )
}
