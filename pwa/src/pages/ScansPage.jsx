import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getMyJobs, deleteJob } from '../api/wordpress'
import StatusBadge from '../components/StatusBadge'

function formatDate(str) {
  if (!str) return '—'
  return new Date(str + 'Z').toLocaleString()
}

export default function ScansPage() {
  const [jobs,    setJobs]    = useState(null)
  const [error,   setError]   = useState('')
  const [deleting, setDeleting] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    getMyJobs()
      .then(setJobs)
      .catch(err => setError(err.message))
  }, [])

  async function handleDelete(uuid, filename) {
    if (!window.confirm(`Delete "${filename}"? This cannot be undone.`)) return
    setDeleting(uuid)
    try {
      await deleteJob(uuid)
      setJobs(jobs.filter(j => j.uuid !== uuid))
    } catch (err) {
      setError(err.message)
    } finally {
      setDeleting(null)
    }
  }

  if (error) return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <div className="alert alert-error">{error}</div>
    </div>
  )

  if (!jobs) return (
    <div className="loading-center"><div className="spinner" /><span className="text-muted">Loading…</span></div>
  )

  return (
    <div style={{ maxWidth: 900, margin: '0 auto' }}>

      <div className="flex-between mb-24">
        <div>
          <h1 style={{ fontSize: '1.5rem' }}>My Scans</h1>
          <p className="text-muted" style={{ fontSize: '0.875rem' }}>
            {jobs.length} scan{jobs.length !== 1 ? 's' : ''} total
          </p>
        </div>
        <Link to="/" className="btn btn-primary">+ New Scan</Link>
      </div>

      {jobs.length === 0 && (
        <div className="empty-state">
          <div className="empty-state-icon">📂</div>
          <h3>No scans yet</h3>
          <p>Upload an inventory CSV to get started.</p>
          <Link to="/" className="btn btn-primary mt-16">Upload now</Link>
        </div>
      )}

      {jobs.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Status</th>
                <th>Rows</th>
                <th>EOL</th>
                <th>Uploaded</th>
                <th>Completed</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {jobs.map(job => (
                <tr key={job.uuid} style={{ cursor: job.status === 'complete' ? 'pointer' : 'default' }}
                  onClick={() => job.status === 'complete' && navigate(`/results/${job.uuid}`)}>
                  <td style={{ fontWeight: 500, maxWidth: 260 }}>
                    <span style={{ wordBreak: 'break-all' }}>{job.filename || '—'}</span>
                  </td>
                  <td>
                    {job.status === 'complete'  && <StatusBadge status="supported" label="Complete" />}
                    {job.status === 'pending'   && <StatusBadge status="unknown"   label="Pending"  />}
                    {job.status === 'processing'&& <StatusBadge status="lts"       label="Processing"/>}
                    {job.status === 'failed'    && <StatusBadge status="eol"       label="Failed"   />}
                  </td>
                  <td className="mono">{(job.row_count ?? 0).toLocaleString()}</td>
                  <td className="mono" style={{ color: job.eol_count > 0 ? 'var(--eol)' : 'var(--text-muted)' }}>
                    {job.eol_count > 0 ? job.eol_count.toLocaleString() : '—'}
                  </td>
                  <td className="muted" style={{ fontSize: '0.8rem', whiteSpace: 'nowrap' }}>
                    {formatDate(job.created_at)}
                  </td>
                  <td className="muted" style={{ fontSize: '0.8rem', whiteSpace: 'nowrap' }}>
                    {job.status === 'complete' ? formatDate(job.completed_at) : '—'}
                  </td>
                  <td onClick={e => e.stopPropagation()}>
                    <button
                      className="btn btn-ghost"
                      style={{ fontSize: '0.8rem', color: 'var(--eol)', padding: '4px 10px' }}
                      disabled={deleting === job.uuid}
                      onClick={() => handleDelete(job.uuid, job.filename)}
                    >
                      {deleting === job.uuid ? '…' : '🗑'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

    </div>
  )
}
