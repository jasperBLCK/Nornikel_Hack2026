import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getEntity, getFullGraph, getStats } from '../api.js'
import GraphView, { GROUP_RU } from '../components/GraphView.jsx'

const LIMITS = [100, 200, 500, 1000]

export default function GraphExplorer() {
  const [limit, setLimit] = useState(200)
  const [graph, setGraph] = useState(null)
  const [stats, setStats] = useState(null)
  const [dossier, setDossier] = useState(null)
  const [dossierBusy, setDossierBusy] = useState(false)
  const [params, setParams] = useSearchParams()
  const loading = graph === null

  const openDossier = (name, group) => {
    setDossierBusy(true)
    setDossier({ name, group })
    getEntity(name)
      .then((d) => setDossier({ ...d, group }))
      .catch(() => {})
      .finally(() => setDossierBusy(false))
  }

  useEffect(() => {
    getStats().then(setStats).catch(() => setStats({}))
  }, [])

  const entityParam = params.get('entity')
  useEffect(() => {
    if (!entityParam) return
    const t = setTimeout(() => openDossier(entityParam, null), 0)
    return () => clearTimeout(t)
  }, [entityParam])

  useEffect(() => {
    let cancelled = false
    getFullGraph(limit)
      .then((g) => !cancelled && setGraph(g))
      .catch(() => !cancelled && setGraph({ nodes: [], edges: [] }))
    return () => {
      cancelled = true
    }
  }, [limit])

  const changeLimit = (l) => {
    setGraph(null)
    setLimit(l)
  }

  return (
    <div className={`grid gap-5 items-start ${dossier ? 'xl:grid-cols-[minmax(0,1fr)_340px]' : ''}`}>
    <div className="card">
      <div className="card-title">
        Обзор графа знаний
        <span className="ml-auto flex items-center gap-2 normal-case tracking-normal font-medium">
          <span className="text-[11px]">связей:</span>
          {LIMITS.map((l) => (
            <button
              key={l}
              onClick={() => changeLimit(l)}
              className={`text-[11px] px-2.5 py-1 rounded-md border transition-colors ${
                limit === l
                  ? 'border-nn-blue/60 bg-nn-blue/20 text-nn-accent'
                  : 'border-nn-border text-nn-muted hover:text-nn-text'
              }`}
            >
              {l}
            </button>
          ))}
        </span>
      </div>
      {graph && (
        <p className="text-xs text-nn-muted mb-3">
          Показано {graph.nodes?.length || 0} узлов и {graph.edges?.length || 0} связей.
          Клик по узлу — досье сущности; перетаскивайте узлы, колесо мыши — масштаб.
        </p>
      )}
      {loading ? (
        <div className="skeleton" style={{ height: 'calc(100vh - 260px)' }} />
      ) : !graph.nodes?.length ? (
        <div
          className="grid place-items-center text-center text-sm text-nn-muted border border-dashed border-nn-border rounded-xl px-6"
          style={{ height: Math.max(480, window.innerHeight - 260) }}
        >
          <div className="space-y-2">
            <div className="text-nn-text font-semibold">Граф пуст</div>
            {stats && !stats.neo4j ? (
              <p>
                Neo4j недоступен: запустите базу (например,{' '}
                <code>docker compose up -d neo4j</code>) и задайте{' '}
                <code>NEO4J_PASSWORD</code> перед стартом приложения.
              </p>
            ) : (
              <p>
                Neo4j доступен, но узлов нет — прогоните пайплайн{' '}
                (<code>python run_pipeline.py</code>, Stage 4), чтобы загрузить граф.
              </p>
            )}
          </div>
        </div>
      ) : (
        <GraphView
          graph={graph}
          height={Math.max(480, window.innerHeight - 260)}
          physics={true}
          onNodeClick={openDossier}
        />
      )}
    </div>

    {dossier && (
      <div className="card xl:sticky xl:top-20 max-h-[calc(100vh-120px)] overflow-y-auto">
        <div className="card-title">
          Досье сущности
          <button
            onClick={() => {
              setDossier(null)
              if (params.get('entity')) setParams({}, { replace: true })
            }}
            className="ml-auto normal-case tracking-normal text-nn-muted hover:text-nn-pink"
          >
            ✕
          </button>
        </div>
        <div className="font-bold text-lg">{dossier.name}</div>
        {dossier.group && (
          <div className="text-[11px] text-nn-muted mb-3">{GROUP_RU[dossier.group] || dossier.group}</div>
        )}
        {dossierBusy ? (
          <div className="space-y-2">
            <div className="skeleton h-4" />
            <div className="skeleton h-4" />
            <div className="skeleton h-4" />
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <div className="text-[11px] uppercase tracking-wider text-nn-muted mb-1.5">
                Связи в графе · {(dossier.facts || []).length}
              </div>
              <div className="space-y-1.5">
                {(dossier.facts || []).slice(0, 12).map((f, i) => (
                  <div key={i} className="text-xs rounded-lg border border-nn-border bg-nn-panel2/60 px-2.5 py-1.5">
                    <b>{f.source}</b> <span className="text-nn-blue">—{f.relation}→</span> <b>{f.target}</b>
                    {f.evidence && (
                      <div className="text-[11px] text-nn-muted mt-0.5">«{f.evidence.slice(0, 120)}…»</div>
                    )}
                  </div>
                ))}
                {(dossier.facts || []).length === 0 && (
                  <div className="text-xs text-nn-muted">Связей не найдено</div>
                )}
              </div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wider text-nn-muted mb-1.5">
                Упоминания в корпусе
              </div>
              <div className="space-y-1.5">
                {(dossier.chunks || []).map((c, i) => (
                  <div key={i} className="text-xs rounded-lg border border-nn-border bg-nn-panel2/60 px-2.5 py-1.5">
                    <div className="font-semibold text-nn-blue mb-0.5">{c.filename}</div>
                    <div className="text-nn-muted">{c.text.slice(0, 180)}…</div>
                  </div>
                ))}
                {(dossier.chunks || []).length === 0 && (
                  <div className="text-xs text-nn-muted">Фрагментов не найдено</div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    )}
    </div>
  )
}
