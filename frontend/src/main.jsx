import React from 'react'
import ReactDOM from 'react-dom/client'
import { Navigate, createHashRouter, RouterProvider } from 'react-router-dom'
import './index.css'
import { AuthProvider, hasRole, useAuth } from './auth.jsx'
import Layout from './components/Layout.jsx'
import Login from './pages/Login.jsx'
import Admin from './pages/Admin.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Search from './pages/Search.jsx'
import GraphExplorer from './pages/GraphExplorer.jsx'
import Documents from './pages/Documents.jsx'
import Analytics from './pages/Analytics.jsx'
import WorldScience from './pages/WorldScience.jsx'
import Verification from './pages/Verification.jsx'
import CoverageMatrix from './pages/CoverageMatrix.jsx'
import Parameters from './pages/Parameters.jsx'
import Radar from './pages/Radar.jsx'
import Bridges from './pages/Bridges.jsx'

function RequireAuth({ children }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  return children
}

function RequireRole({ roles, children }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  if (!hasRole(user, ...roles)) return <Navigate to="/" replace />
  return children
}

const INTERNAL = ['researcher', 'analyst', 'project_manager', 'admin']

const router = createHashRouter([
  { path: '/login', element: <Login /> },
  {
    path: '/',
    element: (
      <RequireAuth>
        <Layout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'search', element: <Search /> },
      { path: 'world', element: <WorldScience /> },
      { path: 'documents', element: <Documents /> },
      {
        path: 'graph',
        element: <RequireRole roles={INTERNAL}><GraphExplorer /></RequireRole>,
      },
      {
        path: 'analytics',
        element: <RequireRole roles={INTERNAL}><Analytics /></RequireRole>,
      },
      {
        path: 'verify',
        element: <RequireRole roles={INTERNAL}><Verification /></RequireRole>,
      },
      {
        path: 'matrix',
        element: <RequireRole roles={INTERNAL}><CoverageMatrix /></RequireRole>,
      },
      {
        path: 'parameters',
        element: <RequireRole roles={INTERNAL}><Parameters /></RequireRole>,
      },
      {
        path: 'radar',
        element: (
          <RequireRole roles={['analyst', 'project_manager', 'admin']}>
            <Radar />
          </RequireRole>
        ),
      },
      {
        path: 'bridges',
        element: <RequireRole roles={INTERNAL}><Bridges /></RequireRole>,
      },
      {
        path: 'admin',
        element: <RequireRole roles={['admin']}><Admin /></RequireRole>,
      },
    ],
  },
])

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  </React.StrictMode>,
)
