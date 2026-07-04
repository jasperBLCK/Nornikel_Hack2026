import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  getAnalytics,
  getContradictions,
  getDocuments,
  getFullGraph,
  getGaps,
  getMyOverview,
  getRecentQueries,
} from '../api.js'
import GraphView from '../components/GraphView.jsx'
import { useAuth } from '../auth.jsx'

// Role-specific quick actions for the personal cabinet.
const ROLE_ACTIONS = {
  admin: [
    { icon: '⚙', label: 'Панель администратора', to: '/admin' },
    { icon: '◎', label: 'Радар исследований', to: '/radar' },
    { icon: '⚖', label: 'Верификация фактов', to: '/verify' },
  ],
  project_manager: [
    { icon: '◎', label: 'Радар исследований', to: '/radar' },
    { icon: '▤', label: 'Матрица покрытия', to: '/matrix' },
    { icon: '◔', label: 'Аналитика', to: '/analytics' },
  ],
  analyst: [
    { icon: '⚖', label: 'Верификация фактов', to: '/verify' },
    { icon: '≡', label: 'Параметры', to: '/parameters' },
    { icon: '⌘', label: 'Связи-мосты', to: '/bridges' },
  ],
  researcher: [
    { icon: '✵', label: 'Задать вопрос ИИ', to: '/search' },
    { icon: '❋', label: 'Граф знаний', to: '/graph' },
    { icon: '◍', label: 'Мировая наука', to: '/world' },
  ],
  external_partner: [
    { icon: '✵', label: 'Задать вопрос ИИ', to: '/search' },
    { icon: '☰', label: 'Документы', to: '/documents' },
  ],
}

const ROLE_HINT = {
  admin: 'Полный доступ: управление пользователями, аудит и безопасность.',
  project_manager: 'Обзор покрытия направлений и активности команд.',
  analyst: 'Глубокий анализ: верификация, параметры, междоменные связи.',
  researcher: 'Исследовательский поиск по корпусу и графу знаний.',
  external_partner: 'Ограниченный доступ: только открытые материалы.',
}

const LABEL_RU = {
  Material: 'Материалы',
  Process: 'Процессы',
  Equipment: 'Оборудование',
  Experiment: 'Эксперименты',
  Parameter: 'Параметры',
  Condition: 'Условия',
}
const LABEL_COLOR = {
  Material: 'from-nn-cyan to-nn-blue',
  Process: 'from-nn-green to-nn-cyan',
  Equipment: 'from-nn-amber to-nn-pink',
  Experiment: 'from-nn-purple to-nn-blue',
  Parameter: 'from-nn-blue to-nn-purple',
  Condition: 'from-nn-pink to-nn-amber',
}

