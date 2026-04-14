import { useState, useEffect, useRef } from 'react'
import { useParams, useSearchParams, Link, useNavigate } from 'react-router-dom'
import { getJobStatus, getJobReport, resendReport, deleteJob } from '../api/wordpress'
import StatusBadge from '../components/StatusBadge'

// ── CVE Badge ─────────────────────────────────────────────────────────────────

function CveBadge({ count, critical, high }) {
  if (count === null || count === undefined) {
    return <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>—</span>
  }
  if (count === 0) {
    return <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>0</span>
  }
  const bg = critical > 0 ? '#dc2626'   // red — has critical CVEs
           : high > 0     ? '#ea580c'   // orange — has high CVEs
           : '#6b7280'                  // grey — medium/low only
  const title = `${count} CVE${count !== 1 ? 's' : ''}${critical ? ` (${critical} critical)` : ''}${high ? ` (${high} high)` : ''}`
  return (
    <span title={title} style={{
      display: 'inline-block',
      background: bg,
      color: '#fff',
      borderRadius: '4px',
      padding: '1px 6px',
      fontSize: '0.72rem',
      fontWeight: 600,
      letterSpacing: '0.02em',
      cursor: 'default',
    }}>
      {count}
    </span>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatElapsed(secs) {
  if (secs < 60)  return `${secs}s`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`
}

function formatAgo(secs) {
  if (secs < 5)   return 'just now'
  if (secs < 60)  return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s ago`
  return `${Math.floor(secs / 3600)}h ago`
}

const FILTERS = ['all', 'eol', 'outdated', 'no_patch', 'unknown', 'supported', 'lts']

function downloadCSV(report, filter) {
  const rows = report.items
  if (!rows.length) return

  const headers = [
    'software_name', 'vendor', 'version', 'platform', 'file_type',
    'eol_status', 'eol_date', 'latest_version', 'latest_source_url',
    'confidence', 'ref_source', 'ref_notes'
  ]

  const escape = v => {
    const s = String(v ?? '')
    return s.includes(',') || s.includes('"') || s.includes('\n')
      ? `"${s.replace(/"/g, '""')}"`
      : s
  }

  const lines = [
    headers.join(','),
    ...rows.map(r => headers.map(h => escape(r[h])).join(','))
  ]

  const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `s3c_report_${filter}_${new Date().toISOString().slice(0,10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export default function ResultsPage() {
  const { uuid }           = useParams()
  const [searchParams]     = useSearchParams()
  const rtoken             = searchParams.get('rtoken') || null

  const navigate = useNavigate()

  const [job,           setJob]           = useState(null)
  const [report,        setReport]        = useState(null)
  const [filter,        setFilter]        = useState('all')
  const [error,         setError]         = useState('')
  const [polling,       setPolling]       = useState(true)
  const [resent,        setResent]        = useState(false)
  const [deleting,      setDeleting]      = useState(false)
  const [elapsedSecs,   setElapsedSecs]   = useState(0)
  const [activitySecs,  setActivitySecs]  = useState(null) // secs since last matched_count change
  const intervalRef    = useRef()
  const clockRef       = useRef()
  const jobStartRef    = useRef(null)  // Date — set from job.created_at on first load
  const lastCountRef   = useRef(null)  // last seen matched_count
  const lastActivityRef= useRef(null)  // Date of last matched_count change

  // Poll job status until complete
  useEffect(() => {
    async function poll() {
      try {
        const j = await getJobStatus(uuid, rtoken)
        setJob(j)

        // Stamp client-side start time on first poll (avoids server/client
        // timezone mismatches that would make elapsed go negative)
        if (!jobStartRef.current) {
          jobStartRef.current = new Date()
        }

        // Detect when matched_count advances — record as last activity
        const count = j.matched_count ?? 0
        if (lastCountRef.current === null || count > lastCountRef.current) {
          lastCountRef.current  = count
          lastActivityRef.current = new Date()
        }

        if (j.status === 'complete' || j.status === 'failed') {
          clearInterval(intervalRef.current)
          clearInterval(clockRef.current)
          setPolling(false)
          if (j.status === 'complete') {
            const r = await getJobReport(uuid, 'all', rtoken)
            setReport(r)
          }
        }
      } catch (err) {
        setError(err.message)
        clearInterval(intervalRef.current)
        clearInterval(clockRef.current)
        setPolling(false)
      }
    }

    // 1-second clock tick — updates elapsed + last-activity displays
    clockRef.current = setInterval(() => {
      if (jobStartRef.current) {
        setElapsedSecs(Math.floor((Date.now() - jobStartRef.current) / 1000))
      }
      if (lastActivityRef.current) {
        setActivitySecs(Math.floor((Date.now() - lastActivityRef.current) / 1000))
      }
    }, 1000)

    poll()
    intervalRef.current = setInterval(poll, 2000)
    return () => {
      clearInterval(intervalRef.current)
      clearInterval(clockRef.current)
    }
  }, [uuid])

  // Re-fetch report when filter changes
  useEffect(() => {
    if (!report) return
    getJobReport(uuid, filter, rtoken)
      .then(setReport)
      .catch(err => setError(err.message))
  }, [filter])

  async function handleResend() {
    try {
      await resendReport(uuid)
      setResent(true)
    } catch (err) {
      setError(err.message)
    }
  }

  async function handleDelete() {
    if (!window.confirm(`Delete this scan (${job.filename})? This cannot be undone.`)) return
    setDeleting(true)
    try {
      await deleteJob(uuid)
      navigate('/')
    } catch (err) {
      setError(err.message)
      setDeleting(false)
    }
  }

  if (error) return (
    <div style={{ maxWidth: 700, margin: '0 auto' }}>
      <div className="alert alert-error">{error}</div>
      <Link to="/" className="btn btn-ghost mt-16">← Back to upload</Link>
    </div>
  )

  if (!job) return <div className="loading-center"><div className="spinner" /><span className="text-muted">Loading…</span></div>

  const summary = report?.summary ?? {}
  const items   = report?.items   ?? []

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto' }}>

      {/* Header */}
      <div className="flex-between mb-24" style={{ flexWrap: 'wrap', gap: 12 }}>
        <div>
          <Link to="/" style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>← New scan</Link>
          <h1 style={{ fontSize: '1.5rem', marginTop: 6 }}>
            {job.filename || 'Inventory Report'}
          </h1>
          <p className="text-muted" style={{ fontSize: '0.875rem' }}>
            {job.row_count?.toLocaleString()} items scanned
            {job.completed_at ? ` · ${new Date(job.completed_at).toLocaleString()}` : ''}
          </p>
        </div>
        {report && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {!rtoken && (
              <button
                className="btn btn-ghost"
                onClick={handleResend}
                disabled={resent}
                title="Re-send the 24-hour report link to your email"
              >
                {resent ? '✓ Link sent' : '📧 Email link'}
              </button>
            )}
            <button className="btn btn-ghost" onClick={() => downloadCSV(report, filter)}>
              ⬇ Download CSV
            </button>
            <button
              className="btn btn-ghost"
              onClick={handleDelete}
              disabled={deleting}
              title="Delete this scan and all its data"
              style={{ color: 'var(--eol)' }}
            >
              {deleting ? 'Deleting…' : '🗑 Delete scan'}
            </button>
          </div>
        )}
      </div>

      {/* Processing state */}
      {polling && (() => {
        const pct      = job.progress_pct ?? 0
        const matched  = job.matched_count ?? 0
        const total    = job.row_count ?? 0
        const isPending   = job.status === 'pending'
        const isStale     = activitySecs !== null && activitySecs > 360 // 6+ min without activity
        const statusLabel = isPending ? 'Waiting for processor' : 'Actively processing'
        const statusColor = isPending ? 'var(--text-muted)' : 'var(--supported)'

        return (
          <div className="card mb-24">

            {/* Title row */}
            <div className="flex-between mb-16">
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div className="spinner" />
                <span style={{ fontWeight: 600 }}>Processing your inventory…</span>
              </div>
              <span style={{ fontSize: '0.75rem', color: statusColor, fontWeight: 600 }}>
                {statusLabel}
              </span>
            </div>

            {/* Progress bar */}
            <div className="progress-bar mb-8" style={{ height: 10, borderRadius: 6 }}>
              <div
                className="progress-fill"
                style={{ width: `${pct}%`, borderRadius: 6, transition: 'width 0.6s ease' }}
              />
            </div>

            {/* Counts + percent */}
            <div className="flex-between mt-8 mb-16" style={{ fontSize: '0.8rem' }}>
              <span className="text-muted">
                <strong style={{ color: 'var(--text)' }}>{matched.toLocaleString()}</strong>
                {' / '}
                {total.toLocaleString()} items processed
              </span>
              <span style={{ fontWeight: 700, fontSize: '0.95rem', color: pct > 0 ? 'var(--accent)' : 'var(--text-muted)' }}>
                {pct}%
              </span>
            </div>

            {/* Elapsed + last activity */}
            <div style={{
              display: 'flex', gap: 20, flexWrap: 'wrap',
              borderTop: '1px solid var(--border)', paddingTop: 12,
              fontSize: '0.8rem', color: 'var(--text-muted)'
            }}>
              <span>
                ⏱ Elapsed: <strong style={{ color: 'var(--text)' }}>{formatElapsed(elapsedSecs)}</strong>
              </span>
              {activitySecs !== null && (
                <span style={{ color: isStale ? 'var(--warning)' : 'var(--text-muted)' }}>
                  {isStale ? '⚠' : '🔄'} Last activity:{' '}
                  <strong style={{ color: isStale ? 'var(--warning)' : 'var(--text)' }}>
                    {formatAgo(activitySecs)}
                  </strong>
                </span>
              )}
            </div>

            {/* Hint: shown after 2 min or when stale */}
            {(elapsedSecs > 120 || isStale) && (
              <div className="alert alert-info mt-12" style={{ marginBottom: 0, fontSize: '0.8rem' }}>
                {isStale
                  ? 'No activity detected for several minutes. The job is waiting for the next scheduled processor ping (every 5 minutes). Large files may span multiple cycles.'
                  : 'Files process in 5-minute cycles. You\'ll receive an email when the report is ready — you can safely close this page.'
                }
              </div>
            )}

          </div>
        )
      })()}

      {/* Summary cards */}
      {report && (
        <div className="stats-grid mb-24">
          {[
            { key: 'eol',       label: 'End of Life',  color: 'var(--eol)'       },
            { key: 'no_patch',  label: 'No Patch',     color: 'var(--no-patch)'  },
            { key: 'unknown',   label: 'Unknown',      color: 'var(--unknown)'   },
            { key: 'supported', label: 'Supported',    color: 'var(--supported)' },
            { key: 'lts',       label: 'LTS',          color: 'var(--lts)'       },
          ].map(({ key, label, color }) => (
            <div
              key={key}
              className="stat-card"
              style={{ cursor: 'pointer', outline: filter === key ? `2px solid ${color}` : 'none' }}
              onClick={() => setFilter(filter === key ? 'all' : key)}
            >
              <div className="stat-num" style={{ color }}>{(summary[key] ?? 0).toLocaleString()}</div>
              <div className="stat-label">{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Filter tabs */}
      {report && (
        <div className="filter-tabs">
          {FILTERS.map(f => (
            <button
              key={f}
              className={`filter-tab${filter === f ? (f === 'eol' ? ' active-eol' : ' active') : ''}`}
              onClick={() => setFilter(f)}
            >
              {f === 'all' ? `All (${job.row_count?.toLocaleString()})` : f.replace('_', ' ')}
              {f !== 'all' && summary[f] != null ? ` (${summary[f]})` : ''}
            </button>
          ))}
        </div>
      )}

      {/* Results table */}
      {report && items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Software</th>
                <th>Vendor</th>
                <th>Your version</th>
                <th>Status</th>
                <th>EOL date</th>
                <th>Latest</th>
                <th>CVEs</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 500 }}>
                    {row.software_name}
                    {row.parent_app && (
                      <span className="text-muted" style={{ fontSize: '0.75rem', display: 'block' }}>
                        in {row.parent_app}
                      </span>
                    )}
                  </td>
                  <td className="muted">{row.vendor || '—'}</td>
                  <td className="mono">{row.version || '—'}</td>
                  <td><StatusBadge status={row.eol_status} /></td>
                  <td className="mono muted">{row.eol_date || '—'}</td>
                  <td className="mono">
                    {row.latest_version ? (
                      row.latest_source_url
                        ? <a href={row.latest_source_url} target="_blank" rel="noreferrer">{row.latest_version}</a>
                        : row.latest_version
                    ) : '—'}
                  </td>
                  <td>
                    <CveBadge count={row.cve_count} critical={row.cve_critical} high={row.cve_high} />
                  </td>
                  <td className="muted" style={{ fontSize: '0.75rem' }}>
                    {row.ref_source || '—'}
                    {row.confidence ? ` (${row.confidence}%)` : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {report && items.length === 0 && (
        <div className="empty-state">
          <div className="empty-state-icon">✅</div>
          <h3>No items in this category</h3>
          <p>Try a different filter above.</p>
        </div>
      )}

    </div>
  )
}
