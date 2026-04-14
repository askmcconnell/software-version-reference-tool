import { Link } from 'react-router-dom'

export default function PrivacyPage() {
  return (
    <div style={{ maxWidth: 680, margin: '48px auto', padding: '0 16px 64px' }}>

      <h1 style={{ fontSize: '1.75rem', marginBottom: 8 }}>Privacy &amp; Data Practices</h1>
      <p className="text-muted" style={{ fontSize: '0.9rem', marginBottom: 40 }}>
        Last updated April 2026 · S3C-Tool is open source —{' '}
        <a
          href="https://github.com/askmcconnell/software-version-reference-tool"
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: 'var(--accent)' }}
        >
          audit the code yourself
        </a>
      </p>

      <Section title="The short version">
        <p>
          S3C-Tool never sees your actual hostnames, file contents, or personal data beyond
          your email address. Hostnames are one-way hashed before they ever leave your machine.
          Software inventory data (names, versions, vendors) is used to generate your report
          and improve the shared reference database — nothing else.
        </p>
      </Section>

      <Section title="What your scanner collects">
        <p style={{ marginBottom: 12 }}>
          The scanner scripts run entirely on your machine. Before any data is uploaded, the scanner:
        </p>
        <BulletList items={[
          ['Hostname', 'Replaced with a SHA-256 hash on-device. The original hostname never leaves your machine and cannot be recovered from the hash.'],
          ['Software names, versions, vendors', 'Collected from installed applications. This is the core data S3C-Tool needs to check EOL status.'],
          ['Platform and architecture', 'e.g. macOS arm64, Windows x64, Linux x86_64. Used to match the correct EOL record.'],
          ['File paths and sizes', 'Collected for context but not used in EOL lookups and not shared with third parties.'],
          ['Scan date', 'Timestamp of when the scan ran on your machine.'],
        ]} />
        <p className="text-muted" style={{ fontSize: '0.85rem', marginTop: 12 }}>
          No file contents, no registry values, no network data, no browser history, no credentials.
        </p>
      </Section>

      <Section title="What is stored on our servers">
        <p style={{ marginBottom: 12 }}>
          When you upload a CSV, S3C-Tool stores on IONOS shared hosting (EU):
        </p>
        <BulletList items={[
          ['Your email address', 'Used to authenticate your account. Not shared with anyone.'],
          ['The uploaded inventory rows', 'Software name, version, vendor, platform, hashed hostname, scan date. Stored to generate your report and populate the research queue.'],
          ['Your job results', 'The enriched EOL report, linked to your account, accessible via the Results page.'],
          ['Aggregate reference data', 'Software name + EOL status entries go into the shared reference database. These contain no hostname hash or account information.'],
        ]} />
      </Section>

      <Section title="What AI models see">
        <p style={{ marginBottom: 12 }}>
          When a software product isn't found in the endoflife.date database, GitHub, or Repology,
          a research agent on a Raspberry Pi queries AI models to determine EOL status.
          The AI is sent <strong>only</strong>:
        </p>
        <CodeBlock lines={[
          'Product:  nginx',
          'Vendor:   F5 / NGINX Inc.',
          'Version:  1.18',
          'Platform: linux',
        ]} />
        <p style={{ marginTop: 12 }}>
          No hostname hash, no file paths, no account information, no user data of any kind
          is included in AI queries. The models used are Claude Haiku (Anthropic),
          GPT-4o-mini (OpenAI), and Gemini Flash (Google).
        </p>
      </Section>

      <Section title="The shared reference database">
        <p>
          EOL research results are stored in a shared SQLite database and synced to IONOS nightly.
          This is what makes S3C-Tool faster for everyone over time — a product researched for one
          user is instantly available for all future uploads.
        </p>
        <p style={{ marginTop: 12 }}>
          Reference database entries contain: software name, vendor, version, EOL status,
          EOL date, latest version, confidence score, and source. They contain
          no user identifiers, no hostname hashes, and no account information.
          The reference database is{' '}
          <a
            href="https://github.com/askmcconnell/software-version-reference-tool/tree/main/reference-db"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: 'var(--accent)' }}
          >
            partially public on GitHub
          </a>
          {' '}in YAML format.
        </p>
      </Section>

      <Section title="Data retention">
        <BulletList items={[
          ['Upload jobs and inventory rows', 'Retained indefinitely to support re-processing and report access. No automatic deletion yet — this will be configurable in a future release.'],
          ['Reference database entries', 'EOL facts expire after 90 days and are re-verified. "Supported" entries expire after 14 days. "Unknown" entries expire after 3 days.'],
          ['API cost logs', 'Stored locally on the Raspberry Pi only. Not synced to IONOS. Used for operational monitoring.'],
          ['Account data', 'Email address retained as long as your account exists. No payment data is stored — Stripe handles all transactions.'],
        ]} />
      </Section>

      <Section title="Third-party services">
        <BulletList items={[
          ['IONOS (EU)', 'Shared hosting for the WordPress backend, MySQL database, and file storage.'],
          ['Anthropic (Claude)', 'EOL research queries — software name/version/platform only.'],
          ['OpenAI (GPT-4o-mini)', 'EOL research queries — software name/version/platform only.'],
          ['Google (Gemini)', 'EOL research queries — software name/version/platform only.'],
          ['GitHub', 'Repository activity checks for open-source software — product name only.'],
          ['Repology', 'Cross-distro package status — product name only.'],
          ['endoflife.date', 'EOL date lookups — product name only. No data sent.'],
          ['Stripe', 'Optional voluntary donations. S3C-Tool never sees your payment details.'],
        ]} />
      </Section>

      <Section title="Cookies and tracking">
        <p>
          S3C-Tool uses no analytics, no tracking pixels, no third-party cookies, and no advertising.
          A single session token cookie is set on login for authentication. That's it.
        </p>
      </Section>

      <Section title="Questions">
        <p>
          Questions about your data or requests to delete your account can be sent to{' '}
          <a href="mailto:jim@askmcconnell.com" style={{ color: 'var(--accent)' }}>
            jim@askmcconnell.com
          </a>.
          Because S3C-Tool is open source, you can also review exactly what the code does at any time.
        </p>
      </Section>

      <p className="text-muted" style={{ fontSize: '0.8rem', marginTop: 32, textAlign: 'center' }}>
        <Link to="/terms" style={{ color: 'var(--accent)' }}>Terms of Service</Link>
        {' · '}
        <a href="https://github.com/askmcconnell/s3c-tool" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--text-muted)' }}>
          Open source on GitHub
        </a>
      </p>

    </div>
  )
}


function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 36 }}>
      <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: 12, paddingBottom: 8,
                   borderBottom: '1px solid var(--border)' }}>
        {title}
      </h2>
      <div style={{ fontSize: '0.92rem', lineHeight: 1.75, color: 'var(--text)' }}>
        {children}
      </div>
    </div>
  )
}


function BulletList({ items }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {items.map(([label, desc]) => (
        <div key={label} style={{ display: 'flex', gap: 12 }}>
          <div style={{ color: 'var(--accent)', flexShrink: 0, paddingTop: 2 }}>→</div>
          <div>
            <strong>{label}</strong>
            {desc ? <> — {desc}</> : null}
          </div>
        </div>
      ))}
    </div>
  )
}


function CodeBlock({ lines }) {
  return (
    <div style={{
      background: 'var(--surface-raised, #1a1a2e)',
      border: '1px solid var(--border)',
      borderRadius: 6,
      padding: '12px 16px',
      fontFamily: 'monospace',
      fontSize: '0.85rem',
      color: 'var(--text-muted)',
      lineHeight: 1.8,
    }}>
      {lines.map((line, i) => <div key={i}>{line}</div>)}
    </div>
  )
}
