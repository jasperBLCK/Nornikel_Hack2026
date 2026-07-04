import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getContradictions, getGaps, logExport } from '../api.js'

const PRIORITY = {
  high: { label: 'Высокий', cls: 'text-nn-pink border-nn-pink/40 bg-nn-pink/10' },
  medium: { label: 'Средний', cls: 'text-nn-amber border-nn-amber/40 bg-nn-amber/10' },
  low: { label: 'Низкий', cls: 'text-nn-cyan border-nn-cyan/40 bg-nn-cyan/10' },
}

function buildTopics(gaps, contra) {
  const topics = []
  for (const c of contra?.contradictions || []) {
    topics.push({
      id: `contra|${c.process}|${c.parameter}`,
      priority: c.spread >= 0.3 ? 'high' : 'medium',
      score: Math.round(50 + c.spread * 100 + c.sources * 10),
      kind: 'Противоречие в данных',
      title: `Уточнить параметр «${c.parameter}» процесса «${c.process}»`,
      why: `Источники расходятся: от ${c.min} до ${c.max} ${c.unit} (разброс ${Math.round(
        c.spread * 100,
      )}%, источников: ${c.sources}). Нужен верификационный эксперимент или анализ условий.`,
      query: `Составь техническое задание на исследование: уточнение параметра «${c.parameter}» процесса «${c.process}» — в корпусе значения от ${c.min} до ${c.max} ${c.unit}. Сформулируй цель, гипотезы и методику.`,
    })
  }
  for (const m of gaps?.uncovered_materials || []) {
    topics.push({
      id: `mat|${m}`,
      priority: 'medium',
      score: 45,
      kind: 'Белое пятно',
      title: `Методы переработки материала «${m}»`,
      why: `Материал упоминается в корпусе, но не связан ни с одним процессом — направление не исследовано или знания не оцифрованы.`,
      query: `Составь техническое задание на исследование методов переработки материала «${m}»: что известно из корпуса, какие процессы стоит испытать, какие параметры контролировать.`,
    })
  }
  for (const p of gaps?.uncovered_processes || []) {
    topics.push({
      id: `proc|${p}`,
      priority: 'low',
      score: 30,
      kind: 'Неполные данные',
      title: `Задокументировать режимы процесса «${p}»`,
      why: `Для процесса нет ни условий, ни численных параметров — воспроизвести его по корпусу невозможно.`,
      query: `Какие условия и параметры процесса «${p}» известны? Составь план сбора недостающих данных для его воспроизводимости.`,
    })
  }
  topics.sort((a, b) => b.score - a.score)
  return topics
}

export default function Radar() {
  const [gaps, setGaps] = useState(null)
  const [contra, setContra] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    getGaps()
      .then(setGaps)
      .catch(() => setGaps({}))
    getContradictions()
      .then(setContra)
      .catch(() => setContra({ contradictions: [] }))
  }, [])

  const loading = gaps === null || contra === null
  const topics = useMemo(() => (loading ? [] : buildTopics(gaps, contra)), [gaps, contra, loading])

  const exportMd = () => {
    logExport('md', 'research-radar').catch(() => {})
    let md = `# HydraX — рекомендации исследований\n\n_Сформировано из пробелов и противоречий графа знаний · ${new Date().toLocaleDateString('ru-RU')}_\n\n`
    for (const [i, t] of topics.entries()) {
      md += `## ${i + 1}. ${t.title}\n\n- **Приоритет:** ${PRIORITY[t.priority].label}\n- **Сигнал:** ${t.kind}\n- **Обоснование:** ${t.why}\n\n`
    }
    const blob = new Blob([md], { type: 'text/markdown' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'hydrax-research-radar.md'
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-extrabold">Радар исследований</h1>
          <p className="text-sm text-nn-muted mt-1">
            Что исследовать дальше: приоритизированные темы из пробелов и противоречий графа знаний
          </p>
        </div>
        {topics.length > 0 && (
          <button
            onClick={exportMd}
            className="text-[11px] px-3 py-2 rounded-xl border border-nn-border text-nn-muted hover:text-nn-text hover:border-nn-blue/50 transition-colors"
          >
            ⬇ Экспорт плана .md
          </button>
        )}
      </div>

      {loading ? (
        <div className="space-y-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton h-28" />
          ))}
        </div>
      ) : topics.length === 0 ? (
        <div className="card text-center py-14">
          <div className="text-4xl mb-3">◎</div>
          <div className="font-semibold">Радар чист</div>
          <div className="text-sm text-nn-muted mt-1">
            Граф не выявил ни пробелов, ни противоречий — корпус согласован
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {topics.map((t, i) => (
            <div key={t.id} className="card flex gap-4 items-start">
              <div className="w-10 h-10 shrink-0 rounded-xl bg-nn-panel2 border border-nn-border grid place-items-center font-extrabold text-nn-accent">
                {i + 1}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2.5 flex-wrap">
                  <span className={`text-[10px] px-2 py-0.5 rounded border ${PRIORITY[t.priority].cls}`}>
                    приоритет: {PRIORITY[t.priority].label}
                  </span>
                  <span className="text-[10px] px-2 py-0.5 rounded border border-nn-border text-nn-muted">
                    {t.kind}
                  </span>
                </div>
                <div className="font-bold mt-1.5">{t.title}</div>
                <p className="text-[13px] text-nn-muted mt-1 leading-relaxed">{t.why}</p>
              </div>
              <button
                onClick={() => navigate(`/search?q=${encodeURIComponent(t.query)}`)}
                className="shrink-0 text-[11px] px-3 py-2 rounded-xl border border-nn-blue/50 bg-nn-blue/10 text-nn-accent hover:bg-nn-blue/20 transition-colors font-semibold"
              >
                ✦ Сформулировать ТЗ
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
