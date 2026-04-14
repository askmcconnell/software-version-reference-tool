import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

export default function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [fields,  setFields]  = useState({ firstName: '', lastName: '', email: '', password: '', company: '' })
  const [error,   setError]   = useState('')
  const [loading, setLoading] = useState(false)

  function set(k) { return e => setFields(f => ({ ...f, [k]: e.target.value })) }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    if (fields.password.length < 8) { setError('Password must be at least 8 characters.'); return }
    setLoading(true)
    try {
      await register(fields)
      navigate('/')
    } catch (err) {
      setError(err.message || 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 480, margin: '48px auto' }}>
      <div style={{ textAlign: 'center', marginBottom: 32 }}>
        <h1 style={{ fontSize: '1.5rem', marginBottom: 8 }}>Create your account</h1>
        <p className="text-muted">Ask McConnell's Software Security Supply Chain Tool</p>
        <p className="text-muted" style={{ fontSize: '0.8rem' }}>Free and open-source — unlimited uploads</p>
      </div>

      <div className="card">
        {error && <div className="alert alert-error">{error}</div>}
        <form onSubmit={handleSubmit}>
          <div className="form-row">
            <div className="form-group">
              <label>First name</label>
              <input className="input" type="text" value={fields.firstName} onChange={set('firstName')} placeholder="Jane" required autoFocus />
            </div>
            <div className="form-group">
              <label>Last name</label>
              <input className="input" type="text" value={fields.lastName} onChange={set('lastName')} placeholder="Smith" required />
            </div>
          </div>
          <div className="form-group">
            <label>Company <span className="text-muted">(optional)</span></label>
            <input className="input" type="text" value={fields.company} onChange={set('company')} placeholder="Acme Corp" />
          </div>
          <div className="form-group">
            <label>Email</label>
            <input className="input" type="email" value={fields.email} onChange={set('email')} placeholder="jane@acme.com" required />
          </div>
          <div className="form-group">
            <label>Password</label>
            <input className="input" type="password" value={fields.password} onChange={set('password')} placeholder="8+ characters" required />
          </div>
          <button className="btn btn-primary btn-full btn-lg mt-8" disabled={loading}>
            {loading ? <><span className="spinner" style={{width:16,height:16}} /> Creating account…</> : 'Create account'}
          </button>
        </form>
      </div>

      <p className="text-center text-muted mt-16" style={{ fontSize: '0.875rem' }}>
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </div>
  )
}
