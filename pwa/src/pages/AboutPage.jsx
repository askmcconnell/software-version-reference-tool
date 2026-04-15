import { Link } from 'react-router-dom'

export default function AboutPage() {
  return (
    <div style={{ maxWidth: 720, margin: '0 auto', padding: '0 16px 80px' }}>

      {/* ── Hero ───────────────────────────────────────────────── */}
      <div style={{ textAlign: 'center', padding: '56px 0 48px' }}>
        <div style={{ display: 'inline-block', background: 'var(--bg-card)', border: '1px solid var(--border)',
                      borderRadius: 8, padding: '4px 14px', fontSize: '0.75rem', fontWeight: 600,
                      letterSpacing: '0.08em', color: 'var(--accent)', textTransform: 'uppercase',
                      marginBottom: 20 }}>
          Open Source · Free to Use
        </div>
        <h1 style={{ fontSize: '2rem', fontWeight: 700, lineHeight: 1.25, marginBottom: 16 }}>
          Know what's running.<br />Know what's at risk.
        </h1>
        <p style={{ fontSize: '1.05rem', color: 'var(--text-muted)', lineHeight: 1.75,
                    maxWidth: 540, margin: '0 auto 32px' }}>
          S3C-Tool is a software supply chain security tool that cross-references your
          software inventory against a continuously updated end-of-life database — so
          you know which software is unsupported before attackers find out first.
        </p>
        <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
          <Link to="/register" className="btn btn-primary" style={{ padding: '10px 28px' }}>
            Try it free
          </Link>
          <a href="https://github.com/askmcconnell/s3c-tool" target="_blank" rel="noopener noreferrer"
             className="btn btn-ghost" style={{ padding: '10px 28px' }}>
            View on GitHub
          </a>
        </div>
      </div>

      <Divider />

      {/* ── The Problem ────────────────────────────────────────── */}
      <Section>
        <SectionLabel>The Problem</SectionLabel>
        <h2>End-of-life software is the attack surface nobody's watching</h2>
        <p>
          Every software package has a lifecycle. Vendors publish a version, support it for
          a few years, then move on. When support ends — no more patches, no more security
          fixes. But the software doesn't uninstall itself.
        </p>
        <p>
          Organizations routinely run hundreds of applications, libraries, and OS components.
          Keeping track of which ones are still supported is a manual, error-prone process
          that falls through the cracks of standard vulnerability management workflows.
          CVE scanners find known vulnerabilities. They don't tell you that the entire
          product is past its end-of-life date and will never receive another patch —
          regardless of what new CVEs are discovered tomorrow.
        </p>
        <CalloutBox>
          End-of-life software isn't just a known-vulnerability problem. It's a
          <strong> no-future-patch problem</strong> — and most security tools don't
          distinguish the two.
        </CalloutBox>
      </Section>

      <Divider />

      {/* ── How It Works ───────────────────────────────────────── */}
      <Section>
        <SectionLabel>How It Works</SectionLabel>
        <h2>Upload an inventory. Get a report.</h2>
        <p>
          S3C-Tool uses lightweight scanner scripts for macOS, Linux, and Windows that
          inventory installed software and produce a standardized CSV. Upload that file
          and S3C-Tool cross-references every row against a shared reference database —
          returning an EOL/EOS/No-Patch status for each product.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                      gap: 16, margin: '28px 0' }}>
          {[
            ['1', 'Scan', 'Run a scanner script on your Mac, Linux, or Windows machine. Takes under a minute.'],
            ['2', 'Upload', 'Upload the CSV to S3C-Tool. No agent to install. No persistent access to your systems.'],
            ['3', 'Report', 'Get a full EOL/EOS/No-Patch + CVE report. Download it, act on it, share it.'],
          ].map(([num, title, desc]) => (
            <div key={num} style={{ background: 'var(--bg-card)', border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius)', padding: 20 }}>
              <div style={{ fontSize: '1.5rem', fontWeight: 800, color: 'var(--accent)',
                            marginBottom: 8, lineHeight: 1 }}>{num}</div>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>{title}</div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', lineHeight: 1.6 }}>{desc}</div>
            </div>
          ))}
        </div>

        <p>
          The reference database is continuously expanded by a Raspberry Pi research agent
          running around the clock — pulling from endoflife.date, package registries,
          GitHub activity, and AI-assisted research when public data falls short. Results
          are cached and shared across all users: the more the database grows, the faster
          and more accurate reports become for everyone.
        </p>
      </Section>

      <Divider />

      {/* ── The Standard ───────────────────────────────────────── */}
      <Section>
        <SectionLabel>The Standard Initiative</SectionLabel>
        <h2>There's no standard way for vendors to declare EOL status. There should be.</h2>
        <p>
          Right now, if you want to know whether a piece of software is still supported,
          you search the vendor's website, hope they have a lifecycle page, and manually
          read it. If they don't — you guess. Tools like S3C-Tool do their best to
          automate that process, but we're all scraping a web that was never designed
          for machine-readable lifecycle data.
        </p>
        <p>
          The fix is straightforward: give every software project — from enterprise
          vendors to solo open source maintainers — a simple, standardized place to
          publish their own lifecycle data. One JSON file. Machine-readable.
          Authoritative from the source.
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 20, margin: '28px 0' }}>
          <StandardCard
            icon="🌐"
            title="Well-Known URI (IETF Internet-Draft)"
            sub="For vendors and service operators"
            desc="A proposed IETF standard that would establish /.well-known/software-status.json as a canonical location for any domain to publish lifecycle status for the software it runs or distributes. Following the RFC 8615 pattern used by security.txt and other well-known resources."
            tag="Internet-Draft in progress"
          />
          <StandardCard
            icon="🐙"
            title="GitHub Implementation Profile"
            sub="For open source maintainers"
            desc="A companion convention for open source projects: publish .github/software-status.json in your repository to declare authoritative EOL dates for each release series. S3C-Tool already checks this file as part of its lookup chain."
            tag="Draft published"
            href="https://github.com/askmcconnell/s3c-tool/blob/main/docs/github-implementation-profile.md"
            hrefLabel="Read the spec →"
          />
        </div>

        <p>
          These two formats share the same schema intentionally. A tool that reads one
          can read the other. The goal is a future where software lifecycle status is
          as easy to check as a TLS certificate — structured, authoritative, and
          available without scraping.
        </p>
      </Section>

      <Divider />

      {/* ── Support the Standard ───────────────────────────────── */}
      <Section>
        <SectionLabel>Support the Standard</SectionLabel>
        <h2>If you maintain open source software, you can adopt this today</h2>
        <p>
          You don't need to wait for an RFC to be published. Add{' '}
          <code style={codeStyle}>.github/software-status.json</code> to your repository now.
          It takes five minutes, and it makes your users' security posture measurably better.
        </p>

        <div style={{ background: 'var(--bg-input)', border: '1px solid var(--border)',
                      borderRadius: 'var(--radius)', padding: '16px 20px', margin: '20px 0',
                      fontFamily: 'var(--font-mono)', fontSize: '0.8rem', lineHeight: 1.7,
                      color: 'var(--text-muted)', overflowX: 'auto', whiteSpace: 'pre' }}>
{`{
  "schema_version": "1.0",
  "name": "Your Project",
  "vendor": "Your Org",
  "versions": [
    {
      "version": "2.0",
      "status": "active",
      "support_ends": null
    },
    {
      "version": "1.x",
      "status": "eol",
      "eol_date": "2024-12-31"
    }
  ]
}`}
        </div>

        <p>
          S3C-Tool checks for this file when researching any GitHub-hosted project.
          When found, it's stored with <code style={codeStyle}>source=authoritative</code> and
          a confidence score of 95 — the highest possible without manual verification.
          No AI guessing. No web scraping. Straight from the maintainer.
        </p>

        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 24 }}>
          <a
            href="https://github.com/askmcconnell/s3c-tool/blob/main/docs/github-implementation-profile.md"
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-primary btn-sm"
          >
            Read the full spec
          </a>
          <a
            href="https://github.com/askmcconnell/s3c-tool/issues"
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-ghost btn-sm"
          >
            Discuss on GitHub
          </a>
        </div>
      </Section>

      <Divider />

      {/* ── Origin ─────────────────────────────────────────────── */}
      <Section>
        <SectionLabel>Origin</SectionLabel>
        <h2>Built by a security practitioner, for security practitioners</h2>
        <p>
          S3C-Tool was built out of frustration. Running software EOL assessments
          for organizations meant the same painful manual process every time: compile
          an inventory, search vendor lifecycle pages one by one, piece together a
          spreadsheet, and repeat every quarter. There had to be a better way.
        </p>
        <p>
          The shared reference database is the core insight. Every time S3C-Tool looks
          up a product, the result is cached. The next user to scan the same software
          gets an instant answer. Over time, the database grows toward complete coverage
          of the enterprise software landscape — at effectively zero marginal cost per lookup.
        </p>
        <p>
          The standards initiative grew from the same realization: the right long-term fix
          isn't a better scraper. It's giving the people who <em>know</em> the lifecycle data —
          the vendors and maintainers themselves — a simple, standard way to publish it.
        </p>
      </Section>

      <Divider />

      {/* ── CTA ────────────────────────────────────────────────── */}
      <div style={{ textAlign: 'center', padding: '12px 0 0' }}>
        <h2 style={{ fontSize: '1.4rem', marginBottom: 12 }}>Ready to see what's in your environment?</h2>
        <p className="text-muted" style={{ marginBottom: 28, fontSize: '0.95rem' }}>
          Free, open source, no upload limits. Takes under five minutes from download to report.
        </p>
        <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
          <Link to="/register" className="btn btn-primary" style={{ padding: '10px 28px' }}>
            Get started free
          </Link>
          <Link to="/docs" className="btn btn-ghost" style={{ padding: '10px 28px' }}>
            Read the docs
          </Link>
        </div>
        <p style={{ marginTop: 24, fontSize: '0.8rem', color: 'var(--text-muted)' }}>
          Questions?{' '}
          <Link to="/support" style={{ color: 'var(--accent)' }}>Support page</Link>
          {' · '}
          <a href="https://github.com/askmcconnell/s3c-tool" target="_blank" rel="noopener noreferrer"
             style={{ color: 'var(--text-muted)' }}>GitHub</a>
        </p>
      </div>

    </div>
  )
}


