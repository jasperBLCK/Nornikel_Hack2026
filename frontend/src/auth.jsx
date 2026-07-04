import { createContext, useCallback, useContext, useEffect, useState } from 'react'

const AuthContext = createContext(null)

export const getToken = () => localStorage.getItem('hydrax_token') || ''

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('hydrax_user') || 'null')
    } catch {
      return null
    }
  })
  const [notice, setNotice] = useState(null)

  const logout = useCallback(() => {
    localStorage.removeItem('hydrax_token')
    localStorage.removeItem('hydrax_refresh')
    localStorage.removeItem('hydrax_user')
    setUser(null)
  }, [])

  useEffect(() => {
    const onUnauthorized = () => logout()
    window.addEventListener('hydrax-unauthorized', onUnauthorized)
    return () => window.removeEventListener('hydrax-unauthorized', onUnauthorized)
  }, [logout])

  const login = useCallback(async (username, password) => {
    const resp = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    const data = await resp.json().catch(() => ({}))
    if (!resp.ok) throw new Error(data.detail || 'Ошибка входа')
    localStorage.setItem('hydrax_token', data.access_token)
    if (data.refresh_token) localStorage.setItem('hydrax_refresh', data.refresh_token)
    localStorage.setItem('hydrax_user', JSON.stringify(data.user))
    setUser(data.user)
    setNotice(data.security_notice || null)
    return data.user
  }, [])

  return (
    <AuthContext.Provider value={{ user, login, logout, notice, setNotice }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)

export const hasRole = (user, ...roles) =>
  !!user && roles.some((r) => (user.roles || []).includes(r))
