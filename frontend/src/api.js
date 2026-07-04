import { getToken } from './auth.jsx'

const authHeaders = () => {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

const apiFetch = (url, opts = {}) =>
  fetch(url, {
    ...opts,
    headers: { ...(opts.headers || {}), ...authHeaders() },
  }).then((r) => {
    if (r.status === 401) window.dispatchEvent(new Event('hydrax-unauthorized'))
    return r
  })

const json = (r) => {
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

// Corpus-wide payloads change rarely; cache them client-side so navigating
// back to a page reuses the already-fetched data instead of refetching.
const CACHE_TTL = 5 * 60 * 1000
const _cache = new Map()
const cached = (key, fn) => {
  const hit = _cache.get(key)
  if (hit && Date.now() - hit.t < CACHE_TTL) return hit.p
  const p = fn().catch((e) => {
    _cache.delete(key)
    throw e
  })
  _cache.set(key, { t: Date.now(), p })
  return p
}

export const getStats = () =>
  cached('stats', () => apiFetch('/api/stats').then(json))
export const getGaps = () =>
  cached('gaps', () => apiFetch('/api/gaps').then(json))
export const getSessions = () => apiFetch('/api/sessions').then(json)
export const getSession = (id) => apiFetch(`/api/sessions/${id}`).then(json)
export const deleteSession = (id) =>
  apiFetch(`/api/sessions/${id}`, { method: 'DELETE' }).then(json)
export const getAnalytics = () =>
  cached('analytics', () => apiFetch('/api/analytics').then(json))
export const getContradictions = () =>
  cached('contradictions', () => apiFetch('/api/contradictions').then(json))
export const getRecentQueries = (limit = 12) =>
  apiFetch(`/api/queries/recent?limit=${limit}`).then(json)
export const getWorld = (q, limit = 10) =>
  apiFetch(`/api/world?q=${encodeURIComponent(q)}&limit=${limit}`).then(json)
export const getEntity = (name) =>
  apiFetch(`/api/entity?name=${encodeURIComponent(name)}`).then(json)
export const getDocuments = (limit = 2000) =>
  cached(`documents:${limit}`, () =>
    apiFetch(`/api/documents?limit=${limit}`).then(json))
export const getFullGraph = (limit = 200) =>
  cached(`graph:${limit}`, () =>
    apiFetch(`/api/graph/full?limit=${limit}`).then(json))
export const getMatrix = () =>
  cached('matrix', () => apiFetch('/api/matrix').then(json))
export const getParameters = () =>
  cached('parameters', () => apiFetch('/api/parameters').then(json))
export const getPath = (source, target) =>
  apiFetch(
    `/api/path?source=${encodeURIComponent(source)}&target=${encodeURIComponent(target)}`,
  ).then(json)
export const getEntities = () => apiFetch('/api/entities').then(json)
export const getVideos = (q, limit = 3) =>
  apiFetch(`/api/videos?q=${encodeURIComponent(q)}&limit=${limit}`).then(json)
export const postGraph = (query) =>
  apiFetch('/api/graph', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  }).then(json)

export const logExport = (kind, detail = '') =>
  apiFetch('/api/audit/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, detail }),
  }).then(json)

export const getAdminSummary = () => apiFetch('/api/admin/summary').then(json)
export const getAdminAudit = (params = '') =>
  apiFetch(`/api/admin/audit?${params}`).then(json)
export const getAdminLogins = (suspicious = false) =>
  apiFetch(`/api/admin/logins?suspicious=${suspicious}`).then(json)
export const getAdminUsers = () => apiFetch('/api/admin/users').then(json)
export const getMyOverview = () => apiFetch('/api/me/overview').then(json)

/**
 * Stream an answer over SSE.
 * onSession({session_id}); onSources({entities, chunks, facts});
 * onDelta(textChunk); onDone().
 */
export async function streamAnswer(
  query,
  { sessionId, mode, geo, style, signal, onSession, onSources, onDelta, onDone, onError, onAbort },
) {
  try {
    const resp = await apiFetch('/api/answer/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal,
      body: JSON.stringify({
        query,
        session_id: sessionId || null,
        mode: mode || 'answer',
        geo: geo || '',
        style: style || '',
      }),
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const raw = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        let event = 'message'
        let data = ''
        for (const line of raw.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          else if (line.startsWith('data:')) data += line.slice(5).trim()
        }
        if (!data) continue
        const parsed = JSON.parse(data)
        if (event === 'session') onSession?.(parsed)
        else if (event === 'sources') onSources?.(parsed)
        else if (event === 'delta') onDelta?.(parsed.text)
        else if (event === 'done') onDone?.()
      }
    }
    onDone?.()
  } catch (e) {
    if (e?.name === 'AbortError') onAbort?.()
    else onError?.(e)
  }
}
