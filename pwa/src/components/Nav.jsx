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
        <svg width="32" height="32" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <linearGradient id="nsg" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%"   stopColor="#4a90d9" stopOpacity="0"/>
              <stop offset="50%"  stopColor="#7ec8f5" stopOpacity="1"/>
              <stop offset="100%" stopColor="#4a90d9" stopOpacity="0"/>
            </linearGradient>
            <linearGradient id="nsf" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"   stopColor="#1a2540"/>
              <stop offset="100%" stopColor="#0f1520"/>
            </linearGradient>
            <linearGradient id="ncm" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"   stopColor="#7ec8f5"/>
              <stop offset="40%"  stopColor="#4a90d9"/>
              <stop offset="100%" stopColor="#2a5a8a"/>
            </linearGradient>
            <filter id="ngl">
              <feGaussianBlur stdDeviation="2" result="b"/>
              <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
            <clipPath id="nsc">
              <path d="M100 18 L168 46 L168 102 C168 140 138 168 100 182 C62 168 32 140 32 102 L32 46 Z"/>
            </clipPath>
          </defs>
          <path d="M100 18 L168 46 L168 102 C168 140 138 168 100 182 C62 168 32 140 32 102 L32 46 Z"
                fill="url(#nsf)" stroke="#4a90d9" strokeWidth="2.5" strokeLinejoin="round"/>
          <path d="M100 30 L156 53 L156 102 C156 134 130 158 100 170 C70 158 44 134 44 102 L44 53 Z"
                fill="none" stroke="#2e4a6a" strokeWidth="1" strokeLinejoin="round"/>
          <g clipPath="url(#nsc)">
            <text x="100" y="108"
                  fontFamily="'SF Mono','Fira Code','Consolas',monospace"
                  fontSize="52" fontWeight="900" textAnchor="middle" letterSpacing="2"
                  fill="none" stroke="#0e1624" strokeWidth="10" strokeLinejoin="round">S3C</text>
            <text x="100" y="108"
                  fontFamily="'SF Mono','Fira Code','Consolas',monospace"
                  fontSize="52" fontWeight="900" textAnchor="middle" letterSpacing="2"
                  fill="none" stroke="url(#ncm)" strokeWidth="5" strokeLinejoin="round">S3C</text>
            <text x="100" y="108"
                  fontFamily="'SF Mono','Fira Code','Consolas',monospace"
                  fontSize="52" fontWeight="900" textAnchor="middle" letterSpacing="2"
                  fill="#0a1020">S3C</text>
          </g>
          <g clipPath="url(#nsc)" filter="url(#ngl)">
            <rect x="28" y="116" width="144" height="3"   fill="url(#nsg)" rx="1.5"/>
            <rect x="28" y="121" width="144" height="1.5" fill="url(#nsg)" opacity="0.3" rx="0.75"/>
          </g>
        </svg>
        <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.25 }}>
          <span style={{ fontWeight: 700, letterSpacing: '0.02em', fontSize: '1rem' }}>S3C-Tool</span>
          <span style={{ fontSize: '0.6rem', fontWeight: 400, color: 'var(--text-muted)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>Software Security Supply Chain</span>
        </span>
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
            <Link to="/about" style={pathname === '/about' ? { color: 'var(--text)' } : {}}>
              About
            </Link>
            <Link to="/privacy" style={{ fontSize: '0.85rem' }}>Privacy</Link>
            <Link to="/terms" style={{ fontSize: '0.85rem' }}>Terms</Link>
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
            <Link to="/about" style={pathname === '/about' ? { color: 'var(--text)' } : {}}>
              About
            </Link>
            <Link to="/dashboard" style={pathname === '/dashboard' ? { color: 'var(--text)' } : {}}>
              Dashboard
            </Link>
            <Link to="/docs">Docs</Link>
            <Link to="/privacy" style={{ fontSize: '0.85rem' }}>Privacy</Link>
            <Link to="/terms" style={{ fontSize: '0.85rem' }}>Terms</Link>
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
