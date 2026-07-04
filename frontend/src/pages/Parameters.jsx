import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getParameters } from '../api.js'

export default function Parameters() {
  const [data, setData] = useState(null)
  const [q, setQ] = useState('')
  const [onlyConflicts, setOnlyConflicts] = useState(false)
  const [open, setOpen] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    getParameters()
      .then(setData)
      .catch(() => setData({ rows: [] }))
  }, [])

  const rows = useMemo(() => {
    let list = data?.rows || []
    if (onlyConflicts) list = list.filter((r) => r.conflict)
    const needle = q.trim().toLowerCase()
    if (needle) {
      list = list.filter(
        (r) =>
          r.process.toLowerCase().includes(needle) ||
          r.parameter.toLowerCase().includes(needle) ||
          r.unit.toLowerCase().includes(needle),
      )
    }
    return list
  }, [data, q, onlyConflicts])

  const nConflicts = (data?.rows || []).filter((r) => r.conflict).length

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-extrabold">Параметрический справочник</h1>
          <p className="text-sm text-nn-muted mt-1">
            Все численные параметры процессов из корпуса — значения, единицы, источники
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Фильтр: процесс, параметр, единица…"
            className="bg-nn-panel border border-nn-border rounded-xl px-3 py-2 text-sm outline-none focus:border-nn-blue/60 transition-colors w-64"
          />
          <button
            onClick={() => setOnlyConflicts((v) => !v)}
            className={`text-[11px] px-3 py-2 rounded-xl border transition-colors ${
              onlyConflicts
                ? 'border-nn-pink/50 bg-nn-pink/10 text-nn-pink font-semibold'
                : 'border-nn-border text-nn-muted hover:text-nn-text'
            }`}
          >
            ⚠ Конфликты · {nConflicts}
          </button>
        </div>
      </div>

      {data === null ? (
        <div className="skeleton h-96" />
      ) : rows.length === 0 ? (
        <div className="card text-center py-14">
          <div className="text-4xl mb-3">≡</div>
          <div className="font-semibold">Ничего не найдено</div>
          <div className="text-sm text-nn-muted mt-1">
            {data.rows.length === 0
              ? 'В графе пока нет параметров — запустите пайплайн'
              : 'Попробуйте другой фильтр'}
          </div>
        </div>
      ) : (
        <div className="card !p-0 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-nn-muted border-b border-nn-border">
                <th className="px-4 py-3">Процесс</th>
                <th className="px-4 py-3">Параметр</th>
                <th className="px-4 py-3">Значения</th>
                <th className="px-4 py-3">Единица</th>
                <th className="px-4 py-3 text-right">Источники</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const key = `${r.process}|${r.parameter}|${r.unit}`
                const isOpen = open === key
                return (
                  <RowGroup
                    key={key}
                    row={r}
                    open={isOpen}
                    zebra={i % 2 === 1}
                    onToggle={() => setOpen(isOpen ? null : key)}
                    onProcess={() => navigate(`/graph?entity=${encodeURIComponent(r.process)}`)}
                  />
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function RowGroup({ row, open, zebra, onToggle, onProcess }) {
  return (
    <>
      <tr
        onClick={onToggle}
        className={`cursor-pointer transition-colors hover:bg-nn-blue/5 ${
          zebra ? 'bg-nn-panel2/40' : ''
        } ${row.conflict ? 'border-l-2 border-l-nn-pink' : ''}`}
      >
        <td className="px-4 py-2.5">
          <button
            onClick={(e) => {
              e.stopPropagation()
              onProcess()
            }}
            className="font-semibold text-nn-accent hover:underline"
          >
            {row.process}
          </button>
        </td>
        <td className="px-4 py-2.5">{row.parameter}</td>
        <td className="px-4 py-2.5">
          <span className={row.conflict ? 'font-bold text-nn-pink' : 'font-semibold'}>
            {row.min !== null && row.max !== null && row.min !== row.max
              ? `${row.min} – ${row.max}`
              : row.values[0]?.value}
          </span>
          {row.conflict && (
            <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded border border-nn-pink/40 bg-nn-pink/10 text-nn-pink">
              конфликт
            </span>
          )}
        </td>
        <td className="px-4 py-2.5 text-nn-muted">{row.unit || '—'}</td>
        <td className="px-4 py-2.5 text-right text-nn-muted">{row.values.length}</td>
      </tr>
      {open && (
        <tr className={zebra ? 'bg-nn-panel2/40' : ''}>
          <td colSpan={5} className="px-4 pb-3">
            <div className="rounded-xl border border-nn-border bg-nn-panel2/50 p-3 space-y-2">
              {row.values.map((v, i) => (
                <div key={i} className="text-[13px]">
                  <span className="font-semibold">
                    {v.value} {row.unit}
                  </span>
                  {v.evidence && <span className="text-nn-muted"> — «{v.evidence}»</span>}
                  {v.document_id && (
                    <span className="text-[11px] text-nn-muted/70 ml-2">
                      док. {v.document_id.slice(0, 10)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}