export default function Dashboard() {
  const [analytics, setAnalytics] = useState(null)
  const [gaps, setGaps] = useState(null)
  const [conflicts, setConflicts] = useState(null)
  const [docs, setDocs] = useState(null)
  const [graph, setGraph] = useState(null)
  const [queries, setQueries] = useState(null)
  const [overview, setOverview] = useState(null)
  const navigate = useNavigate()
  const { user } = useAuth()

  useEffect(() => {
    getAnalytics().then(setAnalytics).catch(() => setAnalytics({}))
    getGaps().then(setGaps).catch(() => setGaps({}))
    getContradictions().then(setConflicts).catch(() => setConflicts({}))
    getDocuments().then(setDocs).catch(() => setDocs({}))
    getFullGraph(120).then(setGraph).catch(() => setGraph({ nodes: [], edges: [] }))
    getRecentQueries(8).then(setQueries).catch(() => setQueries({}))
    getMyOverview().then(setOverview).catch(() => setOverview({}))
  }, [])

  const coverage = useMemo(() => {
    const weak = gaps?.weak_by_label || []
    const total = weak.reduce((a, w) => a + w.total, 0)
    const weakN = weak.reduce((a, w) => a + w.weak, 0)
    if (!total) return null
    return Math.round(100 * (1 - weakN / total))
  }, [gaps])

  const labels = analytics?.labels || []
  const maxLabel = Math.max(1, ...labels.map((l) => l.count))
  const documents = docs?.documents || []
  const conflictItems = conflicts?.contradictions || []
  const recentQ = queries?.queries || []

  const role = user?.role || 'researcher'
  const actions = ROLE_ACTIONS[role] || ROLE_ACTIONS.researcher
  const myCounts = overview?.counts || {}
  const mySessions = overview?.sessions || []

  return (
    <div className="space-y-5">
      {/* personal cabinet */}
      <div className="card bg-gradient-to-br from-nn-blue/10 to-transparent border-nn-blue/30">
        <div className="flex items-start gap-4 flex-wrap">
          <div className="w-12 h-12 shrink-0 rounded-2xl bg-gradient-to-br from-nn-blue to-nn-cyan grid place-items-center text-xl font-black text-white">
            {(user?.name || '?').slice(0, 1)}
          </div>
          <div className="min-w-0">
            <div className="text-lg font-extrabold">
              {user?.name || 'Пользователь'}
            </div>
            <div className="text-xs text-nn-muted">
              {user?.role_label} · допуск: {user?.clearance_label}
            </div>
            <div className="text-[13px] text-nn-muted mt-1">{ROLE_HINT[role]}</div>
          </div>
          <div className="ml-auto flex gap-2 flex-wrap">
            {actions.map((a) => (
              <button
                key={a.to}
                onClick={() => navigate(a.to)}
                className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium border border-nn-blue/40 bg-nn-blue/10 text-nn-accent hover:bg-nn-blue/20 transition-colors"
              >
                <span>{a.icon}</span>
                {a.label}
              </button>
            ))}
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
          <MiniStat label="Мои запросы" value={myCounts.query || 0} />
          <MiniStat label="Экспорты" value={myCounts.export || 0} />
          <MiniStat label="Всего действий" value={myCounts.total || 0} />
          <MiniStat label="Диалоги" value={mySessions.length} />
        </div>
        {mySessions.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {mySessions.slice(0, 4).map((s) => (
              <button
                key={s.id}
                onClick={() => navigate(`/search?session=${s.id}`)}
                title="Открыть диалог"
                className="text-[11px] px-2.5 py-1 rounded-lg border border-nn-border bg-nn-panel2/60 text-nn-muted hover:text-nn-text hover:border-nn-blue/50 transition-colors max-w-[220px] truncate"
              >
                ✵ {s.title || 'Без названия'}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4">
        <StatCard icon="📄" label="Документы" value={docs ? (docs.total ?? documents.length) : null} />
        <StatCard icon="🧩" label="Фрагменты" value={analytics?.chunks} />
        <StatCard icon="🕸" label="Узлы графа" value={analytics?.nodes} />
        <StatCard icon="🔗" label="Связи" value={analytics?.relations} />
        <StatCard
          icon="⚠️"
          label="Противоречия"
          value={conflicts ? conflictItems.length : null}
          accent="text-nn-amber"
        />
        <StatCard
          icon="◔"
          label="Покрытие знаний"
          value={coverage !== null ? `${coverage}%` : gaps ? '—' : null}
          accent="text-nn-green"
        />
      </div>

      <div className="grid xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_minmax(0,1fr)] gap-5 items-start">
        {/* activity by entity type */}
        <div className="card">
          <div className="card-title">Состав базы знаний</div>
          {!analytics ? (
            <div className="skeleton h-56" />
          ) : labels.length === 0 ? (
            <Empty text="Граф пуст — прогоните пайплайн" />
          ) : (
            <div className="space-y-3">
              {labels.map((l) => (
                <div key={l.label}>
                  <div className="flex justify-between text-xs mb-1">
                    <span>{LABEL_RU[l.label] || l.label}</span>
                    <span className="text-nn-muted">{l.count.toLocaleString('ru-RU')}</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-nn-border overflow-hidden">
                    <div
                      className={`h-full rounded-full bg-gradient-to-r ${
                        LABEL_COLOR[l.label] || 'from-nn-blue to-nn-cyan'
                      }`}
                      style={{ width: `${(100 * l.count) / maxLabel}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* graph preview */}
        <div className="card">
          <div className="card-title flex">
            Граф знаний
            <button
              onClick={() => navigate('/graph')}
              className="ml-auto normal-case tracking-normal font-medium text-[11px] text-nn-accent hover:underline"
            >
              Открыть полностью →
            </button>
          </div>
          {graph === null ? (
            <div className="skeleton h-72" />
          ) : (
            <GraphView
              graph={graph}
              height={300}
              physics={false}
              onNodeClick={(name) => navigate(`/graph?entity=${encodeURIComponent(name)}`)}
            />
          )}
        </div>

        {/* fresh documents */}
        <div className="card">
          <div className="card-title flex">
            Документы корпуса
            <button
              onClick={() => navigate('/documents')}
              className="ml-auto normal-case tracking-normal font-medium text-[11px] text-nn-accent hover:underline"
            >
              Все →
            </button>
          </div>
          {!docs ? (
            <div className="skeleton h-56" />
          ) : documents.length === 0 ? (
            <Empty text="Корпус ещё не проиндексирован" />
          ) : (
            <div className="space-y-2.5">
              {documents.slice(0, 6).map((d) => (
                <div
                  key={d.document_id}
                  className="flex items-center gap-2.5 rounded-xl border border-nn-border bg-nn-panel2/50 px-3 py-2"
                >
                  <span className="shrink-0">📄</span>
                  <span className="text-xs truncate flex-1" title={d.filename}>
                    {d.filename}
                  </span>
                  <span className="text-[10px] text-nn-muted shrink-0">
                    {d.chunks} фрагм.
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="grid xl:grid-cols-3 gap-5 items-start">
        {/* contradictions & gaps */}
        <div className="card">
          <div className="card-title">Противоречия и пробелы в знаниях</div>
          {!conflicts || !gaps ? (
            <div className="skeleton h-40" />
          ) : (
            <div className="space-y-3">
              {conflictItems.slice(0, 3).map((c, i) => {
                const q = `Почему источники расходятся по параметру «${c.parameter}»${c.unit ? ` (${c.unit})` : ''} для процесса «${c.process}»? Диапазон значений в корпусе: ${c.min} – ${c.max} ${c.unit || ''}. Какие значения считать достоверными и почему?`
                return (
                <div
                  key={i}
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate(`/search?q=${encodeURIComponent(q)}`)}
                  onKeyDown={(e) => e.key === 'Enter' && navigate(`/search?q=${encodeURIComponent(q)}`)}
                  title="Спросить ИИ о противоречии"
                  className="rounded-xl border border-nn-amber/40 bg-nn-amber/5 px-3.5 py-2.5 cursor-pointer hover:border-nn-amber/70 transition-colors"
                >
                  <div className="text-[13px] font-semibold text-nn-amber">
                    ⚠ Противоречивые данные: {c.parameter}
                    {c.unit ? ` (${c.unit})` : ''} — {c.process}
                  </div>
                  <div className="text-xs text-nn-muted mt-1">
                    Диапазон значений: {c.min} – {c.max} {c.unit} (разброс в источниках) ·
                    источников: {c.sources}
                  </div>
                </div>
                )
              })}
              {conflictItems.length === 0 && (
                <div className="text-xs text-nn-muted">
                  Противоречий в числовых параметрах не обнаружено
                </div>
              )}
              {(gaps.uncovered_processes || []).slice(0, 2).map((p) => {
                const q = `Какие режимы, параметры и условия процесса «${p}» описаны в мировой и отечественной практике? В нашем корпусе данных о режимах нет.`
                return (
                <div
                  key={p}
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate(`/search?q=${encodeURIComponent(q)}`)}
                  onKeyDown={(e) => e.key === 'Enter' && navigate(`/search?q=${encodeURIComponent(q)}`)}
                  title="Спросить ИИ о пробеле"
                  className="rounded-xl border border-nn-blue/40 bg-nn-blue/5 px-3.5 py-2.5 cursor-pointer hover:border-nn-blue/70 transition-colors"
                >
                  <div className="text-[13px] font-semibold text-nn-accent">
                    ℹ Пробел: процесс «{p}» без параметров и условий
                  </div>
                  <div className="text-xs text-nn-muted mt-1">
                    Нет данных о режимах — рекомендуется добавить источники
                  </div>
                </div>
                )
              })}
              {(gaps.uncovered_materials || []).length > 0 && (
                <div className="text-xs text-nn-muted">
                  Материалы без связанных процессов:{' '}
                  {(gaps.uncovered_materials || []).slice(0, 6).join(', ')}
                  {(gaps.uncovered_materials || []).length > 6 ? '…' : ''}
                </div>
              )}
            </div>
          )}
        </div>

        {/* research recommendations */}
        <div className="card">
          <div className="card-title">Рекомендации исследований</div>
          {!conflicts || !gaps ? (
            <div className="skeleton h-40" />
          ) : (
            <div className="space-y-2.5">
              {conflictItems.slice(0, 2).map((c, i) => (
                <Recommendation
                  key={`c${i}`}
                  icon="🔬"
                  text={`Верифицировать «${c.parameter}» для «${c.process}» — источники расходятся в ${Math.round(
                    100 * c.spread,
                  )}%`}
                  onClick={() =>
                    navigate(
                      `/search?q=${encodeURIComponent(
                        `Как верифицировать параметр «${c.parameter}» для процесса «${c.process}»? Источники расходятся в ${Math.round(100 * c.spread)}% — какие значения подтверждены и какими источниками?`,
                      )}`,
                    )
                  }
                />
              ))}
              {(gaps.uncovered_processes || []).slice(0, 3).map((p, i) => (
                <Recommendation
                  key={`p${i}`}
                  icon="🧪"
                  text={`Собрать данные о режимах процесса «${p}» — параметры отсутствуют в корпусе`}
                  onClick={() =>
                    navigate(
                      `/search?q=${encodeURIComponent(
                        `Какие режимы и параметры процесса «${p}» известны из мировой практики? В корпусе данные отсутствуют — что стоит изучить в первую очередь?`,
                      )}`,
                    )
                  }
                />
              ))}
              {(gaps.uncovered_materials || []).slice(0, 2).map((m, i) => (
                <Recommendation
                  key={`m${i}`}
                  icon="⚗"
                  text={`Изучить применение материала «${m}» — нет связанных процессов`}
                  onClick={() =>
                    navigate(
                      `/search?q=${encodeURIComponent(
                        `В каких процессах применяется материал «${m}»? В корпусе нет связанных процессов — какие применения известны в мировой практике?`,
                      )}`,
                    )
                  }
                />
              ))}
              {conflictItems.length === 0 &&
                (gaps.uncovered_processes || []).length === 0 &&
                (gaps.uncovered_materials || []).length === 0 && (
                  <div className="text-xs text-nn-muted">
                    Пробелов не обнаружено — корпус покрывает известные темы
                  </div>
                )}
              <button
                onClick={() => navigate('/world')}
                className="text-[11px] text-nn-accent hover:underline"
              >
                Найти зарубежные работы по теме →
              </button>
            </div>
          )}
        </div>

        {/* recent queries */}
        <div className="card">
          <div className="card-title">Последние запросы</div>
          {!queries ? (
            <div className="skeleton h-40" />
          ) : recentQ.length === 0 ? (
            <Empty text="Запросов пока не было — задайте вопрос ИИ" />
          ) : (
            <div className="divide-y divide-nn-border/60">
              {recentQ.map((q, i) => (
                <div
                  key={i}
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate(q.session_id ? `/search?session=${q.session_id}` : '/search')}
                  onKeyDown={(e) => e.key === 'Enter' && navigate(q.session_id ? `/search?session=${q.session_id}` : '/search')}
                  className="flex items-center gap-3 py-2 cursor-pointer group"
                >
                  <span className="text-nn-muted shrink-0">⌕</span>
                  <span className="text-xs truncate flex-1 group-hover:text-nn-accent transition-colors">
                    {q.query}
                  </span>
                  <span className="text-[10px] text-nn-muted shrink-0">
                    {formatWhen(q.created_at)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function MiniStat({ label, value }) {
  return (
    <div className="rounded-xl border border-nn-border bg-nn-panel2/50 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-nn-muted">{label}</div>
      <div className="text-xl font-extrabold text-nn-accent">
        {Number(value).toLocaleString('ru-RU')}
      </div>
    </div>
  )
}

function StatCard({ icon, label, value, accent = 'text-nn-accent' }) {
  return (
    <div className="card !p-4">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-nn-muted">
        <span>{icon}</span>
        {label}
      </div>
      {value === null || value === undefined ? (
        <div className="skeleton h-7 mt-2 w-20" />
      ) : (
        <div className={`text-2xl font-extrabold mt-1 ${accent}`}>
          {typeof value === 'number' ? value.toLocaleString('ru-RU') : value}
        </div>
      )}
    </div>
  )
}

function Recommendation({ icon, text, onClick }) {
  return (
    <div
      onClick={onClick}
      className="flex items-start gap-2.5 rounded-xl border border-nn-border bg-nn-panel2/50 px-3 py-2 text-xs cursor-pointer hover:border-nn-blue/50 transition-colors"
    >
      <span className="shrink-0">{icon}</span>
      <span>{text}</span>
    </div>
  )
}

function Empty({ text }) {
  return <div className="text-xs text-nn-muted text-center py-6">{text}</div>
}

function formatWhen(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const today = new Date()
  const sameDay = d.toDateString() === today.toDateString()
  if (sameDay) return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}
