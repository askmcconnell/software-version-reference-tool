import { useState, useEffect, useCallback } from 'react'
import { getReference, searchReference } from '../api/wordpress'
import StatusBadge from '../components/StatusBadge'

const STATUS_FILTERS = ['', 'eol', 'supported', 'lts', 'no_patch', 'unknown']

export default function ReferencePage() {
  const [data,    setData]    = useState(null)
  const [query,   setQuery]   = useState('')
  const [status,  setStatus]  = useState('')
  const [page,    setPage]    = useState(1)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = query.length >= 2
        ? await searchReference(query)
        : await getReference({ page, perPage: 100, status })
      setData(res)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [query, status, page])

  useEffect(() => {
    const t = setTimeout(load, query ? 400 : 0)
    return () => clearTimeout(t)
  }, [load])

  useEffect(() => { setPage(1) }, [status, query])

  const items = data?.items ?? []
  const total = data?.total ?? data?.count ?? 0
  const pages = data?.pages ?? 1

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>

      {/* Header */}
      <div className="flex-between mb-24" style={{ flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ fontSize: '1.5rem' }}>Reference Database</h1>
          <p className="text-muted" style={{ fontSize: '0.875rem' }}>
            {total.toLocaleString()} entries · updated nightly by the S3C research agent
          </p>
        </div>
      </div>

      {/* Search + filter */}
      <div className="card mb-16">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 12 }}>
          <input
            className="input"
            type="search"
            placeholder="Search software name or vendor…"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          <select
            className="input"
            style={{ width: 'auto' }}
            value={status}
            onChange={e => setStatus(e.target.value)}
          >
            <option value="">All statuses</option>
            {STATUS_FILTERS.slice(1).map(s => (
              <option key={s} value={s}>{s.replace('_', ' ')}</option>
            ))}
          </select>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {loading ? (
        <div className="loading-center"><div className="spinner" /><span className="text-muted">Loading…</span></div>
      ) : items.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">🔍</div>
          <h3>No results</h3>
          <p>Try a different search or filter.</p>
        </div>
      ) : (
        <>
          <div className="table-wrap">
            <table style={{ minWidth: 860 }}>
              <thead>
                <tr>
                  <th style={{ minWidth: 180 }}>Software</th>
                  <th style={{ minWidth: 130 }}>Vendor</th>
                  <th style={{ minWidth: 90  }}>Version</th>
                  <th style={{ minWidth: 90  }}>Platform</th>
                  <th style={{ minWidth: 110 }}>Status</th>
                  <th style={{ minWidth: 90  }}>EOL date</th>
                  <th style={{ minWidth: 100 }}>Latest</th>
                  <th style={{ minWidth: 100 }}>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row, i) => (
                  <tr key={i}>
                    <td style={{ fontWeight: 500 }}>{row.software_name}</td>
                    <td className="muted">{row.vendor || '—'}</td>
                    <td className="mono">{row.version || '—'}</td>
                    <td className="muted">{row.platform || '—'}</td>
                    <td><StatusBadge status={row.eol_status} /></td>
                    <td className="mono muted">{row.eol_date || '—'}</td>
                    <td className="mono">
                      {row.latest_version
                        ? row.latest_source_url
                          ? <a href={row.latest_source_url} target="_blank" rel="noreferrer">{row.latest_version}</a>
                          : row.latest_version
                        : '—'}
                    </td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <div style={{
                          width: 40, height: 4, background: 'var(--bg-input)',
                          borderRadius: 2, overflow: 'hidden'
                        }}>
                          <div style={{
                            width: `${row.confidence ?? 0}%`,
                            height: '100%',
                            background: row.confidence >= 80 ? 'var(--supported)' :
                                        row.confidence >= 50 ? 'var(--warning)' : 'var(--eol)',
                            borderRadius: 2,
                          }} />
                        </div>
                        <span className="text-muted" style={{ fontSize: '0.75rem' }}>{row.confidence ?? 0}%</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {pages > 1 && !query && (
            <div className="flex-center mt-16" style={{ gap: 8, justifyContent: 'center' }}>
              <button
                className="btn btn-ghost btn-sm"
                disabled={page <= 1}
                onClick={() => setPage(p => p - 1)}
              >← Prev</button>
              <span className="text-muted" style={{ fontSize: '0.875rem' }}>
                Page {page} of {pages}
              </span>
              <button
                className="btn btn-ghost btn-sm"
                disabled={page >= pages}
                onClick={() => setPage(p => p + 1)}
              >Next →</button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
