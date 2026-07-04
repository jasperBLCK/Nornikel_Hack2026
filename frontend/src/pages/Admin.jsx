import { useEffect, useState } from 'react'
import {
  getAdminAudit,
  getAdminLogins,
  getAdminSummary,
  getAdminUsers,
} from '../api.js'

const TABS = [
  ['overview', 'Обзор'],
  ['users', 'Пользователи'],
  ['audit', 'Журнал действий'],
  ['security', 'Безопасность входов'],
]

const ACTION_LABELS = {
  query: 'Запрос',
  view: 'Просмотр',
  export: 'Экспорт',
}

const REASON_LABELS = {
  shared_ip: 'IP использовался другой учёткой',
  new_geo: 'Вход из новой страны',
  bruteforce: 'Подбор пароля (5+ неудач за 10 мин)',
}

const fmt = (ts) =>
  new Date(ts * 1000).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })

export default function Admin() {
  const [tab, setTab] = useState('overview')
  return (
    <div className="max-w-6xl mx-auto space-y-5">
      <div>
        <h1 className="text-xl font-bold">Администрирование</h1>
        <p className="text-sm text-nn-muted">
          Пользователи, аудит действий и мониторинг безопасности входов
        </p>
      </div>
      <div className="flex gap-2 flex-wrap">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`px-3.5 py-1.5 rounded-xl text-sm border transition-colors ${
              tab === id
                ? 'bg-nn-blue/25 text-nn-accent border-nn-blue/40'
                : 'text-nn-muted border-nn-border hover:text-nn-text hover:bg-nn-panel2'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === 'overview' && <Overview />}
      {tab === 'users' && <Users />}
      {tab === 'audit' && <Audit />}
      {tab === 'security' && <Security />}
    </div>
  )
}

function Card({ title, value, tone = '' }) {
  return (
    <div className="rounded-2xl border border-nn-border bg-nn-panel/60 p-4">
      <div className={`text-2xl font-bold ${tone}`}>{value}</div>
      <div className="text-xs text-nn-muted mt-1">{title}</div>
    </div>
  )
}

function Overview() {
  const [s, setS] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    getAdminSummary().then(setS).catch((e) => setErr(String(e)))
  }, [])
  if (err) return <Err text={err} />
  if (!s) return <Skeleton />
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
      <Card title="Активных пользователей за 24 ч" value={s.active_users_24h} />
      <Card title="Действий за 24 ч (запросы, просмотры)" value={s.actions_24h} />
      <Card title="Экспортов данных за 24 ч" value={s.exports_24h} />
      <Card title="Всего событий входа" value={s.logins_total} />
      <Card
        title="Неудачных входов за 24 ч"
        value={s.failed_24h}
        tone={s.failed_24h > 0 ? 'text-nn-amber' : ''}
      />
      <Card
        title="Подозрительных входов (всего)"
        value={s.suspicious_total}
        tone={s.suspicious_total > 0 ? 'text-nn-pink' : 'text-nn-green'}
      />
    </div>
  )
}

function Users() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    getAdminUsers().then(setData).catch((e) => setErr(String(e)))
  }, [])
  if (err) return <Err text={err} />
  if (!data) return <Skeleton />
  return (
    <div className="rounded-2xl border border-nn-border bg-nn-panel/60 overflow-hidden">
      <div className="px-4 py-2.5 text-xs text-nn-muted border-b border-nn-border/60">
        {data.keycloak
          ? 'Учётные записи управляются в Keycloak (realm hydrax)'
          : 'Локальный режим: демонстрационные учётные записи'}
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-nn-muted border-b border-nn-border/60">
            <th className="px-4 py-2">Логин</th>
            <th className="px-4 py-2">Имя</th>
            <th className="px-4 py-2">Роль</th>
            <th className="px-4 py-2">Допуск</th>
            <th className="px-4 py-2">Последний вход</th>
            <th className="px-4 py-2">Входов</th>
          </tr>
        </thead>
        <tbody>
          {data.users.map((u) => (
            <tr key={u.username} className="border-b border-nn-border/40">
              <td className="px-4 py-2 font-mono">{u.username}</td>
              <td className="px-4 py-2">{u.name}</td>
              <td className="px-4 py-2">{u.role_label}</td>
              <td className="px-4 py-2">
                <Clearance level={u.clearance} />
              </td>
              <td className="px-4 py-2 text-nn-muted">
                {u.activity ? fmt(u.activity.last_seen) : '—'}
              </td>
              <td className="px-4 py-2 text-nn-muted">
                {u.activity ? u.activity.logins : 0}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Clearance({ level }) {
  const map = {
    public: ['Открытые', 'text-nn-green border-nn-green/40 bg-nn-green/10'],
    internal: ['Внутренние', 'text-nn-cyan border-nn-cyan/40 bg-nn-cyan/10'],
    confidential: [
      'Коммерческая тайна',
      'text-nn-amber border-nn-amber/40 bg-nn-amber/10',
    ],
  }
  const [label, cls] = map[level] || [level, '']
  return (
    <span className={`text-[11px] px-2 py-0.5 rounded-md border ${cls}`}>{label}</span>
  )
}

function Audit() {
  const [rows, setRows] = useState(null)
  const [action, setAction] = useState('')
  const [err, setErr] = useState('')
  useEffect(() => {
    getAdminAudit(action ? `action=${action}` : '')
      .then((d) => setRows(d.actions))
      .catch((e) => setErr(String(e)))
  }, [action])
  if (err) return <Err text={err} />
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        {[['', 'Все'], ['query', 'Запросы'], ['view', 'Просмотры'], ['export', 'Экспорт']].map(
          ([id, label]) => (
            <button
              key={id}
              onClick={() => setAction(id)}
              className={`px-3 py-1 rounded-lg text-xs border ${
                action === id
                  ? 'bg-nn-blue/25 text-nn-accent border-nn-blue/40'
                  : 'text-nn-muted border-nn-border hover:text-nn-text'
              }`}
            >
              {label}
            </button>
          ),
        )}
      </div>
      {!rows ? (
        <Skeleton />
      ) : rows.length === 0 ? (
        <Empty text="Событий пока нет" />
      ) : (
        <div className="rounded-2xl border border-nn-border bg-nn-panel/60 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-nn-muted border-b border-nn-border/60">
                <th className="px-4 py-2">Время</th>
                <th className="px-4 py-2">Пользователь</th>
                <th className="px-4 py-2">Роль</th>
                <th className="px-4 py-2">Действие</th>
                <th className="px-4 py-2">Детали</th>
                <th className="px-4 py-2">IP</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-nn-border/40 align-top">
                  <td className="px-4 py-2 text-nn-muted whitespace-nowrap">{fmt(r.ts)}</td>
                  <td className="px-4 py-2 font-mono">{r.username}</td>
                  <td className="px-4 py-2 text-nn-muted">{r.role}</td>
                  <td className="px-4 py-2">{ACTION_LABELS[r.action] || r.action}</td>
                  <td className="px-4 py-2 text-nn-muted max-w-[360px] truncate" title={r.detail}>
                    {r.detail}
                  </td>
                  <td className="px-4 py-2 text-nn-muted font-mono text-xs">{r.ip}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function Security() {
  const [rows, setRows] = useState(null)
  const [suspiciousOnly, setSuspiciousOnly] = useState(false)
  const [err, setErr] = useState('')
  useEffect(() => {
    getAdminLogins(suspiciousOnly)
      .then((d) => setRows(d.logins))
      .catch((e) => setErr(String(e)))
  }, [suspiciousOnly])
  if (err) return <Err text={err} />
  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-sm text-nn-muted cursor-pointer">
        <input
          type="checkbox"
          checked={suspiciousOnly}
          onChange={(e) => setSuspiciousOnly(e.target.checked)}
        />
        Только подозрительные
      </label>
      {!rows ? (
        <Skeleton />
      ) : rows.length === 0 ? (
        <Empty text="Событий входа нет" />
      ) : (
        <div className="rounded-2xl border border-nn-border bg-nn-panel/60 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-nn-muted border-b border-nn-border/60">
                <th className="px-4 py-2">Время</th>
                <th className="px-4 py-2">Пользователь</th>
                <th className="px-4 py-2">IP</th>
                <th className="px-4 py-2">GeoIP</th>
                <th className="px-4 py-2">Результат</th>
                <th className="px-4 py-2">Флаги</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.id}
                  className={`border-b border-nn-border/40 ${
                    r.suspicious ? 'bg-nn-pink/5' : ''
                  }`}
                >
                  <td className="px-4 py-2 text-nn-muted whitespace-nowrap">{fmt(r.ts)}</td>
                  <td className="px-4 py-2 font-mono">{r.username}</td>
                  <td className="px-4 py-2 font-mono text-xs text-nn-muted">{r.ip}</td>
                  <td className="px-4 py-2 text-nn-muted">
                    {[r.country, r.city].filter(Boolean).join(', ') || '—'}
                  </td>
                  <td className="px-4 py-2">
                    {r.success ? (
                      <span className="text-nn-green text-xs">успех</span>
                    ) : (
                      <span className="text-nn-amber text-xs">отказ</span>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    {r.reasons
                      ? r.reasons.split(',').map((x) => (
                          <span
                            key={x}
                            className="inline-block text-[11px] px-2 py-0.5 mr-1 rounded-md border text-nn-pink border-nn-pink/40 bg-nn-pink/10"
                          >
                            {REASON_LABELS[x] || x}
                          </span>
                        ))
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function Skeleton() {
  return (
    <div className="space-y-2 animate-pulse">
      {[...Array(4)].map((_, i) => (
        <div key={i} className="h-10 rounded-xl bg-nn-panel2/60" />
      ))}
    </div>
  )
}

function Empty({ text }) {
  return (
    <div className="rounded-2xl border border-dashed border-nn-border py-10 text-center text-sm text-nn-muted">
      {text}
    </div>
  )
}

function Err({ text }) {
  return (
    <div className="rounded-2xl border border-nn-pink/40 bg-nn-pink/10 px-4 py-3 text-sm text-nn-pink">
      {text}
    </div>
  )
}
