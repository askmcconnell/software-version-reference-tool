export default function SupportPage() {
  return (
    <div style={{ maxWidth: 580, margin: '64px auto', textAlign: 'center', padding: '0 16px' }}>

      <div style={{ fontSize: '2.5rem', marginBottom: 16 }}>♥</div>
      <h1 style={{ fontSize: '1.75rem', marginBottom: 12 }}>Support S3C-Tool</h1>
      <p className="text-muted" style={{ fontSize: '1rem', lineHeight: 1.7, marginBottom: 32 }}>
        S3C-Tool is free, open-source, and has no paywalls or upload limits.
        If it's saved you time tracking down EOL software, a voluntary
        contribution helps keep the lights on — Raspberry Pi electricity,
        Claude API costs, and the occasional coffee.
      </p>

      <a
        href="https://buy.stripe.com/00w9ATgA76dE2aOcuqcZa00"
        target="_blank"
        rel="noopener noreferrer"
        className="btn btn-primary"
        style={{ fontSize: '1.1rem', padding: '14px 36px', display: 'inline-block', marginBottom: 12 }}
      >
        Contribute $20.26
      </a>
      <p className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 40 }}>
        One-time · Secure checkout via Stripe · No account required
      </p>

      <div className="card" style={{ textAlign: 'left' }}>
        <div className="card-title" style={{ marginBottom: 16 }}>What your contribution supports</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: '0.9rem', color: 'var(--text-muted)' }}>
          {[
            ['Claude API', 'AI-powered EOL research for software the public databases don\'t cover'],
            ['Raspberry Pi', '24/7 research agent running nightly to expand the reference database'],
            ['Hosting', 'IONOS shared hosting for the WordPress backend and file storage'],
            ['Open source', 'Keeping S3C-Tool free, with no upload quotas or subscription tiers'],
          ].map(([title, desc]) => (
            <div key={title} style={{ display: 'flex', gap: 12 }}>
              <div style={{ color: 'var(--accent)', flexShrink: 0, fontSize: '1rem' }}>→</div>
              <div><strong>{title}</strong> — {desc}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-24" style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
        Want to contribute code or EOL data instead?{' '}
        <a
          href="https://github.com/askmcconnell/s3c-tool"
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: 'var(--accent)' }}
        >
          S3C-Tool is on GitHub
        </a>
        {' '}— pull requests welcome.
      </div>

    </div>
  )
}
