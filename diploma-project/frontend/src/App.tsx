import {useEffect, useState} from 'react'
import {NavLink, Outlet, useNavigate} from 'react-router'
import {api, label, type Account} from './api'
import {SessionContext} from './session'

export function App() {
  const [account, setAccount] = useState<Account | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  useEffect(() => {api<Account>('/auth/me').then(setAccount).catch(() => {}).finally(() => setLoading(false))}, [])
  async function logout() {
    try {await api('/auth/logout', 'POST'); setAccount(null); navigate('/login')} catch (e) {setError((e as Error).message)}
  }
  if (loading) return <div className="loading">Загрузка сеанса…</div>
  return (
    <SessionContext value={{account, setAccount}}>
      <div className="shell">
        <aside className="sidebar"><NavLink to="/" className="brand"><span className="brand-icon">А</span><span>Антифрод<small>Настраиваемые правила</small></span></NavLink><div className="nav-label">РАБОЧЕЕ ПРОСТРАНСТВО</div><nav>
          {account?.role === 'admin' && <><NavLink to="/admin">Правила проверки</NavLink><NavLink to="/settings">Приложения и источники</NavLink></>}
          {account && ['admin', 'specialist'].includes(account.role) && <NavLink to="/journal">Журнал решений</NavLink>}
          {account && ['employee', 'manager', 'accountant'].includes(account.role) && <NavLink to="/demo">Возмещение расходов</NavLink>}
          {!account && <NavLink to="/login">Вход в систему</NavLink>}
        </nav><div className="sidebar-bottom"><span className="dot"/> Локальная демонстрация<small>Без настоящих платежей</small></div></aside>
        <div className="workspace"><header className="topbar"><span>Система проверки действий</span><div>{account ? <><strong>{account.name}</strong><span className="role">{label(account.role)}</span><button className="quiet" onClick={logout}>Выйти</button></> : <span className="role">Вход не выполнен</span>}</div></header>{error && <div className="error" role="alert">{error}</div>}<main id="application-root"><Outlet /></main></div>
      </div>
    </SessionContext>
  )
}
