export default function DocsPage() {
  const code = (s) => (
    <code style={{ fontFamily: 'var(--font-mono)', background: 'var(--bg-input)', padding: '2px 6px', borderRadius: 4, fontSize: '0.85em' }}>
      {s}
    </code>
  )

  return (
    <div style={{ maxWidth: 760, margin: '0 auto' }}>
      <h1 style={{ fontSize: '1.75rem', marginBottom: 8 }}>Documentation</h1>
      <p className="text-muted mb-24">How to generate an inventory file and upload it to S3C-Tool.</p>

      {/* Downloads */}
      <div className="card mb-24">
        <div className="card-title">📦 Download Scanners</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
          {[
            { name: 'macOS Scanner',   file: 's3c_scan_mac.py',      icon: '🍎', cmd: 'python3 s3c_scan_mac.py --quick' },
            { name: 'Linux Scanner',   file: 's3c_scan_linux.py',    icon: '🐧', cmd: 'python3 s3c_scan_linux.py --quick' },
            { name: 'Windows Scanner', file: 's3c_scan_windows.ps1', icon: '🪟', cmd: '.\\s3c_scan_windows.ps1 -Quick' },
          ].map(({ name, file, icon, cmd }) => (
            <div key={file} style={{ background: 'var(--bg-input)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: 16 }}>
              <div style={{ fontSize: '1.5rem', marginBottom: 8 }}>{icon}</div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>{name}</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 12 }}>
                {code(file)}
              </div>
              <a
                href={`https://askmcconnell.com/s3c/scanners/${file}`}
                className="btn btn-ghost btn-sm"
                download
              >
                ⬇ Download
              </a>
            </div>
          ))}
        </div>
      </div>

      {/* Quick start */}
      <div className="card mb-24">
        <div className="card-title">🚀 Quick Start</div>
        <ol style={{ paddingLeft: 20, lineHeight: 2.2, color: 'var(--text-muted)', fontSize: '0.9rem' }}>
          <li>Download the scanner for your platform above</li>
          <li>
            <strong>macOS/Linux</strong>: Requires Python 3.8+ (pre-installed on macOS and most Linux distros) &nbsp;·&nbsp;
            <strong>Windows</strong>: Requires PowerShell (pre-installed on Windows 10+)
          </li>
          <li>
            Run: {code('python3 s3c_scan_mac.py --quick')} (macOS/Linux)
            &nbsp;or&nbsp; {code('.\\s3c_scan_windows.ps1 -Quick')} (Windows)
            <span style={{ display: 'block', fontSize: '0.8rem', marginTop: 2 }}>
              Output: {code('s3c_inventory_[platform]_YYYY-MM-DD.csv')}
            </span>
          </li>
          <li>Log in and upload the CSV on the <a href="/s3c/">Upload page</a></li>
          <li>Your EOL/EOS report is ready in seconds</li>
        </ol>
        <div className="alert alert-info mt-16" style={{ marginBottom: 0 }}>
          The <strong>--quick</strong> flag scans apps and CLI tools only (~30 seconds).
          Full scan (without flag) includes bundled frameworks and libraries (~2–5 minutes).
        </div>
      </div>

      {/* CSV format */}
      <div className="card mb-24">
        <div className="card-title">📋 CSV Format v1.0</div>
        <p className="text-muted mb-16" style={{ fontSize: '0.875rem' }}>
          S3C-Tool expects these 17 columns. The scanners produce this format automatically.
          Only {code('software_name')} is required — all other columns are optional.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Column</th><th>Required</th><th>Example</th><th>Notes</th></tr>
            </thead>
            <tbody>
              {[
                ['s3c_format_version', '—', '1.0',         'Always "1.0"'],
                ['scan_date',           '—', '2026-04-05',  'ISO 8601 date'],
                ['hostname_hash',       '—', 'a3f9b2c1…',  'SHA-256 prefix (privacy)'],
                ['platform',            '—', 'mac',         'mac | linux | windows'],
                ['arch',                '—', 'arm64',       'CPU architecture'],
                ['os_version',          '—', 'macOS 15.3',  'OS version string'],
                ['filename',            '—', 'Slack.app',   'File or bundle name'],
                ['filepath',            '—', '/Applications/Slack.app', 'Full path'],
                ['software_name',       '✓', 'Slack',       'Product name (required)'],
                ['vendor',              '—', 'Slack Technologies', 'Publisher'],
                ['version',             '—', '4.42.0',      'Installed version'],
                ['file_version',        '—', '4.42.0.0',    'Binary file version'],
                ['file_size_bytes',     '—', '284672',      'Integer'],
                ['file_type',           '—', 'app',         'app | binary | library | package | snap | flatpak'],
                ['parent_app',          '—', 'Slack',       'Containing bundle name'],
                ['install_date',        '—', '2026-01-15',  'ISO 8601 date'],
                ['source',              '—', 'plist',       'How version was found'],
              ].map(([col, req, ex, note]) => (
                <tr key={col}>
                  <td>{code(col)}</td>
                  <td style={{ textAlign: 'center', color: req === '✓' ? 'var(--supported)' : 'var(--text-dim)' }}>{req}</td>
                  <td className="mono" style={{ fontSize: '0.8rem' }}>{ex}</td>
                  <td className="muted" style={{ fontSize: '0.8rem' }}>{note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Status codes */}
      <div className="card mb-24">
        <div className="card-title">🔴 Status Definitions</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[
            ['eol',       'var(--eol)',       'End of Life',  'Vendor has officially ended support. No more security patches.'],
            ['no_patch',  'var(--no-patch)',  'No Patch',     'No security patches released in 12+ months but no formal EOL announced.'],
            ['unknown',   'var(--unknown)',   'Unknown',      'Not in reference database yet. Will be researched nightly.'],
            ['supported', 'var(--supported)', 'Supported',    'Currently receiving security updates from the vendor.'],
            ['lts',       'var(--lts)',       'LTS',          'Long-term support — extended patch cycle.'],
          ].map(([status, color, label, desc]) => (
            <div key={status} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
              <div style={{ width: 10, height: 10, borderRadius: '50%', background: color, marginTop: 5, flexShrink: 0 }} />
              <div>
                <span style={{ fontWeight: 600, color }}>{label}</span>
                <span className="text-muted" style={{ fontSize: '0.875rem', marginLeft: 8 }}>{desc}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* FAQ */}
      <div className="card">
        <div className="card-title">❓ FAQ</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20, fontSize: '0.9rem' }}>
          {[
            ['Is my data private?',
             'Yes. Your hostname is stored as a one-way SHA-256 hash — we never see your actual machine name. File paths and software names are stored only for the duration of your session report.'],
            ['How is the reference database populated?',
             'A Raspberry Pi research agent runs nightly, querying endoflife.date (442+ products), manufacturer lifecycle pages, and Claude AI as a last resort. Results are pushed to IONOS nightly.'],
            ['What if my software shows "Unknown"?',
             '"Unknown" means it isn\'t in the reference DB yet. It\'s queued for research and will resolve within 1–3 nightly cycles. Upload the same file again in a few days to see updated results.'],
            ['Can I upload multiple platforms?',
             'Each upload is one CSV from one platform. Upload separately for Mac, Linux, and Windows machines. All reports are in your account history.'],
            ['What are the scanner prerequisites?',
             'macOS and Linux: Python 3.8 or newer (pre-installed on macOS and most Linux distros). Windows: PowerShell 5.1 or newer, which is pre-installed on Windows 10 and 11 — no download required.'],
          ].map(([q, a]) => (
            <div key={q}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>{q}</div>
              <div className="text-muted">{a}</div>
            </div>
          ))}
        </div>
      </div>

    </div>
  )
}
