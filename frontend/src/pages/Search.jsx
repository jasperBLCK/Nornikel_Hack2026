import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { marked } from 'marked'
import { deleteSession, getSession, getSessions, getVideos, logExport, postGraph, streamAnswer } from '../api.js'
import { useAuth } from '../auth.jsx'
import GraphView from '../components/GraphView.jsx'

const MODES = [
  { id: 'answer', label: 'Ответ', title: 'Обычный ответ с цитатами по корпусу' },
  { id: 'review', label: '📚 Обзор', title: 'Литературный обзор: группировка по источникам, противоречия, пробелы' },
  { id: 'compare', label: '⚖ Сравнение', title: 'Сравнительная таблица: отечественная vs мировая практика' },
]

const GEOS = [
  { id: '', label: 'Все источники', title: 'Без гео-фильтра (автоподсказка из текста запроса)' },
  { id: 'domestic', label: '🇷🇺 Отечественные', title: 'Только отечественная практика' },
  { id: 'foreign', label: '🌍 Зарубежные', title: 'Только зарубежная практика' },
]

const STYLES = [
  { id: '', label: 'Стандартный' },
  { id: 'concise', label: 'Кратко' },
  { id: 'academic', label: 'Академично' },
  { id: 'simple', label: 'Простым языком' },
]

const GEO_BADGE = { domestic: '🇷🇺', foreign: '🌍' }

function formatWhen(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return 'только что'
  if (diff < 3600) return `${Math.floor(diff / 60)} мин назад`
  if (diff < 86400) return `${Math.floor(diff / 3600)} ч назад`
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}

const EXAMPLES = [
  'циркуляция католита при электроэкстракции никеля',
  'распределение Au, Ag и МПГ между штейном и шлаком',
  'кучное выщелачивание в холодном климате',
  'способы удаления SO₂ из отходящих газов',
  'закачка шахтных вод в глубокие горизонты',
]

const KIND_RU = {
  materials: 'материал',
  processes: 'процесс',
  equipment: 'оборудование',
  conditions: 'условие',
}
const KIND_COLOR = {
  materials: 'text-nn-cyan',
  processes: 'text-nn-green',
  equipment: 'text-nn-amber',
  conditions: 'text-nn-purple',
}

