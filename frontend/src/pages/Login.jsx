import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth.jsx'

const DEMO = [
  ['researcher', 'researcher123', 'Исследователь', 'поиск, граф, чат, экспорт'],
  ['analyst', 'analyst123', 'Аналитик', '+ аналитика, параметры, матрица'],
  ['manager', 'manager123', 'Руководитель проекта', '+ коммерческие данные, радар'],
  ['admin', 'admin123', 'Администратор', 'всё + админ-панель и аудит'],
  ['partner', 'partner123', 'Внешний партнёр', 'только открытые документы'],
]

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await login(username.trim(), password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.message || 'Ошибка входа')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen grid place-items-center px-4">
      <div className="w-full max-w-md">
        <div className="flex items-center gap-3 justify-center mb-6">
          <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-nn-blue to-nn-cyan grid place-items-center font-black text-white text-lg">
            Hx
          </div>
          <div>
            <div className="font-bold leading-tight">Научный клубок</div>
            <div className="text-xs text-nn-muted">Карта знаний R&D · HydraX</div>
          </div>
        </div>

        <form
          onSubmit={submit}
          className="rounded-2xl border border-nn-border bg-nn-panel/70 backdrop-blur-md p-6 space-y-4"
        >
          <div className="text-sm font-semibold">Вход в систему</div>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Логин"
            autoFocus
            autoComplete="username"
            className="w-full px-3 py-2.5 rounded-xl bg-nn-panel2 border border-nn-border text-sm outline-none focus:border-nn-blue/60"
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Пароль"
            autoComplete="current-password"
            className="w-full px-3 py-2.5 rounded-xl bg-nn-panel2 border border-nn-border text-sm outline-none focus:border-nn-blue/60"
          />
          {error && (
            <div className="text-sm text-nn-pink bg-nn-pink/10 border border-nn-pink/30 rounded-xl px-3 py-2">
              {error}
            </div>
          )}
          <button
            type="submit"
            disabled={busy || !username || !password}
            className="w-full py-2.5 rounded-xl text-sm font-semibold text-white bg-gradient-to-r from-nn-blue to-nn-cyan disabled:opacity-50 hover:opacity-90 transition-opacity"
          >
            {busy ? 'Вход…' : 'Войти'}
          </button>
          <div className="text-[11px] text-nn-muted text-center">
            Авторизация через Keycloak (OIDC) · роли и доступ по политикам ИБ
          </div>
        </form>

        <details className="mt-4 rounded-2xl border border-nn-border bg-nn-panel/50 px-4 py-3 text-xs text-nn-muted">
          <summary className="cursor-pointer font-medium">Демо-учётки (5 ролей)</summary>
          <table className="mt-2 w-full text-left">
            <tbody>
              {DEMO.map(([u, p, role, scope]) => (
                <tr
                  key={u}
                  className="cursor-pointer hover:text-nn-text"
                  onClick={() => {
                    setUsername(u)
                    setPassword(p)
                  }}
                >
                  <td className="py-1 pr-2 font-mono">{u}</td>
                  <td className="py-1 pr-2 font-mono">{p}</td>
                  <td className="py-1 pr-2">{role}</td>
                  <td className="py-1 text-[10px]">{scope}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </div>
    </div>
  )
}
