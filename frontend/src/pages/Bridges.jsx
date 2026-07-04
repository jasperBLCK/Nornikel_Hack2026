import { useEffect, useMemo, useState } from 'react'
import { getEntities, getPath } from '../api.js'
import GraphView, { GROUP_COLORS, GROUP_RU } from '../components/GraphView.jsx'

export default function Bridges() {
  const [entities, setEntities] = useState([])
  const [source, setSource] = useState('')
  const [target, setTarget] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getEntities()
      .then((d) => setEntities(d.entities || []))
      .catch(() => {})
  }, [])

  const find = () => {
    if (!source || !target || source === target) return
    setBusy(true)
    setResult(null)
    getPath(source, target)
      .then(setResult)
      .catch(() => setResult({ paths: [], nodes: [], edges: [] }))
      .finally(() => setBusy(false))
  }

  const swap = () => {
    setSource(target)
    setTarget(source)
  }

  const graph = useMemo(() => {
    if (!result?.nodes?.length) return null
    return { nodes: result.nodes, edges: result.edges }
  }, [result])

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold">Связи-мосты</h1>
        <p className="text-sm text-nn-muted mt-1">
          Как связаны две сущности корпуса: кратчайшие цепочки фактов между ними в графе знаний
        </p>
      </div>

      <div className="card flex items-center gap-3 flex-wrap">
        <EntityPicker
          value={source}
          onChange={setSource}
          entities={entities}
          placeholder="Первая сущность…"
        />
        <button
          onClick={swap}
          title="Поменять местами"
          className="w-9 h-9 rounded-xl border border-nn-border text-nn-muted hover:text-nn-text hover:border-nn-blue/50 transition-colors"
        >
          ⇄
        </button>
        <EntityPicker
          value={target}
          onChange={setTarget}
          entities={entities}
          placeholder="Вторая сущность…"
        />
        <button
          onClick={find}
          disabled={!source || !target || source === target || busy}
          className="px-5 py-2 rounded-xl font-semibold text-white bg-gradient-to-r from-nn-blue to-nn-cyan disabled:opacity-50 hover:brightness-110 transition-all"
        >
          Найти связь
        </button>
      </div>

      {busy ? (
        <div className="skeleton h-80" />
      ) : result === null ? (
        <div className="card text-center py-14">
          <div className="text-4xl mb-3">⌘</div>
          <div className="font-semibold">Выберите две сущности</div>
          <div className="text-sm text-nn-muted mt-1">
            Например: «медь» и «никель» — граф покажет, через какие процессы и параметры они связаны
          </div>
        </div>
      ) : result.paths.length === 0 ? (
        <div className="card text-center py-14">
          <div className="text-4xl mb-3">∅</div>
          <div className="font-semibold">Путь не найден</div>
          <div className="text-sm text-nn-muted mt-1">
            В пределах 4 шагов эти сущности не связаны — возможно, это белое пятно корпуса
          </div>
        </div>
      ) : (
        <div className="grid lg:grid-cols-[1fr_380px] gap-5 items-start">
          <div className="card">
            <div className="card-title">Граф связи</div>
            <GraphView graph={graph} height={380} physics={false} />
            <div className="flex flex-wrap gap-3 mt-3">
              {Object.entries(GROUP_RU).map(([g, ru]) => (
                <span key={g} className="flex items-center gap-1.5 text-[11px] text-nn-muted">
                  <span
                    className="w-2.5 h-2.5 rounded-full inline-block"
                    style={{ background: GROUP_COLORS[g] }}
                  />
                  {ru}
                </span>
              ))}
            </div>
          </div>

          <div className="space-y-4">
            {result.paths.map((steps, i) => (
              <div key={i} className="card">
                <div className="card-title">
                  Цепочка {i + 1} · {steps.length} {steps.length === 1 ? 'шаг' : 'шага'}
                </div>
                <ol className="space-y-2.5">
                  {steps.map((s, j) => (
                    <li key={j} className="text-[13px]">
                      <div>
                        <b>{s.from}</b>{' '}
                        <span className="text-nn-accent font-semibold text-[11px]">{s.label}</span>{' '}
                        <b>{s.to}</b>
                      </div>
                      {s.evidence && (
                        <blockquote className="text-nn-muted border-l-2 border-nn-cyan/60 pl-2.5 mt-1 leading-relaxed">
                          «{s.evidence}»
                        </blockquote>
                      )}
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function EntityPicker({ value, onChange, entities, placeholder }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="flex-1 min-w-44 bg-nn-panel border border-nn-border rounded-xl px-3 py-2 text-sm outline-none focus:border-nn-blue/60 transition-colors"
    >
      <option value="">{placeholder}</option>
      {entities.map((e) => (
        <option key={e.name} value={e.name}>
          {e.name} · {GROUP_RU[e.label] || e.label}
        </option>
      ))}
    </select>
  )
}
