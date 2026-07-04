import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getMatrix } from '../api.js'

export default function CoverageMatrix() {
  const [data, setData] = useState(null)
  const [hover, setHover] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    getMatrix()
      .then(setData)
      .catch(() => setData({ materials: [], processes: [], cells: [] }))
  }, [])

  const cellMap = useMemo(() => {
    const m = new Map()
    for (const c of data?.cells || []) m.set(`${c.process}|${c.material}`, c)
    return m
  }, [data])

  const covered = data ? data.cells.length : 0
  const total = data ? data.processes.length * data.materials.length : 0
  const pct = total ? Math.round((covered / total) * 100) : 0

  const onCell = (process, material, cell) => {
    if (cell) {
      navigate(`/graph?entity=${encodeURIComponent(process)}`)
    } else {
      const q = `Что известно о применении процесса «${process}» для материала «${material}»? Если данных в корпусе нет — какие исследования стоило бы провести?`
      navigate(`/search?q=${encodeURIComponent(q)}`)
    }
  }

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-extrabold">Матрица покрытия</h1>
          <p className="text-sm text-nn-muted mt-1">
            Материал × Процесс: какие комбинации изучены в корпусе, а где — белые пятна
          </p>
        </div>
        <div className="flex items-center gap-4 text-xs text-nn-muted">
          <span className="flex items-center gap-1.5">
            <span className="w-3.5 h-3.5 rounded bg-gradient-to-br from-nn-blue to-nn-cyan inline-block" />
            есть данные
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-3.5 h-3.5 rounded border border-dashed border-nn-border bg-nn-panel inline-block" />
            белое пятно
          </span>
          <span className="px-2.5 py-1 rounded-md border border-nn-border font-semibold text-nn-accent">
            покрытие {pct}%
          </span>
        </div>
      </div>

      {data === null ? (
        <div className="skeleton h-96" />
      ) : !data.processes.length || !data.materials.length ? (
        <div className="card text-center py-14">
          <div className="text-4xl mb-3">▦</div>
          <div className="font-semibold">Граф знаний пуст</div>
          <div className="text-sm text-nn-muted mt-1">Запустите пайплайн, чтобы построить матрицу</div>
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="border-separate" style={{ borderSpacing: 4 }}>
            <thead>
              <tr>
                <th />
                {data.materials.map((m) => (
                  <th key={m} className="pb-1 align-bottom">
                    <div
                      className="text-[10px] font-semibold text-nn-muted whitespace-nowrap"
                      style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)', maxHeight: 110 }}
                    >
                      {m}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.processes.map((p) => (
                <tr key={p}>
                  <td className="pr-2 text-xs font-semibold text-nn-muted whitespace-nowrap text-right">
                    {p}
                  </td>
                  {data.materials.map((m) => {
                    const cell = cellMap.get(`${p}|${m}`)
                    const key = `${p}|${m}`
                    return (
                      <td key={m}>
                        <button
                          onClick={() => onCell(p, m, cell)}
                          onMouseEnter={() => setHover(key)}
                          onMouseLeave={() => setHover(null)}
                          title={
                            cell
                              ? `${p} × ${m}: ${cell.evidence || 'есть связь в графе'}`
                              : `${p} × ${m}: данных нет — сформулировать исследовательский вопрос`
                          }
                          className={`w-8 h-8 rounded-md transition-all ${
                            cell
                              ? 'bg-gradient-to-br from-nn-blue to-nn-cyan hover:brightness-110 hover:scale-110'
                              : 'border border-dashed border-nn-border bg-nn-panel hover:border-nn-amber hover:bg-nn-amber/10'
                          } ${hover === key ? 'ring-2 ring-nn-blue/30' : ''}`}
                        />
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[11px] text-nn-muted mt-4">
            Клик по заполненной клетке открывает досье процесса в графе; клик по белому пятну —
            формулирует исследовательский вопрос в чате.
          </p>
        </div>
      )}
    </div>
  )
}
