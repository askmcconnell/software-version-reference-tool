import { useState, useRef, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { uploadInventory, getStats } from '../api/wordpress'

export default function UploadPage() {
  const { user } = useAuth()
  const fileRef  = useRef()
  const [dragging,   setDragging]   = useState(false)
  const [file,       setFile]       = useState(null)
  const [error,      setError]      = useState('')
  const [loading,    setLoading]    = useState(false)
  const [stats,      setStats]      = useState(null)
  const [confirmed,  setConfirmed]  = useState(null) // { uuid, filename, rowCount, email }

  useEffect(() => {
    getStats().then(setStats).catch(() => {})
  }, [])

  function handleFile(f) {
    if (!f) return
    const isCsv  = f.name.endsWith('.csv')
    const isJson = f.name.endsWith('.json')
    if (!isCsv && !isJson) { setError('Accepted formats: SVRT CSV (.csv), CycloneDX JSON (.json), SPDX JSON (.json)'); return }
    if (f.size > 2 * 1024 * 1024) { setError('File exceeds 2 MB limit.'); return }
    setError('')
    setFile(f)
  }

  function fileFormatLabel(f) {
    if (!f) return ''
    if (f.name.endsWith('.json')) return 'SBOM (JSON)'
    return 'SVRT CSV'
  }

  function onDrop(e) {
    e.preventDefault()
    setDragging(false)
    handleFile(e.dataTransfer.files[0])
  }

  async function handleUpload() {
    if (!file) return
    setError('')
    setLoading(true)
    try {
      const res = await uploadInventory(file)
      setConfirmed({
        uuid:     res.uuid,
        filename: file.name,
        rowCount: res.row_count,
        email:    user?.email ?? '',
      })
    } catch (err) {
      setError(err.message || 'Upload failed')
    } finally {
      setLoading(false)
    }
  }

  const quotaUsed = user?.uploads_used ?? 0
  const quotaMax  = user?.upload_quota ?? 10
  const quotaPct  = Math.round(quotaUsed / quotaMax * 100)

  // ── Confirmation screen ───────────────────────────────────────────────────
  if (confirmed) {
    return (
      <div style={{ maxWidth: 560, margin: '64px auto', textAlign: 'center' }}>
        <div style={{ fontSize: '3rem', marginBottom: 16 }}>✅</div>
        <h1 style={{ fontSize: '1.5rem', marginBottom: 8 }}>Got your file!</h1>
        <p className="text-muted mb-24" style={{ fontSize: '0.95rem' }}>
          We're processing <strong>{confirmed.filename}</strong> ({confirmed.rowCount?.toLocaleString()} items)
          against the reference database.
        </p>

        <div className="card mb-24" style={{ textAlign: 'left' }}>
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
            <div style={{ fontSize: '1.5rem', flexShrink: 0 }}>📧</div>
            <div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>We'll email you when it's ready</div>
              <div className="text-muted" style={{ fontSize: '0.875rem' }}>
                A link to your report will be sent to <strong>{confirmed.email}</strong>.
                The link is valid for 24 hours. Large files may take up to 30 minutes to process.
              </div>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
          <Link to={`/results/${confirmed.uuid}`} className="btn btn-ghost">
            Watch live
          </Link>
          <button className="btn btn-primary" onClick={() => { setConfirmed(null); setFile(null) }}>
            Upload another file
          </button>
        </div>

        <p className="text-muted mt-24" style={{ fontSize: '0.8rem' }}>
          You can also access all past reports from your account at any time.
        </p>
      </div>
    )
  }

  // ── Upload form ───────────────────────────────────────────────────────────
  return (
    <div style={{ maxWidth: 680, margin: '0 auto' }}>

      {/* Header */}
      <div className="mb-24">
        <h1 style={{ fontSize: '1.75rem', marginBottom: 8 }}>Upload Inventory</h1>
        <p className="text-muted">
          Upload a SVRT-format CSV from your Mac, Linux, or Windows scanner.
          We'll match it against the reference database and email you the results.
        </p>
      </div>

      {/* Stats bar */}
      {stats && (
        <div className="stats-grid mb-24">
          {[
            { num: stats.reference_entries?.toLocaleString(), label: 'Reference entries', color: 'var(--accent)' },
            { num: stats.eol_entries?.toLocaleString(),       label: 'Known EOL',          color: 'var(--eol)' },
            { num: stats.supported_entries?.toLocaleString(), label: 'Supported',           color: 'var(--supported)' },
            { num: stats.scans_completed?.toLocaleString(),   label: 'Scans completed',     color: 'var(--text-muted)' },
          ].map(({ num, label, color }) => (
            <div className="stat-card" key={label}>
              <div className="stat-num" style={{ color }}>{num ?? '—'}</div>
              <div className="stat-label">{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Upload card */}
      <div className="card">
        {error && <div className="alert alert-error">{error}</div>}

        {/* Drop zone */}
        <div
          className={`drop-zone${dragging ? ' drag-over' : ''}`}
          onClick={() => !file && fileRef.current.click()}
          onDragOver={e => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.json,text/csv,application/json"
            style={{ display: 'none' }}
            onChange={e => handleFile(e.target.files[0])}
          />
          {file ? (
            <>
              <div className="drop-zone-icon">{file.name.endsWith('.json') ? '🔍' : '📄'}</div>
              <div className="drop-zone-title">{file.name}</div>
              <div className="drop-zone-sub">
                {fileFormatLabel(file)} · {(file.size / 1024).toFixed(1)} KB — click to change
              </div>
            </>
          ) : (
            <>
              <div className="drop-zone-icon">⬆️</div>
              <div className="drop-zone-title">Drop your inventory file here</div>
              <div className="drop-zone-sub">SVRT CSV · CycloneDX JSON · SPDX JSON — max 5,000 rows / 2 MB</div>
            </>
          )}
        </div>

        {/* Upload button */}
        {file && (
          <button
            className="btn btn-primary btn-full btn-lg mt-16"
            onClick={handleUpload}
            disabled={loading}
          >
            {loading
              ? <><span className="spinner" style={{width:16,height:16}} /> Uploading…</>
              : `Analyze ${file.name}`
            }
          </button>
        )}

        {/* Quota */}
        <div className="mt-16">
          <div className="flex-between mb-8" style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            <span>Upload quota</span>
            <span>{quotaUsed} / {quotaMax} used</span>
          </div>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${quotaPct}%`, background: quotaPct >= 90 ? 'var(--warning)' : undefined }} />
          </div>
        </div>
      </div>

      {/* Instructions */}
      <div className="card mt-24">
        <div className="card-title">Accepted file formats</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, fontSize: '0.875rem' }}>

          <div>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>📄 SVRT CSV — machine inventory scanner</div>
            <ol style={{ paddingLeft: 20, lineHeight: 2, color: 'var(--text-muted)', margin: 0 }}>
              <li>Download the scanner from the <a href="/svrt/docs">Docs page</a></li>
              <li>Run: <code style={{ fontFamily: 'var(--font-mono)', background: 'var(--bg-input)', padding: '1px 6px', borderRadius: 4 }}>python3 svrt_scan_mac.py --quick</code></li>
              <li>Upload the generated <code style={{ fontFamily: 'var(--font-mono)', background: 'var(--bg-input)', padding: '1px 6px', borderRadius: 4 }}>.csv</code> above</li>
            </ol>
          </div>

          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 16 }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>🔍 CycloneDX or SPDX JSON — SBOM import</div>
            <p style={{ color: 'var(--text-muted)', margin: '0 0 6px' }}>
              Already generating SBOMs in your CI/CD pipeline? Upload them directly.
              Compatible with Syft, Trivy, cdxgen, Grype, and any tool producing standard CycloneDX 1.x or SPDX 2.x JSON.
            </p>
          </div>

        </div>
      </div>

    </div>
  )
}