export default function Search() {
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [messages, setMessages] = useState([]) // {role, content, sources?}
  const [sources, setSources] = useState(null)
  const [graph, setGraph] = useState(null)
  const [error, setError] = useState('')
  const [openSource, setOpenSource] = useState(null)
  const [flashSource, setFlashSource] = useState(null)
  const [sessions, setSessions] = useState([])
  const [activeSession, setActiveSession] = useState(null)
  const [mode, setMode] = useState('answer')
  const [geo, setGeo] = useState('')
  const [style, setStyle] = useState(() => localStorage.getItem('hydrax_style') || '')
  const [listening, setListening] = useState(false)
  const recRef = useRef(null)
  const [video, setVideo] = useState(null) // null | {loading} | {videos, fallback_url}
  const [videoOpen, setVideoOpen] = useState(null)
  const sourceRefs = useRef({})
  const bottomRef = useRef(null)
  const streamRef = useRef(null)
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const { user } = useAuth()
  const canExport = !!user?.can_export

  const refreshSessions = useCallback(() => {
    getSessions()
      .then((d) => setSessions(d.sessions || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    refreshSessions()
  }, [refreshSessions])

  const stopStream = useCallback(() => {
    streamRef.current?.abort()
    streamRef.current = null
  }, [])

  const newChat = useCallback(() => {
    stopStream()
    setBusy(false)
    setStreaming(false)
    setActiveSession(null)
    setMessages([])
    setSources(null)
    setGraph(null)
    setError('')
    setOpenSource(null)
    setQuery('')
    setVideo(null)
    setVideoOpen(null)
  }, [stopStream])

  const openSession = useCallback((id) => {
    getSession(id)
      .then((s) => {
        stopStream()
        setBusy(false)
        setStreaming(false)
        setActiveSession(id)
        setMessages(s.messages || [])
        const lastAssistant = [...(s.messages || [])]
          .reverse()
          .find((m) => m.role === 'assistant' && m.sources)
        setSources(lastAssistant?.sources || null)
        setGraph(null)
        setError('')
        setOpenSource(null)
        setVideo(null)
        setVideoOpen(null)
        const lastUser = [...(s.messages || [])].reverse().find((m) => m.role === 'user')
        if (lastUser) {
          postGraph(lastUser.content)
            .then(setGraph)
            .catch(() => setGraph({ nodes: [], edges: [] }))
        }
      })
      .catch(() => {})
  }, [stopStream])

  useEffect(() => {
    const sid = params.get('session')
    const q = params.get('q')
    if (sid) {
      openSession(sid)
      setParams({}, { replace: true })
    } else if (q) {
      setParams({}, { replace: true })
      run(q)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const removeSession = useCallback(
    (id, e) => {
      e.stopPropagation()
      if (!window.confirm('Удалить этот диалог?')) return
      deleteSession(id)
        .then(() => {
          refreshSessions()
          if (id === activeSession) newChat()
        })
        .catch(() => {})
    },
    [activeSession, newChat, refreshSessions],
  )

  const run = useCallback(
    (q, runMode = mode) => {
      const text = (q || '').trim()
      if (!text || busy) return
      setQuery('')
      setBusy(true)
      setStreaming(true)
      setError('')
      setSources(null)
      setOpenSource(null)
      setVideo(null)
      setVideoOpen(null)
      const prefixes = {
        review: '\u{1F4DA} Обзор литературы: ',
        compare: '\u2696 Сравнение практик: ',
      }
      const shown = (prefixes[runMode] || '') + text
      setMessages((m) => [...m, { role: 'user', content: shown }, { role: 'assistant', content: '' }])

      postGraph(text)
        .then((g) => setGraph((prev) => (g?.nodes?.length || !prev?.nodes?.length ? g : prev)))
        .catch(() => setGraph((prev) => prev || { nodes: [], edges: [] }))

      const controller = new AbortController()
      streamRef.current = controller
      const isCurrent = () => streamRef.current === controller
      streamAnswer(text, {
        sessionId: activeSession,
        mode: runMode,
        geo,
        style,
        signal: controller.signal,
        onSession: ({ session_id }) => {
          if (isCurrent()) setActiveSession(session_id)
        },
        onSources: (s) => {
          if (isCurrent()) setSources(s)
        },
        onDelta: (t) => {
          if (!isCurrent()) return
          setMessages((m) => {
            const last = m[m.length - 1]
            if (!last || last.role !== 'assistant') return m
            return [...m.slice(0, -1), { ...last, content: (last.content || '') + t }]
          })
        },
        onDone: () => {
          if (!isCurrent()) return
          streamRef.current = null
          setBusy(false)
          setStreaming(false)
          refreshSessions()
        },
        onAbort: () => {
          refreshSessions()
        },
        onError: (e) => {
          if (!isCurrent()) return
          streamRef.current = null
          setError(String(e))
          setBusy(false)
          setStreaming(false)
        },
      })
    },
    [activeSession, busy, mode, geo, style, refreshSessions],
  )

  useEffect(() => () => streamRef.current?.abort(), [])

  useEffect(() => {
    localStorage.setItem('hydrax_style', style)
  }, [style])

  const SpeechRec =
    typeof window !== 'undefined' &&
    (window.SpeechRecognition || window.webkitSpeechRecognition)

  const toggleMic = () => {
    if (listening) {
      recRef.current?.stop()
      return
    }
    const rec = new SpeechRec()
    rec.lang = 'ru-RU'
    rec.interimResults = true
    rec.onresult = (e) => {
      const text = Array.from(e.results).map((r) => r[0].transcript).join(' ')
      setQuery(text)
    }
    rec.onend = () => setListening(false)
    rec.onerror = () => setListening(false)
    recRef.current = rec
    setListening(true)
    rec.start()
  }

  const jump = useCallback((n) => {
    setOpenSource(n)
    setFlashSource(n)
    setTimeout(() => setFlashSource(null), 2000)
    sourceRefs.current[n]?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [])

  useEffect(() => {
    window.__hydraxJump = jump
    return () => delete window.__hydraxJump
  }, [jump])

  useEffect(() => {
    if (streaming) bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, streaming])

  const exportMd = () => {
    logExport('md', lastUserQuery()).catch(() => {})
    const lastQ = [...messages].reverse().find((m) => m.role === 'user')?.content || ''
    const lastA = [...messages].reverse().find((m) => m.role === 'assistant')?.content || ''
    let md = `# HydraX — ответ\n\n**Запрос:** ${lastQ}\n\n${lastA}\n\n## Источники\n\n`
    for (const [i, c] of (sources?.chunks || []).entries()) {
      md += `${i + 1}. **${c.filename}** (релевантность ${c.score})\n\n   > ${c.text.slice(0, 400)}\n\n`
    }
    const blob = new Blob([md], { type: 'text/markdown' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'hydrax-answer.md'
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const exportJsonLd = () => {
    logExport('jsonld', lastUserQuery()).catch(() => {})
    const lastQ = [...messages].reverse().find((m) => m.role === 'user')?.content || ''
    const lastA = [...messages].reverse().find((m) => m.role === 'assistant')?.content || ''
    const doc = {
      '@context': 'https://schema.org',
      '@type': 'Answer',
      name: lastQ,
      text: lastA,
      dateCreated: new Date().toISOString(),
      isBasedOn: (sources?.chunks || []).map((c) => ({
        '@type': 'CreativeWork',
        name: c.filename,
        identifier: c.document_id,
        description: c.text.slice(0, 300),
      })),
      about: Object.values(sources?.entities || {})
        .flat()
        .map((e) => ({ '@type': 'Thing', name: e })),
    }
    const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/ld+json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'hydrax-answer.jsonld'
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const renderAnswer = (content) =>
    marked
      .parse(content || '')
      .replace(
        /\[(\d+)\]/g,
        (_, n) => `<span class="cite" onclick="window.__hydraxJump(${n})">[${n}]</span>`,
      )

  const lastUserQuery = () => {
    const raw = [...messages].reverse().find((m) => m.role === 'user')?.content || ''
    return raw.replace(/^(\u{1F4DA} Обзор литературы: |\u2696 Сравнение практик: )/u, '')
  }

  const loadVideos = () => {
    const q = lastUserQuery()
    if (!q) return
    setVideo({ loading: true })
    getVideos(q)
      .then((v) => setVideo({ ...v, loading: false, query: q }))
      .catch(() => setVideo(null))
  }

  const videoRelevant =
    mode === 'answer' &&
    ((sources?.entities?.processes?.length || 0) + (sources?.entities?.equipment?.length || 0) > 0)

  const empty = messages.length === 0

  const inputBar = (
    <div className="sticky bottom-4 bg-nn-panel border border-nn-border rounded-2xl p-2 focus-within:border-nn-blue/60 transition-colors shadow-lg">
      <div className="flex items-center gap-1.5 px-1 pb-1.5 flex-wrap">
        <span className="text-[10px] uppercase tracking-wider text-nn-muted/70 mr-1">Режим</span>
        {MODES.map((m) => (
          <button
            key={m.id}
            onClick={() => setMode(m.id)}
            title={m.title}
            className={`text-[11px] px-2.5 py-1 rounded-md border transition-colors ${
              mode === m.id
                ? 'border-nn-blue/60 bg-nn-blue/15 text-nn-accent font-semibold'
                : 'border-transparent text-nn-muted hover:text-nn-text hover:bg-nn-panel2'
            }`}
          >
            {m.label}
          </button>
        ))}
        <span className="text-[10px] uppercase tracking-wider text-nn-muted/70 ml-2 mr-1">Гео</span>
        {GEOS.map((g) => (
          <button
            key={g.id}
            onClick={() => setGeo(g.id)}
            title={g.title}
            className={`text-[11px] px-2.5 py-1 rounded-md border transition-colors ${
              geo === g.id
                ? 'border-nn-blue/60 bg-nn-blue/15 text-nn-accent font-semibold'
                : 'border-transparent text-nn-muted hover:text-nn-text hover:bg-nn-panel2'
            }`}
          >
            {g.label}
          </button>
        ))}
        <span className="text-[10px] uppercase tracking-wider text-nn-muted/70 ml-2 mr-1">Стиль</span>
        <select
          value={style}
          onChange={(e) => setStyle(e.target.value)}
          title="Стиль изложения ответа"
          className="text-[11px] px-1.5 py-1 rounded-md border border-nn-border bg-nn-panel text-nn-muted hover:text-nn-text outline-none"
        >
          {STYLES.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>
      </div>
      <div className="flex gap-2">
        <input
          className="flex-1 bg-transparent outline-none px-3 text-nn-text placeholder:text-nn-muted/60"
          placeholder={
            empty
              ? 'Какие методы обессоливания воды подходят при сульфатах 200–300 мг/л?'
              : 'Уточняющий вопрос по этому диалогу…'
          }
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !busy && run(query)}
        />
        {SpeechRec && (
          <button
            onClick={toggleMic}
            title={listening ? 'Остановить запись' : 'Голосовой ввод (ru-RU)'}
            className={`px-3 py-2.5 rounded-xl border transition-colors ${
              listening
                ? 'border-nn-pink/60 bg-nn-pink/10 text-nn-pink animate-pulse'
                : 'border-nn-border text-nn-muted hover:text-nn-text hover:border-nn-blue/50'
            }`}
          >
            🎤
          </button>
        )}
        {busy ? (
          <button
            onClick={() => {
              stopStream()
              setBusy(false)
              setStreaming(false)
            }}
            title="Остановить генерацию"
            className="px-6 py-2.5 rounded-xl font-semibold text-nn-pink border border-nn-pink/40 bg-nn-pink/5 hover:bg-nn-pink/10 transition-colors"
          >
            ■ Стоп
          </button>
        ) : (
          <button
            onClick={() => run(query)}
            disabled={!query.trim()}
            className="px-6 py-2.5 rounded-xl font-semibold text-white bg-gradient-to-r from-nn-blue to-nn-cyan disabled:opacity-50 hover:brightness-110 transition-all"
          >
            {empty ? 'Найти' : 'Спросить'}
          </button>
        )}
      </div>
    </div>
  )

  return (
    <div className="grid lg:grid-cols-[240px_1fr] gap-5 items-start">
      {/* sessions sidebar */}
      <aside className="card p-3 lg:sticky lg:top-20 max-h-[calc(100vh-120px)] overflow-y-auto">
        <button
          onClick={newChat}
          className="w-full mb-3 px-3 py-2 rounded-xl text-sm font-semibold text-white bg-gradient-to-r from-nn-blue to-nn-cyan hover:brightness-110 transition-all"
        >
          + Новый диалог
        </button>
        {sessions.length === 0 ? (
          <div className="text-xs text-nn-muted text-center py-4">Диалогов пока нет</div>
        ) : (
          <div className="space-y-1">
            {sessions.map((s) => (
              <div
                key={s.id}
                role="button"
                tabIndex={0}
                onClick={() => openSession(s.id)}
                onKeyDown={(e) => e.key === 'Enter' && openSession(s.id)}
                className={`group flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs cursor-pointer border transition-colors ${
                  s.id === activeSession
                    ? 'bg-nn-blue/20 border-nn-blue/40 text-nn-text'
                    : 'border-transparent text-nn-muted hover:text-nn-text hover:bg-nn-panel2'
                }`}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{s.title || 'Без названия'}</span>
                  <span className="block text-[10px] text-nn-muted/80 mt-0.5">
                    {formatWhen(s.updated_at)}{s.messages ? ` · сообщений: ${s.messages}` : ''}
                  </span>
                </span>
                <button
                  onClick={(e) => removeSession(s.id, e)}
                  title="Удалить диалог"
                  className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 text-nn-muted hover:text-nn-pink shrink-0"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}
      </aside>

      <div className="min-w-0">
        {empty && (
          <section className="text-center pt-6 pb-8">
            <h2 className="text-4xl font-extrabold bg-gradient-to-r from-nn-text via-nn-accent to-nn-cyan bg-clip-text text-transparent">
              Спросите — корпус ответит
            </h2>
            <p className="text-nn-muted mt-2 text-sm">
              Семантический поиск по 30 000+ фрагментам отчётов и статей · граф знаний · ответы с
              цитатами · уточняющие вопросы в диалоге
            </p>
            <div className="flex flex-wrap justify-center gap-2 mt-5 max-w-4xl mx-auto">
              {EXAMPLES.map((e) => (
                <button
                  key={e}
                  onClick={() => run(e)}
                  className="px-3 py-1.5 rounded-full text-xs bg-nn-panel border border-nn-border text-nn-muted hover:text-nn-text hover:border-nn-blue/50 transition-colors"
                >
                  {e}
                </button>
              ))}
            </div>
          </section>
        )}

        {error && (
          <div className="card !border-nn-pink/40 !bg-nn-pink/5 text-nn-pink text-sm mb-5">
            ⚠ Ошибка запроса: {error}
          </div>
        )}

        {!empty && (
          <div className="grid lg:grid-cols-[1fr_340px] gap-5 items-start mb-5">
            <div className="space-y-4 min-w-0">
              {messages.map((m, i) =>
                m.role === 'user' ? (
                  <div key={i} className="flex justify-end">
                    <div className="max-w-[85%] px-4 py-2.5 rounded-2xl rounded-br-md bg-nn-blue/25 border border-nn-blue/40 text-sm">
                      {m.content}
                    </div>
                  </div>
                ) : (
                  <div key={i} className="card">
                    <div className="card-title">
                      Ответ ассистента
                      {i === messages.length - 1 && m.content && !streaming && (
                        <span className="ml-auto flex gap-2 normal-case tracking-normal font-medium">
                          {canExport && (<>
                          <button
                            onClick={exportMd}
                            className="text-[11px] px-2.5 py-1 rounded-md border border-nn-border text-nn-muted hover:text-nn-text hover:border-nn-blue/50"
                          >
                            ⬇ Экспорт .md
                          </button>
                          <button
                            onClick={exportJsonLd}
                            title="Экспорт в JSON-LD (schema.org) для интеграций"
                            className="text-[11px] px-2.5 py-1 rounded-md border border-nn-border text-nn-muted hover:text-nn-text hover:border-nn-blue/50"
                          >
                            ⬇ JSON-LD
                          </button>
                          <button
                            onClick={() => window.print()}
                            title="Сохранить как PDF через печать"
                            className="text-[11px] px-2.5 py-1 rounded-md border border-nn-border text-nn-muted hover:text-nn-text hover:border-nn-blue/50"
                          >
                            🖶 PDF
                          </button>
                          </>)}
                          <button
                            onClick={loadVideos}
                            title="Найти обучающее видео по теме вопроса"
                            className="text-[11px] px-2.5 py-1 rounded-md border border-nn-border text-nn-muted hover:text-nn-text hover:border-nn-blue/50"
                          >
                            🎬 Видео
                          </button>
                          <button
                            onClick={() => navigator.clipboard.writeText(m.content)}
                            className="text-[11px] px-2.5 py-1 rounded-md border border-nn-border text-nn-muted hover:text-nn-text hover:border-nn-blue/50"
                          >
                            ⧉ Копировать
                          </button>
                        </span>
                      )}
                    </div>
                    {!m.content && busy && i === messages.length - 1 ? (
                      <div className="space-y-2.5">
                        {[92, 78, 85, 60].map((w, j) => (
                          <div key={j} className="skeleton h-4" style={{ width: `${w}%` }} />
                        ))}
                      </div>
                    ) : (
                      <div className="md-answer text-[15px]">
                        <span dangerouslySetInnerHTML={{ __html: renderAnswer(m.content) }} />
                        {streaming && i === messages.length - 1 && (
                          <span className="cursor-blink text-nn-accent">▍</span>
                        )}
                      </div>
                    )}
                  </div>
                ),
              )}

              {!streaming && !busy && messages.some((m) => m.role === 'assistant' && m.content) && (
                video === null ? (
                  videoRelevant && (
                    <div className="flex">
                      <button
                        onClick={loadVideos}
                        className="text-[11px] px-3 py-1.5 rounded-full border border-nn-border bg-nn-panel text-nn-muted hover:text-nn-text hover:border-nn-blue/50 transition-colors"
                      >
                        🎬 Есть видео по этой теме — показать
                      </button>
                    </div>
                  )
                ) : video.loading ? (
                  <div className="skeleton h-24" />
                ) : (
                  <div className="card">
                    <div className="card-title">
                      Видео по теме
                      <button
                        onClick={() => { setVideo(null); setVideoOpen(null) }}
                        title="Скрыть"
                        className="ml-auto normal-case tracking-normal text-nn-muted hover:text-nn-text"
                      >
                        ✕
                      </button>
                    </div>
                    {video.videos?.length ? (
                      <>
                        <div className="grid sm:grid-cols-3 gap-3">
                          {video.videos.map((v) => (
                            <button
                              key={v.id}
                              onClick={() => setVideoOpen(videoOpen === v.id ? null : v.id)}
                              className={`text-left rounded-xl border overflow-hidden transition-colors ${
                                videoOpen === v.id
                                  ? 'border-nn-blue/60 bg-nn-blue/5'
                                  : 'border-nn-border hover:border-nn-blue/40'
                              }`}
                            >
                              {v.thumbnail && (
                                <img src={v.thumbnail} alt="" className="w-full aspect-video object-cover" />
                              )}
                              <div className="p-2.5">
                                <div className="text-xs font-semibold line-clamp-2">{v.title}</div>
                                <div className="text-[10px] text-nn-muted mt-1">{v.channel}</div>
                              </div>
                            </button>
                          ))}
                        </div>
                        {videoOpen && (
                          <div className="mt-3 rounded-xl overflow-hidden border border-nn-border">
                            <iframe
                              title="video"
                              src={`https://www.youtube.com/embed/${videoOpen}`}
                              className="w-full aspect-video"
                              allow="accelerometer; encrypted-media; picture-in-picture"
                              allowFullScreen
                            />
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="text-sm text-nn-muted">
                        Встроенный подбор недоступен (нет ключа YouTube API).{' '}
                        <a
                          href={video.fallback_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-nn-accent font-semibold hover:underline"
                        >
                          Найти видео на YouTube ↗
                        </a>
                      </div>
                    )}
                  </div>
                )
              )}
              <div ref={bottomRef} />

              {inputBar}

              <div className="card">
                <div className="card-title">
                  Источники {sources?.chunks?.length ? `· ${sources.chunks.length}` : ''}
                </div>
                {!sources ? (
                  <div className="space-y-3">
                    {[0, 1, 2].map((i) => (
                      <div key={i} className="skeleton h-14" />
                    ))}
                  </div>
                ) : (
                  <div className="space-y-3">
                    {sources.chunks.map((c, i) => {
                      const n = i + 1
                      const open = openSource === n
                      return (
                        <div
                          key={c.chunk_id || n}
                          ref={(el) => (sourceRefs.current[n] = el)}
                          onClick={() => setOpenSource(open ? null : n)}
                          className={`rounded-xl border bg-nn-panel2/50 p-3 cursor-pointer transition-colors border-nn-border hover:border-nn-blue/40 ${
                            flashSource === n ? 'flash' : ''
                          }`}
                        >
                          <div className="flex items-center gap-2.5">
                            <span className="w-6 h-6 grid place-items-center rounded-md bg-nn-blue/25 text-nn-accent text-xs font-bold shrink-0">
                              {n}
                            </span>
                            <span className="font-semibold text-sm truncate">{c.filename}</span>
                            {c.geo && (
                              <span
                                title={c.geo === 'domestic' ? 'Отечественная практика' : 'Зарубежная практика'}
                                className="text-[11px] shrink-0"
                              >
                                {GEO_BADGE[c.geo]}
                              </span>
                            )}
                            <span className="ml-auto text-[11px] text-nn-muted shrink-0">
                              релевантность {c.score}
                            </span>
                          </div>
                          <div className="h-1 mt-2 rounded-full bg-nn-border overflow-hidden">
                            <div
                              className="h-full rounded-full bg-gradient-to-r from-nn-blue to-nn-cyan"
                              style={{ width: `${Math.min(100, c.score * 200)}%` }}
                            />
                          </div>
                          <p
                            className={`text-[13px] text-nn-muted mt-2 leading-relaxed ${
                              open ? '' : 'line-clamp-2'
                            }`}
                          >
                            {c.text}
                          </p>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>

            <div className="space-y-5 min-w-0">
              {(sources?.constraints?.length > 0 || sources?.geo) && (
                <div className="card">
                  <div className="card-title">Фильтры запроса</div>
                  <div className="flex flex-wrap gap-2">
                    {sources.geo && (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-nn-blue/10 border border-nn-blue/40 text-xs">
                        <b className="text-nn-accent">гео</b>
                        {GEO_BADGE[sources.geo]}{' '}
                        {sources.geo === 'domestic' ? 'отечественная практика' : 'зарубежная практика'}
                      </span>
                    )}
                    {(sources.constraints || []).map((c, i) => (
                      <span
                        key={i}
                        title="Числовое ограничение, распознанное в запросе"
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-nn-panel2 border border-nn-border text-xs"
                      >
                        <b className="text-nn-amber">≤≥</b>
                        {c.text}
                      </span>
                    ))}
                  </div>
                  {sources.parameter_matches?.length > 0 && (
                    <ul className="mt-3 text-[12px] text-nn-muted space-y-1">
                      {sources.parameter_matches.slice(0, 6).map((m, i) => (
                        <li key={i}>
                          ✓ <b className="text-nn-text">{m.process}</b>: {m.parameter} ={' '}
                          {m.value} {m.unit} — удовлетворяет «{m.constraint}»
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {sources?.entities && Object.keys(sources.entities).length > 0 && (
                <div className="card">
                  <div className="card-title">Распознанные сущности</div>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(sources.entities).flatMap(([kind, names]) =>
                      names.map((name) => (
                        <span
                          key={kind + name}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-nn-panel2 border border-nn-border text-xs"
                        >
                          <b className={KIND_COLOR[kind] || 'text-nn-muted'}>
                            {KIND_RU[kind] || kind}
                          </b>
                          {name}
                        </span>
                      )),
                    )}
                  </div>
                </div>
              )}

              <div className="card">
                <div className="card-title">Граф знаний</div>
                {graph === null ? (
                  <div className="skeleton h-72" />
                ) : !graph.nodes?.length ? (
                  <div className="text-xs text-nn-muted text-center py-8">
                    Нет данных графа по этому запросу
                  </div>
                ) : (
                  <GraphView
                    graph={graph}
                    height={330}
                    onNodeClick={(name) => navigate(`/graph?entity=${encodeURIComponent(name)}`)}
                  />
                )}
              </div>

              {sources?.facts?.length > 0 && (
                <div className="card">
                  <div className="card-title">Факты графа</div>
                  <ul className="text-[13px] divide-y divide-nn-border/60">
                    {sources.facts.slice(0, 20).map((f, i) => (
                      <li key={i} className="py-1.5">
                        {f.source}{' '}
                        <span className="text-nn-accent font-semibold text-[11px]">
                          {f.relation}
                        </span>{' '}
                        {f.target}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}

        {/* input on the empty screen (in-conversation input lives in the chat column) */}
        {empty && <div className="max-w-3xl mx-auto">{inputBar}</div>}
      </div>
    </div>
  )
}
