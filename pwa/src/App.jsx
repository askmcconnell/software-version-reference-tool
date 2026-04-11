import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './contexts/AuthContext'
import Nav from './components/Nav'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import UploadPage from './pages/UploadPage'
import ResultsPage from './pages/ResultsPage'
import ReferencePage from './pages/ReferencePage'
import DocsPage from './pages/DocsPage'
import QueuePage from './pages/QueuePage'
import DashboardPage from './pages/DashboardPage'
import SupportPage from './pages/SupportPage'
import PrivacyPage from './pages/PrivacyPage'

function RequireAuth({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="loading-center"><div className="spinner" /></div>
  return user ? children : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <div className="app-shell">
      <Nav />
      <main className="main">
        <Routes>
          <Route path="/login"    element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/" element={
            <RequireAuth><UploadPage /></RequireAuth>
          } />
          <Route path="/results/:uuid" element={
            <RequireAuth><ResultsPage /></RequireAuth>
          } />
          <Route path="/reference" element={
            <RequireAuth><ReferencePage /></RequireAuth>
          } />
          <Route path="/docs"      element={<DocsPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/queue"     element={<QueuePage />} />
          <Route path="/support"   element={<SupportPage />} />
          <Route path="/privacy"   element={<PrivacyPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
