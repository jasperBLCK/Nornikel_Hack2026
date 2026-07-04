import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getAnalytics, getGaps, getContradictions, getDocuments } from '../api.js'
import { GROUP_COLORS, GROUP_RU } from '../components/GraphView.jsx'

const asNumber = (v) =>
  typeof v === 'number' ? v : Array.isArray(v) ? v.length : 0

export default function Analytics() {
  const [data, setData] = useState(null)
  const [gaps, setGaps] = useState(null)
  const [contra, setContra] = useState(null)
  const [docs, setDocs] = useState(null)
  const navigate = useNavigate()
  const openEntity = (name) => navigate(`/graph?entity=${encodeURIComponent(name)}`)

  useEffect(() => {
    getAnalytics().then(setData).catch(() => setData({}))
    getGaps().then(setGaps).catch(() => setGaps(null))
    getContradictions().then(setContra).catch(() => setContra(null))
    getDocuments()
      .then((d) => setDocs(d.documents || []))
      .catch(() => setDocs(null))
  }, [])

  const health = useMemo(() => {
    if (!data || !gaps) return null
    const nodes = asNumber(data.nodes)
    if (!nodes) return null
    const weak = (gaps.weak_by_label || []).reduce((s, g) => s + g.weak, 0)
    const total = (gaps.weak_by_label || []).reduce((s, g) => s + g.total, 0) || nodes
    const coverage = 1 - weak / total
    const density = Math.min(1, asNumber(data.relations) / (nodes * 2))
    const nContra = (contra?.contradictions || []).length
    const consistency = Math.max(0, 1 - nContra / Math.max(1, nodes / 4))
    const score = Math.round((coverage * 0.45 + density * 0.3 + consistency * 0.25) * 100)
    return { score, coverage, density, consistency, weak, total, nContra }
  }, [data, gaps, contra])

  if (!data)
    return (
      <div className="space-y-5">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="skeleton h-28" />
          ))}
        </div>
        <div className="grid md:grid-cols-2 gap-5">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="skeleton h-64" />
          ))}
        </div>
      </div>
    )

  const noGraph = !data.labels?.length
  const nodes = asNumber(data.nodes)
  const relations = asNumber(data.relations)
  const relTotal = (data.relation_types || []).reduce((s, r) => s + r.count, 0) || 1

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          icon="⛁"
          value={asNumber(data.chunks)}
          label="Фрагментов в индексе"
          sub={docs ? `${docs.length} документов` : '…'}
        />
        <MetricCard
          icon="◉"
          value={nodes}
          label="Узлов графа"
          sub={`${(data.labels || []).length} типов сущностей`}
        />
        <MetricCard
          icon="⇄"
          value={relations}
          label="Связей"
          sub={nodes ? `≈ ${(relations / nodes).toFixed(1)} на узел` : '—'}
        />
        <MetricCard
          icon="✚"
          value={data.neo4j ? 'online' : 'offline'}
          label="Neo4j"
          sub={data.neo4j ? 'граф доступен' : 'граф недоступен'}
          accent={data.neo4j ? 'text-nn-green' : 'text-nn-pink'}
          dot={data.neo4j ? '#12A150' : '#DB2777'}
        />
      </div>

      {noGraph ? (
        <div className="card text-center text-nn-muted py-14">
          Граф пуст — запустите Neo4j и Stage 4, чтобы увидеть аналитику по сущностям.
        </div>
      ) : (
        <>
          <div className="grid lg:grid-cols-3 gap-5 items-stretch">
            {health && (
              <div className="card flex flex-col">
                <div className="card-title">Индекс здоровья графа</div>
                <div className="flex items-center gap-5 flex-1">
                  <Gauge value={health.score} />
                  <div className="space-y-2.5 flex-1 text-sm">
                    <HealthRow
                      label="Покрытие связями"
                      pct={health.coverage}
                      hint={`${health.total - health.weak}/${health.total} сущностей связаны`}
                    />
                    <HealthRow
                      label="Плотность графа"
                      pct={health.density}
                      hint={`${relations} связей на ${nodes} узлов`}
                    />
                    <HealthRow
                      label="Согласованность данных"
                      pct={health.consistency}
                      hint={
                        health.nContra
                          ? `${health.nContra} противоречий в параметрах`
                          : 'противоречий не найдено'
                      }
                    />
                  </div>
                </div>
              </div>
            )}

            <div className="card">
              <div className="card-title">Сущности по типам</div>
              <div className="flex items-center gap-5">
                <Donut
                  items={(data.labels || []).map((l) => ({
                    name: GROUP_RU[l.label] || l.label,
                    value: l.count,
                    color: GROUP_COLORS[l.label] || '#8899AA',
                  }))}
                  total={nodes}
                />
                <div className="space-y-1.5 flex-1 min-w-0">
                  {(data.labels || []).map((l) => (
                    <div key={l.label} className="flex items-center gap-2 text-sm">
                      <span
                        className="w-2.5 h-2.5 rounded-[4px] shrink-0"
                        style={{ background: GROUP_COLORS[l.label] || '#8899AA' }}
                      />
                      <span className="truncate flex-1">{GROUP_RU[l.label] || l.label}</span>
                      <span className="font-semibold">{l.count}</span>
                      <span className="text-nn-muted text-xs w-10 text-right">
                        {Math.round((l.count / Math.max(1, nodes)) * 100)}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="card">
              <div className="card-title">Типы связей</div>
              <div className="space-y-3.5 mt-1">
                {(data.relation_types || []).map((r, i) => (
                  <div key={r.type}>
                    <div className="flex items-baseline justify-between text-sm mb-1">
                      <span className="font-medium">{r.type}</span>
                      <span className="text-nn-muted text-xs">
                        {r.count} · {Math.round((r.count / relTotal) * 100)}%
                      </span>
                    </div>
                    <div className="h-2.5 rounded-full bg-nn-panel2 overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${(r.count / relTotal) * 100}%`,
                          background:
                            i % 2
                              ? 'linear-gradient(90deg,#0077C8,#00A9E0)'
                              : 'linear-gradient(90deg,#00A9E0,#37C4FF)',
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="grid lg:grid-cols-3 gap-5 items-start">
            <div className="card lg:col-span-2">
              <div className="card-title">Топ связанных сущностей — хабы графа</div>
              <HubList items={data.top_entities || []} onOpen={openEntity} />
            </div>

            <div className="card">
              <div className="card-title">Документы корпуса</div>
              {docs === null ? (
                <div className="skeleton h-32" />
              ) : docs.length ? (
                <div className="space-y-2.5">
                  {docs.slice(0, 8).map((d) => (
                    <div key={d.document_id} className="flex items-center gap-3 text-sm">
                      <span className="w-7 h-7 rounded-lg bg-nn-panel2 border border-nn-border flex items-center justify-center text-[13px] shrink-0">
                        📄
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-medium">{d.filename}</div>
                        <div className="text-[11px] text-nn-muted">
                          {d.chunks} фрагм. · {(d.chars / 1000).toFixed(1)} тыс. симв.
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-nn-muted">Документы не проиндексированы</div>
              )}
            </div>
          </div>

          {gaps && (gaps.weak_by_label?.length || gaps.uncovered_materials?.length) ? (
            <div className="card border-nn-amber/40">
              <div className="card-title">Пробелы в знаниях</div>
              <div className="grid md:grid-cols-3 gap-6">
                <div>
                  <div className="text-xs text-nn-muted mb-2.5">
                    Слабо связанные сущности (≤ 1 связи) по типам
                  </div>
                  <div className="space-y-2.5">
                    {(gaps.weak_by_label || []).map((g) => (
                      <div key={g.label}>
                        <div className="flex items-baseline justify-between text-sm mb-1">
                          <span>{GROUP_RU[g.label] || g.label}</span>
                          <span className="text-nn-muted text-xs">
                            {g.weak}/{g.total}
                          </span>
                        </div>
                        <div className="h-2 rounded-full bg-nn-panel2 overflow-hidden">
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${(g.weak / Math.max(1, g.total)) * 100}%`,
                              background: GROUP_COLORS[g.label] || '#D97706',
                            }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-nn-muted mb-2.5">
                    Материалы без связанного процесса — неизученные комбинации
                  </div>
                  <TagList items={gaps.uncovered_materials || []} color="text-nn-cyan" onClick={openEntity} />
                </div>
                <div>
                  <div className="text-xs text-nn-muted mb-2.5">
                    Процессы без условий/параметров — нет числовых данных
                  </div>
                  <TagList items={gaps.uncovered_processes || []} color="text-nn-green" />
                </div>
              </div>
            </div>
          ) : null}
        </>
      )}
    </div>
  )
}

function MetricCard({ icon, value, label, sub, accent = 'text-nn-accent', dot }) {
  return (
    <div className="card relative overflow-hidden">
      <div
        className="absolute -top-8 -right-8 w-24 h-24 rounded-full opacity-[.07]"
        style={{ background: 'radial-gradient(circle,#0077C8,transparent 70%)' }}
      />
      <div className="flex items-start justify-between">
        <span className="w-9 h-9 rounded-xl bg-nn-panel2 border border-nn-border flex items-center justify-center text-nn-accent text-lg">
          {icon}
        </span>
        {dot && (
          <span className="w-2.5 h-2.5 rounded-full mt-1" style={{ background: dot }} />
        )}
      </div>
      <div className={`text-3xl font-extrabold mt-3 ${accent}`}>
        {typeof value === 'number' ? value.toLocaleString('ru-RU') : value}
      </div>
      <div className="text-[11px] uppercase tracking-wider text-nn-muted mt-1">{label}</div>
      <div className="text-xs text-nn-muted/80 mt-0.5">{sub}</div>
    </div>
  )
}

function Gauge({ value }) {
  const r = 52
  const c = 2 * Math.PI * r
  const color = value >= 70 ? '#12A150' : value >= 40 ? '#D97706' : '#DB2777'
  return (
    <div className="relative w-32 h-32 shrink-0">
      <svg viewBox="0 0 128 128" className="w-32 h-32 -rotate-90">
        <circle cx="64" cy="64" r={r} fill="none" stroke="#EDF4FB" strokeWidth="12" />
        <circle
          cx="64"
          cy="64"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray={`${(value / 100) * c} ${c}`}
          style={{ transition: 'stroke-dasharray .8s ease' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-extrabold" style={{ color }}>
          {value}
        </span>
        <span className="text-[10px] uppercase tracking-wider text-nn-muted">из 100</span>
      </div>
    </div>
  )
}

function HealthRow({ label, pct, hint }) {
  const v = Math.round(pct * 100)
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span>{label}</span>
        <span className="text-nn-muted text-xs">{v}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-nn-panel2 overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-nn-blue to-nn-cyan"
          style={{ width: `${v}%` }}
        />
      </div>
      <div className="text-[11px] text-nn-muted/80 mt-0.5">{hint}</div>
    </div>
  )
}

function Donut({ items, total }) {
  const r = 42
  const c = 2 * Math.PI * r
  const segments = items.reduce((acc, it) => {
    const prev = acc.length ? acc[acc.length - 1] : { end: 0 }
    const frac = it.value / Math.max(1, total)
    acc.push({ ...it, start: prev.end, end: prev.end + frac })
    return acc
  }, [])
  return (
    <div className="relative w-28 h-28 shrink-0">
      <svg viewBox="0 0 112 112" className="w-28 h-28 -rotate-90">
        {segments.map((it) => (
          <circle
            key={it.name}
            cx="56"
            cy="56"
            r={r}
            fill="none"
            stroke={it.color}
            strokeWidth="14"
            strokeDasharray={`${(it.end - it.start) * c} ${c}`}
            strokeDashoffset={-it.start * c}
          />
        ))}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-xl font-extrabold text-nn-text">{total}</span>
        <span className="text-[9px] uppercase tracking-wider text-nn-muted">узлов</span>
      </div>
    </div>
  )
}

function HubList({ items, onOpen }) {
  const max = Math.max(1, ...items.map((e) => e.degree))
  return (
    <div className="space-y-1">
      {items.map((e, i) => (
        <button
          key={e.name}
          onClick={() => onOpen(e.name)}
          title="Открыть досье сущности"
          className="w-full flex items-center gap-3 text-sm rounded-xl px-2 py-1.5 hover:bg-nn-panel2 transition-colors cursor-pointer text-left group"
        >
          <span
            className={`w-6 h-6 rounded-lg flex items-center justify-center text-[11px] font-bold shrink-0 ${
              i < 3 ? 'bg-nn-blue/15 text-nn-accent' : 'bg-nn-panel2 text-nn-muted'
            }`}
          >
            {i + 1}
          </span>
          <span className="w-48 truncate shrink-0 group-hover:text-nn-accent transition-colors font-medium">
            {e.name}
          </span>
          <span
            className="px-1.5 py-0.5 rounded-md text-[10px] shrink-0 border"
            style={{
              color: GROUP_COLORS[e.label] || '#8899AA',
              borderColor: `${GROUP_COLORS[e.label] || '#8899AA'}55`,
              background: `${GROUP_COLORS[e.label] || '#8899AA'}12`,
            }}
          >
            {GROUP_RU[e.label] || e.label}
          </span>
          <span className="flex-1 h-2 rounded-full bg-nn-panel2 overflow-hidden">
            <span
              className="block h-full rounded-full"
              style={{
                width: `${(e.degree / max) * 100}%`,
                background: `linear-gradient(90deg, ${GROUP_COLORS[e.label] || '#8899AA'}, ${
                  GROUP_COLORS[e.label] || '#8899AA'
                }99)`,
              }}
            />
          </span>
          <span className="w-14 text-right text-nn-muted text-xs shrink-0">
            {e.degree} связ.
          </span>
        </button>
      ))}
    </div>
  )
}

function TagList({ items, color, onClick }) {
  if (!items.length)
    return <div className="text-xs text-nn-muted">Пробелов не найдено</div>
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((name) =>
        onClick ? (
          <button
            key={name}
            onClick={() => onClick(name)}
            className={`px-2 py-0.5 rounded-md bg-nn-panel2 border border-nn-border text-[11px] hover:border-nn-blue/50 transition-colors cursor-pointer ${color}`}
          >
            {name}
          </button>
        ) : (
          <span
            key={name}
            className={`px-2 py-0.5 rounded-md bg-nn-panel2 border border-nn-border text-[11px] ${color}`}
          >
            {name}
          </span>
        ),
      )}
    </div>
  )
}
