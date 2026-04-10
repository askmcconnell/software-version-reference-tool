import { useState, useEffect, useRef, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { getAdminQueue } from '../api/wordpress'
import StatusBadge from '../components/StatusBadge'

const SECRET_KEY = 'svrt_queue_secret'
const POLL_MS    = 4000

function formatElapsed(secs) {
  if (!secs) return '—'
  if (secs < 60)   return `${secs}s`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`
}

function formatTime(iso) {
  if (!iso) return '—'
  return new Date(iso + 'Z').toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function MiniProgress({ pct, status }) {
  const color = status === 'pending'
    ? 'var(--text-muted)'
    : pct === 100 ? 'var(--supported)' : 'var(--accent)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 120 }}>
      <div style={{ flex: 1, background: 'var(--bg-input)', borderRadius: 4, height: 6, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, transition: 'width 0.4s ease', borderRadius: 4 }} />
      </div>
      <span style={{ fontSize: '0.75rem', fontWeight: 700, color, width: 30, textAlign: 'right' }}>{pct}%</span>
    </div>
  )
}

export default function QueuePage() {
  const [secret,     setSecret]     = useState(() => localStorage.getItem(SECRET_KEY) || '')
  const [input,      setInput]      = useState('')
  const [data,       setData]       = useState(null)
  const [error,      setError]      = useState('')
  const [loading,    setLoading]    = useState(false)
  const [lastPoll,   setLastPoll]   = useState(null)
  const [showRecent, setShowRecent] = useState(true)
  const intervalRef  = useRef()
  const tickRef      = useRef()
  const [tick,       setTick]       = useState(0)   // forces re-render each second for elapsed

  const poll = useCallback(async (s) => {
    if (!s) return
    try {
      const res = await getAdminQueue(s)
      setData(res)
      setLastPoll(new Date())
      setError('')
    } catch (err) {
      if (err.status === 403) {
        setError('Invalid secret — check the queue secret in WP Admin → SVRT.')
      } else {
        setError(err.message || 'Fetch failed')
      }
    }
  }, [])

  // Start polling once we have a secret
  useEffect(() => {
    if (!secret) return
    setLoading(true)
    poll(secret).finally(() => setLoading(false))
    intervalRef.current = setInterval(() => poll(secret), POLL_MS)
    tickRef.current     = setInterval(() => setTick(t => t + 1), 1000)
    return () => {
      clearInterval(intervalRef.current)
      clearInterval(tickRef.current)
    }
  }, [secret, poll])

  function handleSecretSubmit(e) {
    e.preventDefault()
    const s = input.trim()
    if (!s) return
    localStorage.setItem(SECRET_KEY, s)
    setSecret(s)
    setInput('')
  }

  function clearSecret() {
    localStorage.removeItem(SECRET_KEY)
    setSecret('')
    setData(null)
    setError('')
    clearInterval(intervalRef.current)
    clearInterval(tickRef.current)
  }

  // ── Secret prompt ─────────────────────────────────────────────────────────
  if (!secret) {
    return (
      <div style={{ maxWidth: 440, margin: '80px auto', textAlign: 'center' }}>
        <div style={{ fontSize: '2rem', marginBottom: 16 }}>🔐</div>
        <h1 style={{ fontSize: '1.4rem', marginBottom: 8 }}>Queue Dashboard</h1>
        <p className="text-muted mb-24" style={{ fontSize: '0.9rem' }}>
          Enter the SVRT queue secret (WP Admin → SVRT → Settings).
        </p>
        <form onSubmit={handleSecretSubmit} style={{ display: 'flex', gap: 8 }}>
          <input
            className="form-input"
            type="password"
            placeholder="Queue secret…"
            value={input}
            onChange={e => setInput(e.target.value)}
            autoFocus
            style={{ flex: 1 }}
          />
          <button className="btn btn-primary" type="submit">Enter</button>
        </form>
        <p className="text-muted mt-16" style={{ fontSize: '0.8rem' }}>
          Secret is saved in this browser only. <Link to="/">← Back to upload</Link>
        </p>
      </div>
    )
  }

  // ── Loading first paint ───────────────────────────────────────────────────
  if (loading && !data) {
    return <div className="loading-center"><div className="spinner" /><span className="text-muted">Connecting…</span></div>
  }

  const summary  = data?.summary  ?? {}
  const active   = data?.active   ?? []
  const recent   = data?.recent   ?? []
  const pi       = data?.pi_stats ?? {}

  const pendingCount    = summary.pending    ?? 0
  const processingCount = summary.processing ?? 0
  const totalActive     = pendingCount + processingCount

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>

      {/* Header */}
      <div className="flex-between mb-24" style={{ flexWrap: 'wrap', gap: 12 }}>
        <div>
          <Link to="/" style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>← Upload</Link>
          <h1 style={{ fontSize: '1.5rem', marginTop: 6 }}>Queue Dashboard</h1>
          <p className="text-muted" style={{ fontSize: '0.8rem' }}>
            Auto-refreshes every {POLL_MS / 1000}s
            {lastPoll && ` · last poll ${new Date(lastPoll).toLocaleTimeString()}`}
          </p>
        </div>
        <button className="btn btn-ghost" style={{ fontSize: '0.8rem' }} onClick={clearSecret}>
          🔒 Change secret
        </button>
      </div>

      {error && <div className="alert alert-error mb-16">{error}</div>}

      {/* Summary strip */}
      <div className="stats-grid mb-24">
        {[
          { num: pendingCount,              label: 'Waiting',        color: 'var(--text-muted)'  },
          { num: processingCount,           label: 'Processing now', color: 'var(--accent)'      },
          { num: summary.complete_total,    label: 'All-time complete', color: 'var(--supported)' },
          { num: summary.failed_total ?? 0, label: 'All-time failed',   color: 'var(--eol)'       },
        ].map(({ num, label, color }) => (
          <div className="stat-card" key={label}>
            <div className="stat-num" style={{ color }}>{num ?? '—'}</div>
            <div className="stat-label">{label}</div>
          </div>
        ))}
      </div>

      {/* Active jobs table */}
      <div className="card mb-24">
        <div className="flex-between mb-16">
          <div className="card-title" style={{ marginBottom: 0 }}>
            Active jobs
            {totalActive > 0 && (
              <span style={{
                marginLeft: 10, fontSize: '0.75rem', fontWeight: 700,
                background: 'var(--accent)', color: '#fff',
                padding: '2px 8px', borderRadius: 10,
              }}>
                {totalActive}
              </span>
            )}
          </div>
          {totalActive === 0 && (
            <span className="text-muted" style={{ fontSize: '0.8rem' }}>Queue is clear ✅</span>
          )}
        </div>

        {active.length > 0 ? (
          <div className="table-wrap" style={{ margin: 0 }}>
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th>User</th>
                  <th>Status</th>
                  <th>Progress</th>
                  <th style={{ textAlign: 'right' }}>Rows</th>
                  <th style={{ textAlign: 'right' }}>EOL hits</th>
                  <th>Elapsed</th>
                  <th>Queued at</th>
                </tr>
              </thead>
              <tbody>
                {active.map(job => {
                  // Compute elapsed client-side — server timestamp has no timezone suffix,
                  // treat as UTC (append 'Z') to avoid local-time offset inflation.
                  const createdMs = job.created_at ? new Date(job.created_at + 'Z').getTime() : null
                  const elapsed   = createdMs ? Math.max(0, Math.floor((Date.now() - createdMs) / 1000)) : 0
                  const isStale = elapsed > 360 && job.status === 'processing'
                  return (
                    <tr key={job.uuid}>
                      <td style={{ fontWeight: 500 }}>
                        <Link to={`/results/${job.uuid}`} target="_blank" rel="noreferrer"
                          style={{ color: 'var(--accent)' }}>
                          {job.filename || job.uuid.slice(0, 8)}
                        </Link>
                      </td>
                      <td className="muted" style={{ fontSize: '0.8rem' }}>{job.user_email || '—'}</td>
                      <td><StatusBadge status={job.status} /></td>
                      <td style={{ minWidth: 160 }}>
                        <MiniProgress pct={job.progress_pct} status={job.status} />
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 2 }}>
                          {job.matched_count.toLocaleString()} / {job.row_count.toLocaleString()}
                        </div>
                      </td>
                      <td className="mono" style={{ textAlign: 'right' }}>{job.row_count.toLocaleString()}</td>
                      <td className="mono" style={{ textAlign: 'right', color: job.eol_count > 0 ? 'var(--eol)' : undefined }}>
                        {job.eol_count > 0 ? job.eol_count.toLocaleString() : '—'}
                      </td>
                      <td className="mono" style={{ color: isStale ? 'var(--warning)' : undefined }}>
                        {isStale ? '⚠ ' : ''}{formatElapsed(elapsed)}
                      </td>
                      <td className="mono muted" style={{ fontSize: '0.75rem' }}>{formatTime(job.created_at)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div style={{ textAlign: 'center', padding: '32px 0', color: 'var(--text-muted)', fontSize: '0.9rem' }}>
            No jobs in queue right now.
          </div>
        )}
      </div>

      {/* Recently completed */}
      <div className="card">
        <div
          className="flex-between"
          style={{ cursor: 'pointer', userSelect: 'none', marginBottom: showRecent ? 16 : 0 }}
          onClick={() => setShowRecent(v => !v)}
        >
          <div className="card-title" style={{ marginBottom: 0 }}>
            Recently completed
            <span className="text-muted" style={{ fontWeight: 400, marginLeft: 8, fontSize: '0.8rem' }}>
              (last 4 hours)
            </span>
          </div>
          <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>{showRecent ? '▲' : '▼'}</span>
        </div>

        {showRecent && (
          recent.length > 0 ? (
            <div className="table-wrap" style={{ margin: 0 }}>
              <table>
                <thead>
                  <tr>
                    <th>File</th>
                    <th>User</th>
                    <th>Status</th>
                    <th style={{ textAlign: 'right' }}>Rows</th>
                    <th style={{ textAlign: 'right' }}>EOL hits</th>
                    <th>Completed</th>
                  </tr>
                </thead>
                <tbody>
                  {recent.map(job => (
                    <tr key={job.uuid} style={{ opacity: 0.75 }}>
                      <td style={{ fontWeight: 500 }}>
                        <Link to={`/results/${job.uuid}`} target="_blank" rel="noreferrer"
                          style={{ color: 'var(--text-muted)' }}>
                          {job.filename || job.uuid.slice(0, 8)}
                        </Link>
                      </td>
                      <td className="muted" style={{ fontSize: '0.8rem' }}>{job.user_email || '—'}</td>
                      <td><StatusBadge status={job.status} /></td>
                      <td className="mono" style={{ textAlign: 'right' }}>{job.row_count.toLocaleString()}</td>
                      <td className="mono" style={{ textAlign: 'right', color: job.eol_count > 0 ? 'var(--eol)' : undefined }}>
                        {job.eol_count > 0 ? job.eol_count.toLocaleString() : '—'}
                      </td>
                      <td className="mono muted" style={{ fontSize: '0.75rem' }}>
                        {job.completed_at ? formatTime(job.completed_at) : '—'}
                        {job.status === 'failed' && job.error_msg && (
                          <span style={{ color: 'var(--eol)', marginLeft: 6 }} title={job.error_msg}>⚠</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--text-muted)', fontSize: '0.9rem' }}>
              No completed jobs in the last 4 hours.
            </div>
          )
        )}
      </div>

      {/* Raspberry Pi research agent status */}
      <div className="card mt-24">
        <div className="flex-between mb-16">
          <div className="card-title" style={{ marginBottom: 0 }}>
            🍓 Raspberry Pi — Nightly Research Agent
          </div>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Runs 2 am nightly · 500 items/run
          </span>
        </div>

        {/* Coverage bar */}
        <div className="mb-16">
          <div className="flex-between mb-8" style={{ fontSize: '0.8rem' }}>
            <span className="text-muted">Reference coverage of scanned products</span>
            <span style={{ fontWeight: 700, color: (pi.coverage_pct ?? 0) >= 80 ? 'var(--supported)' : 'var(--accent)' }}>
              {pi.coverage_pct ?? 0}%
            </span>
          </div>
          <div className="progress-bar">
            <div className="progress-fill" style={{
              width: `${pi.coverage_pct ?? 0}%`,
              background: (pi.coverage_pct ?? 0) >= 80 ? 'var(--supported)' : undefined,
            }} />
          </div>
          <div className="flex-between mt-8" style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            <span>{(pi.ref_total ?? 0).toLocaleString()} products researched</span>
            <span>{(pi.unique_in_scans ?? 0).toLocaleString()} unique products in scans</span>
          </div>
          {(pi.backlog ?? 0) > 0 && (
            <div style={{ marginTop: 6, fontSize: '0.75rem', color: 'var(--accent)' }}>
              ⏳ {pi.backlog.toLocaleString()} products not yet in reference DB — Pi will research over coming nights
            </div>
          )}
        </div>

        {/* Stats grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12 }}>
          {[
            { label: 'Last sync from Pi',  value: pi.last_sync       ? formatTime(pi.last_sync)       : 'Never', muted: !pi.last_sync },
            { label: 'Last entry checked', value: pi.last_checked_at ? formatTime(pi.last_checked_at) : '—',     muted: !pi.last_checked_at },
            { label: 'Updated (24 h)',     value: (pi.updated_24h  ?? 0).toLocaleString(), color: (pi.updated_24h  ?? 0) > 0 ? 'var(--supported)' : undefined },
            { label: 'Updated (7 days)',   value: (pi.updated_7d   ?? 0).toLocaleString(), color: 'var(--supported)' },
            { label: 'Expiring soon',      value: (pi.expiring_soon ?? 0).toLocaleString(), color: (pi.expiring_soon ?? 0) > 0 ? 'var(--warning)' : undefined },
            { label: 'Overdue refresh',    value: (pi.expired      ?? 0).toLocaleString(), color: (pi.expired      ?? 0) > 0 ? 'var(--eol)'     : undefined },
            { label: 'EOL in reference',   value: (pi.eol_count    ?? 0).toLocaleString(), color: 'var(--eol)' },
            { label: 'Unknown in reference', value: (pi.unknown_count ?? 0).toLocaleString(), color: 'var(--unknown)' },
          ].map(({ label, value, color, muted }) => (
            <div key={label} style={{
              background: 'var(--bg-input)', borderRadius: 'var(--radius)',
              padding: '10px 12px',
            }}>
              <div style={{ fontSize: '1rem', fontWeight: 700, color: color ?? (muted ? 'var(--text-muted)' : 'var(--text)') }}>
                {value}
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 2 }}>{label}</div>
            </div>
          ))}
        </div>
      </div>

    </div>
  )
}
