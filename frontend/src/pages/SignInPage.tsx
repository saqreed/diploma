import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router'
import { api, type Account } from '../api'
import { useSession } from '../session'
function home(role: string) {
  return role === 'admin' ? '/admin' : role === 'specialist' ? '/journal' : '/demo'
}
export function SignInPage() {
  const { account, setAccount } = useSession()
  const navigate = useNavigate()
  const [username, setUsername] = useState('employee')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  if (account) return <Navigate to={home(account.role)} replace />
  async function submit(e: FormEvent) {
    e.preventDefault()
    setPending(true)
    setError('')
    try {
      const result = await api<Account>('/auth/login', 'POST', { username, password })
      setAccount(result)
      navigate(home(result.role))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPending(false)
    }
  }
  return (
    <div className="login-layout">
      <form className="card login-card" onSubmit={submit} aria-busy={pending}>
        <h1>Вход в систему</h1>
        <p className="muted">Выберите учебный аккаунт и введите пароль.</p>
        <label>
          Аккаунт
          <select
            aria-label="Аккаунт"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          >
            {[
              ['employee', 'Сотрудник'],
              ['employee2', 'Второй сотрудник'],
              ['manager', 'Руководитель'],
              ['accountant', 'Бухгалтер'],
              ['specialist', 'Специалист по проверке'],
              ['admin', 'Администратор'],
            ].map(([v, n]) => (
              <option value={v} key={v}>
                {n} ({v})
              </option>
            ))}
          </select>
        </label>
        <label>
          Пароль
          <input
            required
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        <button className="primary" disabled={pending}>
          {pending ? 'Вход…' : 'Войти'}
        </button>
        <p className="muted small">Пароль выдан при подготовке демонстрационного стенда.</p>
      </form>
      <p className="login-footer">Учебная система. Выплаты в демо условные.</p>
    </div>
  )
}
