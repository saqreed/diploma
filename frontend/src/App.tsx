import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router'
import { api, ApiError, label, type Account } from './api'
import { SessionContext } from './session'

export function App() {
  const [account, setAccount] = useState<Account | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const location = useLocation()
  useEffect(() => {
    api<Account>('/auth/me')
      .then(setAccount)
      .catch((e) => {
        if (!(e instanceof ApiError && e.status === 401)) setError(e.message)
      })
      .finally(() => setLoading(false))
  }, [])
  async function logout() {
    try {
      await api('/auth/logout', 'POST')
      setAccount(null)
      navigate('/login')
    } catch (e) {
      setError((e as Error).message)
    }
  }
  if (loading) return <div className="loading">Загрузка сеанса…</div>
  const section =
    (
      {
        '/admin': 'Правила проверки',
        '/settings': 'Приложения и источники',
        '/journal': 'Журнал решений',
        '/demo': 'Возмещение расходов',
      } as Record<string, string>
    )[location.pathname] ?? 'Рабочее пространство'
  return (
    <SessionContext value={{ account, setAccount }}>
      <a className="skip-link" href="#application-root">
        Перейти к содержимому
      </a>
      <div className={account ? 'shell' : 'auth-shell'}>
        {account && (
          <aside className="sidebar">
            <NavLink to="/" className="brand">
              Антифрод<small>Проверка действий</small>
            </NavLink>
            <nav aria-label="Основная навигация">
              {account?.role === 'admin' && (
                <>
                  <NavLink to="/admin">Правила проверки</NavLink>
                  <NavLink to="/settings">Приложения и источники</NavLink>
                </>
              )}
              {account && ['admin', 'specialist'].includes(account.role) && (
                <NavLink to="/journal">Журнал решений</NavLink>
              )}
              {account && ['employee', 'manager', 'accountant'].includes(account.role) && (
                <NavLink to="/demo">Возмещение расходов</NavLink>
              )}
            </nav>
            <div className="sidebar-bottom">
              <strong>Демонстрационный стенд</strong>
              <small>Без настоящих платежей</small>
            </div>
          </aside>
        )}
        <div className="workspace">
          <header className="topbar">
            {account ? (
              <>
                <span>{section}</span>
                <div className="account">
                  <span>{account.username}</span>
                  <strong>{label(account.role)}</strong>
                  <button className="quiet" onClick={logout}>
                    Выйти
                  </button>
                </div>
              </>
            ) : (
              <NavLink to="/login" className="brand">
                Антифрод
              </NavLink>
            )}
          </header>
          {error && (
            <div className="error session-error" role="alert">
              {error}
            </div>
          )}
          <main id="application-root" tabIndex={-1}>
            <Outlet />
          </main>
        </div>
      </div>
    </SessionContext>
  )
}
