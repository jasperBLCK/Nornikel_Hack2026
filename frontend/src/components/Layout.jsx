import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { getStats } from '../api.js'
import { hasRole, useAuth } from '../auth.jsx'

const INTERNAL = ['researcher', 'analyst', 'project_manager', 'admin']

const NAV = [
  { to: '/', label: 'Дашборд', icon: '▦' },
  { to: '/search', label: 'Поиск', icon: '⌕' },
  { to: '/world', label: 'Мировая наука', icon: '◍' },
  { to: '/graph', label: 'Граф знаний', icon: '❖', roles: INTERNAL },
  { to: '/documents', label: 'Документы', icon: '☰' },
  { to: '/analytics', label: 'Аналитика', icon: '◔', roles: INTERNAL },
  { to: '/verify', label: 'Верификация', icon: '⚖', roles: INTERNAL },
  { to: '/matrix', label: 'Матрица покрытия', icon: '▤', roles: INTERNAL },
  { to: '/parameters', label: 'Параметры', icon: '≡', roles: INTERNAL },
  {
    to: '/radar',
    label: 'Радар исследований',
    icon: '◎',
    roles: ['analyst', 'project_manager', 'admin'],
  },
  { to: '/bridges', label: 'Связи-мосты', icon: '⌘', roles: INTERNAL },
  { to: '/admin', label: 'Администрирование', icon: '⚙', roles: ['admin'] },
]

export default function Layout() {
  const [stats, setStats] = useState(null)
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const { user, logout, notice, setNotice } = useAuth()

  useEffect(() => {
    getStats().then(setStats).catch(() => {})
  }, [])

  const nav = NAV.filter((n) => !n.roles || hasRole(user, ...n.roles))

  return (
    <div className="min-h-screen flex">
      {/* sidebar */}
      <aside
        className={`${
          collapsed ? 'w-[64px]' : 'w-[230px]'
        } shrink-0 sticky top-0 h-screen flex flex-col border-r border-nn-border bg-nn-panel/70 backdrop-blur-md transition-all duration-200`}
      >
        <div className="flex items-center gap-3 px-4 py-4 border-b border-nn-border/60">
          <div className="w-9 h-9 shrink-0 rounded-xl bg-gradient-to-br from-nn-blue to-nn-cyan grid place-items-center font-black text-white">
            Hx
          </div>
          {!collapsed && (
            <div className="min-w-0">
              <div className="font-bold leading-tight text-sm truncate">Научный клубок</div>
              <div className="text-[10px] text-nn-muted leading-tight truncate">
                Карта знаний R&D · HydraX
              </div>
            </div>
          )}
        </div>

        <nav className="flex-1 px-2.5 py-3 space-y-1 overflow-y-auto">
          {nav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === '/'}
              title={n.label}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-xl text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-nn-blue/25 text-nn-accent border border-nn-blue/40'
                    : 'text-nn-muted hover:text-nn-text hover:bg-nn-panel2 border border-transparent'
                }`
              }
            >
              <span className="w-5 text-center shrink-0">{n.icon}</span>
              {!collapsed && <span className="truncate">{n.label}</span>}
            </NavLink>
          ))}
        </nav>

        <div className="px-2.5 pb-3 space-y-2">
          {user && !collapsed && (
            <div className="px-3 py-2 rounded-xl bg-nn-panel2/70 border border-nn-border/60">
              <div className="text-xs font-semibold truncate">{user.name}</div>
              <div className="text-[10px] text-nn-muted truncate">
                {user.role_label} · допуск: {user.clearance_label}
              </div>
              <button
                onClick={() => {
                  logout()
                  navigate('/login')
                }}
                className="mt-1.5 text-[11px] text-nn-muted hover:text-nn-pink transition-colors"
              >
                ← Выйти
              </button>
            </div>
          )}
          <button
            onClick={() => navigate('/search')}
            title="Задать вопрос ИИ"
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-xl text-sm font-semibold text-nn-accent border border-nn-blue/50 bg-nn-blue/10 hover:bg-nn-blue/25 transition-colors"
          >
            ✦ {!collapsed && 'Задать вопрос ИИ'}
          </button>
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="w-full flex items-center justify-center gap-2 px-3 py-1.5 rounded-xl text-xs text-nn-muted hover:text-nn-text hover:bg-nn-panel2 transition-colors"
          >
            {collapsed ? '»' : '« Свернуть'}
          </button>
        </div>
      </aside>

      {/* main area */}
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="sticky top-0 z-40 backdrop-blur-md bg-nn-dark/85 border-b border-nn-border">
          <div className="px-5 py-2.5 flex items-center gap-5">
            <div className="text-sm font-semibold text-nn-muted">
              Карта знаний горно-металлургических исследований
            </div>
            <div className="ml-auto flex gap-5 text-right">
              {stats && (
                <>
                  <Stat value={stats.chunks} label="фрагментов" />
                  <Stat value={stats.nodes} label="узлов графа" />
                  <Stat value={stats.relations} label="связей" />
                  <span
                    className={`self-center text-[11px] px-2 py-1 rounded-md border ${
                      stats.neo4j
                        ? 'text-nn-green border-nn-green/40 bg-nn-green/10'
                        : 'text-nn-pink border-nn-pink/40 bg-nn-pink/10'
                    }`}
                  >
                    Neo4j {stats.neo4j ? 'online' : 'offline'}
                  </span>
                </>
              )}
            </div>
          </div>
        </header>

        {notice && (
          <div className="mx-5 mt-3 flex items-center gap-3 rounded-xl border border-nn-amber/40 bg-nn-amber/10 px-4 py-2.5 text-sm text-nn-amber">
            ⚠ Служба безопасности: вход помечен как подозрительный (
            {notice.join(', ')}). Событие записано в журнал аудита.
            <button
              onClick={() => setNotice(null)}
              className="ml-auto text-nn-muted hover:text-nn-text"
            >
              ✕
            </button>
          </div>
        )}

        <main className="flex-1 w-full px-5 py-5">
          <Outlet context={{ stats, user }} />
        </main>

        <footer className="text-center text-xs text-nn-muted/60 py-4">
          HydraX Knowledge System · локальное извлечение + векторный поиск + граф знаний ·
          LLM вызывается только на запрос
        </footer>
      </div>
    </div>
  )
}

function Stat({ value, label }) {
  return (
    <div>
      <div className="text-nn-accent font-bold leading-tight text-sm">
        {Number(value).toLocaleString('ru-RU')}
      </div>
      <div className="text-[10px] uppercase tracking-wider text-nn-muted">{label}</div>
    </div>
  )
}