// ── Sub-components ──────────────────────────────────────────────────────────

function Divider() {
  return <div style={{ borderTop: '1px solid var(--border)', margin: '8px 0' }} />
}

function Section({ children }) {
  return (
    <div style={{ padding: '40px 0' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16,
                    fontSize: '0.95rem', lineHeight: 1.8, color: 'var(--text)' }}>
        {children}
      </div>
    </div>
  )
}

function SectionLabel({ children }) {
  return (
    <div style={{ fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.1em',
                  textTransform: 'uppercase', color: 'var(--accent)', marginBottom: -4 }}>
      {children}
    </div>
  )
}

function CalloutBox({ children }) {
  return (
    <div style={{ background: 'var(--bg-card)', borderLeft: '3px solid var(--accent)',
                  borderRadius: '0 var(--radius) var(--radius) 0', padding: '14px 18px',
                  fontSize: '0.92rem', color: 'var(--text-muted)', lineHeight: 1.7 }}>
      {children}
    </div>
  )
}

function StandardCard({ icon, title, sub, desc, tag, href, hrefLabel }) {
  return (
    <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)',
                  borderRadius: 'var(--radius)', padding: 20, display: 'flex', gap: 16 }}>
      <div style={{ fontSize: '1.8rem', flexShrink: 0, lineHeight: 1 }}>{icon}</div>
      <div>
        <div style={{ fontWeight: 600, marginBottom: 2 }}>{title}</div>
        <div style={{ fontSize: '0.8rem', color: 'var(--accent)', marginBottom: 8 }}>{sub}</div>
        <div style={{ fontSize: '0.875rem', color: 'var(--text-muted)', lineHeight: 1.65,
                      marginBottom: href ? 10 : 0 }}>
          {desc}
        </div>
        {href && (
          <a href={href} target="_blank" rel="noopener noreferrer"
             style={{ fontSize: '0.8rem', color: 'var(--accent)' }}>
            {hrefLabel}
          </a>
        )}
        <div style={{ display: 'inline-block', marginLeft: href ? 16 : 0,
                      fontSize: '0.7rem', fontWeight: 600, letterSpacing: '0.06em',
                      color: 'var(--text-muted)', textTransform: 'uppercase',
                      background: 'var(--bg-input)', padding: '2px 8px',
                      borderRadius: 4, verticalAlign: 'middle' }}>
          {tag}
        </div>
      </div>
    </div>
  )
}

const codeStyle = {
  fontFamily: 'var(--font-mono)',
  background: 'var(--bg-input)',
  padding: '1px 6px',
  borderRadius: 4,
  fontSize: '0.85em',
}
