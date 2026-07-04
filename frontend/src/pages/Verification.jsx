import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getContradictions } from '../api.js'

const LS_KEY = 'hydrax_verify_status'

function loadStatuses() {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY)) || {}
  } catch {
    return {}
  }
}

const STATUS = {
  open: { label: 'Требует проверки', cls: 'text-nn-amber border-nn-amber/40 bg-nn-amber/10' },
  verified: { label: 'Проверено', cls: 'text-nn-green border-nn-green/40 bg-nn-green/10' },
  error: { label: 'Ошибка в данных', cls: 'text-nn-pink border-nn-pink/40 bg-nn-pink/10' },
}

export default function Verification() {
  const [data, setData] = useState(null)
  const [statuses, setStatuses] = useState(loadStatuses)
  const [filter, setFilter] = useState('all')
  const navigate = useNavigate()

  useEffect(() => {
    getContradictions()
      .then(setData)
      .catch(() => setData({ contradictions: [] }))
  }, [])

  const setStatus = (key, value) => {
    const next = { ...statuses, [key]: value }
    setStatuses(next)
    localStorage.setItem(LS_KEY, JSON.stringify(next))
  }

  const items = useMemo(() => {
    const list = (data?.contradictions || []).map((c) => {
      const key = `${c.process}|${c.parameter}|${c.unit}`
      return { ...c, key, status: statuses[key] || 'open' }
    })
    if (filter === 'all') return list
    return list.filter((c) => c.status === filter)
  }, [data, statuses, filter])

  const counts = useMemo(() => {
    const list = (data?.contradictions || []).map((c) => {
      const key = `${c.process}|${c.parameter}|${c.unit}`
      return statuses[key] || 'open'
    })
    return {
      all: list.length,
      open: list.filter((s) => s === 'open').length,
      verified: list.filter((s) => s === 'verified').length,
      error: list.filter((s) => s === 'error').length,
    }
  }, [data, statuses])

  const askAI = (c) => {
    const q = `Какое значение параметра «${c.parameter}» для процесса «${c.process}» корректно: в источниках встречаются значения от ${c.min} до ${c.max} ${c.unit}. Объясни расхождение.`
    navigate(`/search?q=${encodeURIComponent(q)}`)
  }

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-extrabold">Верификация фактов</h1>
          <p className="text-sm text-nn-muted mt-1">
            Конфликтующие значения параметров из разных документов корпуса — источник против источника
          </p>
        </div>
        <div className="flex gap-1.5">
          {[
            ['all', `Все · ${counts.all}`],
            ['open', `Требуют проверки · ${counts.open}`],
            ['verified', `Проверено · ${counts.verified}`],
            ['error', `Ошибки · ${counts.error}`],
          ].map(([id, label]) => (
            <button
              key={id}
              onClick={() => setFilter(id)}
              className={`text-[11px] px-3 py-1.5 rounded-full border transition-colors ${
                filter === id
                  ? 'border-nn-blue/60 bg-nn-blue/15 text-nn-accent font-semibold'
                  : 'border-nn-border text-nn-muted hover:text-nn-text'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {data === null ? (
        <div className="space-y-4">
          {[0, 1].map((i) => (
            <div key={i} className="skeleton h-40" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="card text-center py-14">
          <div className="text-4xl mb-3">✓</div>
          <div className="font-semibold">
            {filter === 'all' ? 'Противоречий в корпусе не найдено' : 'Нет фактов с этим статусом'}
          </div>
          <div className="text-sm text-nn-muted mt-1">
            {filter === 'all'
              ? 'Все значения параметров согласованы между документами'
              : 'Измените фильтр, чтобы увидеть остальные'}
          </div>
        </div>
      ) : (
        items.map((c) => (
          <div key={c.key} className="card space-y-3">
            <div className="flex items-center gap-3 flex-wrap">
              <span className={`text-[11px] px-2.5 py-1 rounded-md border ${STATUS[c.status].cls}`}>
                {STATUS[c.status].label}
              </span>
              <div className="font-bold">
                {c.process} · {c.parameter}
              </div>
              <span className="text-xs text-nn-muted">
                разброс {Math.round(c.spread * 100)}% · источников: {c.sources}
              </span>
              <div className="ml-auto flex gap-2">
                <button
                  onClick={() => askAI(c)}
                  className="text-[11px] px-2.5 py-1 rounded-md border border-nn-blue/50 bg-nn-blue/10 text-nn-accent hover:bg-nn-blue/20 transition-colors"
                >
                  ✦ Спросить ИИ
                </button>
                <button
                  onClick={() => setStatus(c.key, 'verified')}
                  className="text-[11px] px-2.5 py-1 rounded-md border border-nn-green/40 text-nn-green hover:bg-nn-green/10 transition-colors"
                >
                  Проверено
                </button>
                <button
                  onClick={() => setStatus(c.key, 'error')}
                  className="text-[11px] px-2.5 py-1 rounded-md border border-nn-pink/40 text-nn-pink hover:bg-nn-pink/10 transition-colors"
                >
                  Ошибка
                </button>
                {c.status !== 'open' && (
                  <button
                    onClick={() => setStatus(c.key, 'open')}
                    className="text-[11px] px-2.5 py-1 rounded-md border border-nn-border text-nn-muted hover:text-nn-text transition-colors"
                  >
                    Сбросить
                  </button>
                )}
              </div>
            </div>

            <div className="flex items-center gap-4">
              <ValuePill value={c.min} unit={c.unit} tone="blue" />
              <div className="flex-1 h-1.5 rounded-full bg-gradient-to-r from-nn-blue via-nn-amber to-nn-pink" />
              <ValuePill value={c.max} unit={c.unit} tone="pink" />
            </div>
            {c.values.length > 2 && (
              <div className="text-xs text-nn-muted">
                Все значения: {c.values.join(' · ')} {c.unit}
              </div>
            )}

            {c.evidence?.length > 0 && (
              <div className="grid sm:grid-cols-2 gap-3">
                {c.evidence.slice(0, 4).map((e, i) => (
                  <blockquote
                    key={i}
                    className="text-[13px] text-nn-muted border-l-2 border-nn-cyan/60 pl-3 leading-relaxed"
                  >
                    «{e}»
                  </blockquote>
                ))}
              </div>
            )}
            {c.documents?.length > 0 && (
              <div className="text-[11px] text-nn-muted/70">
                Документы: {c.documents.map((d) => d.slice(0, 10)).join(', ')}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  )
}

function ValuePill({ value, unit, tone }) {
  const cls =
    tone === 'blue'
      ? 'text-nn-accent border-nn-blue/40 bg-nn-blue/10'
      : 'text-nn-pink border-nn-pink/40 bg-nn-pink/10'
  return (
    <span className={`px-3 py-1.5 rounded-xl border font-bold text-sm shrink-0 ${cls}`}>
      {value} {unit}
    </span>
  )
}
