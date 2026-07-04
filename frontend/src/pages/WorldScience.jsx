import { useState } from 'react'
import { getWorld } from '../api.js'

const EXAMPLES = [
  'электроэкстракция никеля',
  'кучное выщелачивание меди',
  'удаление SO2 из отходящих газов',
  'обессоливание шахтных вод',
  'флотация сульфидных руд',
]

export default function WorldScience() {
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [showOriginal, setShowOriginal] = useState(false)

  const run = (q) => {
    const text = (q || '').trim()
    if (!text || busy) return
    setBusy(true)
    setError('')
    setData(null)
    getWorld(text, 10)
      .then((d) => {
        if (d.error) setError(d.error)
        setData(d)
      })
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(false))
  }

  const works = data?.works || []
  const trends = data?.trends || []
  const maxTrend = Math.max(1, ...trends.map((t) => t.count))

  return (
    <div className="space-y-5 max-w-6xl mx-auto">
      <div className="text-center pt-2">
        <h2 className="text-2xl font-extrabold">
          Мировая наука <span className="text-nn-blue">по вашей теме</span>
        </h2>
        <p className="text-sm text-nn-muted mt-1">
          Поиск зарубежных публикаций через OpenAlex (250+ млн работ) · автоперевод
          заголовков и аннотаций · тренды исследований по годам
        </p>
      </div>

      <div className="flex gap-2 max-w-3xl mx-auto">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && run(query)}
          placeholder="Тема на русском — переведём и найдём зарубежные работы…"
          className="flex-1 px-4 py-2.5 rounded-xl bg-nn-panel border border-nn-border outline-none focus:border-nn-blue text-sm"
        />
        <button
          onClick={() => run(query)}
          disabled={busy}
          className="px-6 py-2.5 rounded-xl font-semibold text-white bg-gradient-to-r from-nn-blue to-nn-cyan disabled:opacity-60 hover:brightness-110 transition-all"
        >
          {busy ? 'Ищу…' : 'Найти'}
        </button>
      </div>

      {!data && !busy && (
        <div className="flex flex-wrap justify-center gap-2">
          {EXAMPLES.map((e) => (
            <button
              key={e}
              onClick={() => {
                setQuery(e)
                run(e)
              }}
              className="px-3 py-1.5 rounded-full text-xs border border-nn-border bg-nn-panel text-nn-muted hover:text-nn-blue hover:border-nn-blue/50 transition-colors"
            >
              {e}
            </button>
          ))}
        </div>
      )}

      {busy && (
        <div className="space-y-3 max-w-4xl mx-auto">
          <div className="skeleton h-24" />
          <div className="skeleton h-24" />
          <div className="skeleton h-24" />
          <div className="text-center text-xs text-nn-muted">
            Ищу в OpenAlex и перевожу через YandexGPT…
          </div>
        </div>
      )}

      {error && (
        <div className="card max-w-3xl mx-auto text-sm text-nn-pink">
          Ошибка запроса: {error}
        </div>
      )}

      {data && !busy && (
        <div className="grid xl:grid-cols-[minmax(0,1fr)_300px] gap-5 items-start">
          <div className="space-y-3">
            <div className="flex items-center gap-3 text-xs text-nn-muted">
              <span>
                Найдено <b className="text-nn-text">{Number(data.total).toLocaleString('ru-RU')}</b>{' '}
                работ по запросу «{data.query_en}»
              </span>
              <label className="ml-auto flex items-center gap-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={showOriginal}
                  onChange={(e) => setShowOriginal(e.target.checked)}
                />
                показать оригинал (EN)
              </label>
            </div>
            {works.map((w) => (
              <div key={w.id} className="card !p-4">
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-sm leading-snug">
                      {showOriginal ? w.title : w.title_ru || w.title}
                    </div>
                    {!showOriginal && w.title_ru && (
                      <div className="text-[11px] text-nn-muted mt-0.5 italic truncate">
                        {w.title}
                      </div>
                    )}
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="text-nn-blue font-bold text-sm">{w.year || '—'}</div>
                    <div className="text-[10px] text-nn-muted">цитирований: {w.cited_by}</div>
                  </div>
                </div>
                {(showOriginal ? w.abstract : w.abstract_ru || w.abstract) && (
                  <p className="text-xs text-nn-muted mt-2 leading-relaxed">
                    {showOriginal ? w.abstract : w.abstract_ru || w.abstract}
                  </p>
                )}
                <div className="flex flex-wrap items-center gap-2 mt-2 text-[11px] text-nn-muted">
                  {w.authors.length > 0 && <span>{w.authors.join(', ')}</span>}
                  {w.venue && (
                    <span className="px-2 py-0.5 rounded-full bg-nn-panel2 border border-nn-border">
                      {w.venue}
                    </span>
                  )}
                  {w.open_access && (
                    <span className="px-2 py-0.5 rounded-full text-nn-green border border-nn-green/40 bg-nn-green/10">
                      Open Access
                    </span>
                  )}
                  {w.doi && (
                    <a
                      href={w.doi}
                      target="_blank"
                      rel="noreferrer"
                      className="text-nn-blue hover:underline ml-auto"
                    >
                      DOI →
                    </a>
                  )}
                </div>
              </div>
            ))}
            {works.length === 0 && (
              <div className="card text-sm text-nn-muted text-center">
                Ничего не найдено — попробуйте переформулировать запрос
              </div>
            )}
          </div>

          <div className="card xl:sticky xl:top-20">
            <div className="card-title">Тренд публикаций по годам</div>
            {trends.length === 0 ? (
              <div className="text-xs text-nn-muted">Нет данных</div>
            ) : (
              <div className="space-y-1.5">
                {trends.slice(-15).map((t) => (
                  <div key={t.year} className="flex items-center gap-2 text-xs">
                    <span className="w-9 shrink-0 text-nn-muted">{t.year}</span>
                    <div className="flex-1 h-2 rounded-full bg-nn-panel2 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-nn-blue to-nn-cyan"
                        style={{ width: `${(100 * t.count) / maxTrend}%` }}
                      />
                    </div>
                    <span className="w-10 shrink-0 text-right text-nn-muted">
                      {t.count.toLocaleString('ru-RU')}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <div className="text-[10px] text-nn-muted mt-3">
              Источник: OpenAlex — открытый каталог мировой научной литературы
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
