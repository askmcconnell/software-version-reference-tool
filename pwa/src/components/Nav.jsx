import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

export default function Nav() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  return (
    <nav className="nav">
      <Link to="/" className="nav-brand">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <ellipse cx="12" cy="5" rx="9" ry="3"/>
          <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
          <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
        </svg>
        <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
          <span style={{ fontSize: '0.65rem', fontWeight: 400, color: 'var(--text-muted)', letterSpacing: '0.03em' }}>Ask McConnell's</span>
          <span style={{ fontWeight: 700, letterSpacing: '0.02em' }}>S3C-Tool</span>
        </span>
        <span className="badge">BETA</span>
      </Link>

      <div className="nav-links">
        {user ? (
          <>
            <Link to="/" style={pathname === '/' ? { color: 'var(--text)' } : {}}>
              Upload
            </Link>
            <Link to="/scans" style={pathname === '/scans' ? { color: 'var(--text)' } : {}}>
              My Scans
            </Link>
            <Link to="/reference" style={pathname === '/reference' ? { color: 'var(--text)' } : {}}>
              Reference DB
            </Link>
            <Link to="/dashboard" style={pathname === '/dashboard' ? { color: 'var(--text)' } : {}}>
              Dashboard
            </Link>
            <Link to="/docs" style={pathname === '/docs' ? { color: 'var(--text)' } : {}}>
              Docs
            </Link>
            <Link to="/privacy" style={{ fontSize: '0.85rem' }}>Privacy</Link>
            <Link to="/support" style={{ color: 'var(--accent)', fontSize: '0.85rem' }}>
              Support ♥
            </Link>
            <span className="text-muted hide-mobile" style={{ fontSize: '0.8rem' }}>
              {user.name}
            </span>
            <button className="nav-btn" onClick={handleLogout}>Sign out</button>
          </>
        ) : (
          <>
            <Link to="/dashboard" style={pathname === '/dashboard' ? { color: 'var(--text)' } : {}}>
              Dashboard
            </Link>
            <Link to="/docs">Docs</Link>
            <Link to="/privacy" style={{ fontSize: '0.85rem' }}>Privacy</Link>
            <Link to="/support" style={{ color: 'var(--accent)', fontSize: '0.85rem' }}>
              Support ♥
            </Link>
            <Link to="/login">Sign in</Link>
            <Link to="/register" className="btn btn-primary btn-sm">Get started</Link>
          </>
        )}
      </div>
    </nav>
  )
}
