import { useEffect, useMemo, useState } from 'react'
import { getDocuments } from '../api.js'

export default function Documents() {
  const [docs, setDocs] = useState(null)
  const [total, setTotal] = useState(null)
  const [filter, setFilter] = useState('')
  const [sortKey, setSortKey] = useState('chunks')

  useEffect(() => {
    getDocuments()
      .then((d) => {
        setDocs(d.documents)
        setTotal(d.total ?? d.documents.length)
      })
      .catch(() => setDocs([]))
  }, [])

  const shown = useMemo(() => {
    if (!docs) return null
    const f = filter.toLowerCase()
    const filtered = f ? docs.filter((d) => d.filename.toLowerCase().includes(f)) : docs
    return [...filtered].sort((a, b) =>
      sortKey === 'filename'
        ? a.filename.localeCompare(b.filename, 'ru')
        : b[sortKey] - a[sortKey],
    )
  }, [docs, filter, sortKey])

  const maxChunks = useMemo(() => Math.max(1, ...(docs || []).map((d) => d.chunks)), [docs])

  return (
    <div className="card">
      <div className="card-title">
        Документы корпуса {docs ? `· ${total ?? docs.length}` : ''}
        {docs && total > docs.length && (
          <span className="ml-2 text-[11px] normal-case tracking-normal font-normal text-nn-muted">
            показаны {docs.length}
          </span>
        )}
        <input
          className="ml-auto normal-case tracking-normal font-normal bg-nn-panel2 border border-nn-border rounded-lg px-3 py-1.5 text-sm text-nn-text outline-none focus:border-nn-blue/60 w-72"
          placeholder="Фильтр по имени файла…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>

      {!shown ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="skeleton h-10" />
          ))}
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wider text-nn-muted border-b border-nn-border">
              <Th onClick={() => setSortKey('filename')} active={sortKey === 'filename'}>
                Файл
              </Th>
              <Th onClick={() => setSortKey('chunks')} active={sortKey === 'chunks'} right>
                Фрагментов
              </Th>
              <Th onClick={() => setSortKey('chars')} active={sortKey === 'chars'} right>
                Символов
              </Th>
              <th className="py-2 pl-6 w-56">Доля корпуса</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((d) => (
              <tr key={d.document_id} className="border-b border-nn-border/50 hover:bg-nn-panel2/50">
                <td className="py-2.5 pr-4 font-medium truncate max-w-md">
                  {d.filename}
                  {d.sensitivity && (
                    <span
                      className={`ml-2 text-[10px] px-1.5 py-0.5 rounded border align-middle ${
                        d.sensitivity === 'confidential'
                          ? 'text-nn-amber border-nn-amber/40 bg-nn-amber/10'
                          : d.sensitivity === 'internal'
                            ? 'text-nn-cyan border-nn-cyan/40 bg-nn-cyan/10'
                            : 'text-nn-green border-nn-green/40 bg-nn-green/10'
                      }`}
                    >
                      {d.sensitivity === 'confidential'
                        ? 'коммерч. тайна'
                        : d.sensitivity === 'internal'
                          ? 'внутренний'
                          : 'открытый'}
                    </span>
                  )}
                </td>
                <td className="py-2.5 text-right text-nn-accent font-semibold">{d.chunks}</td>
                <td className="py-2.5 text-right text-nn-muted">
                  {d.chars.toLocaleString('ru-RU')}
                </td>
                <td className="py-2.5 pl-6">
                  <div className="h-1.5 rounded-full bg-nn-border overflow-hidden">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-nn-blue to-nn-cyan"
                      style={{ width: `${(d.chunks / maxChunks) * 100}%` }}
                    />
                  </div>
                </td>
              </tr>
            ))}
            {shown.length === 0 && (
              <tr>
                <td colSpan={4} className="py-8 text-center text-nn-muted">
                  Ничего не найдено
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}

function Th({ children, onClick, active, right }) {
  return (
    <th
      onClick={onClick}
      className={`py-2 cursor-pointer select-none hover:text-nn-text ${
        right ? 'text-right' : ''
      } ${active ? 'text-nn-accent' : ''}`}
    >
      {children} {active ? '↓' : ''}
    </th>
  )
}
