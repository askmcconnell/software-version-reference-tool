# S3C-Tool — Software Security Supply Chain Tool

A free, open-source SaaS tool that scans software inventories, identifies end-of-life (EOL), unsupported, and unpatched software, and delivers actionable security reports — powered by a continuously updated shared reference database and a Raspberry Pi research agent.

**Live**: [askmcconnell.com/s3c](https://askmcconnell.com/s3c/) &nbsp;·&nbsp;
**About**: [askmcconnell.com/s3c/about](https://askmcconnell.com/s3c/about)

---

## What It Does

1. **Scan** — run a lightweight scanner on macOS, Linux, or Windows endpoints
2. **Upload** — drag-drop the CSV into the web app
3. **Report** — get a per-product EOL/No-Patch/CVE breakdown for your entire inventory
4. **Share** — every resolved product is cached in a shared reference DB, making future lookups instant for everyone

**Status categories:**

| Status | Meaning |
|--------|---------|
| EOL | End of life — no more patches of any kind |
| No Patch | Supported product with an unpatched known vulnerability |
| LTS | Long-term support release |
| Supported | Current and actively maintained |
| Unknown | Not yet in the reference database |

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│  React PWA (Vite)                                │
│  askmcconnell.com/s3c/                           │
└─────────────────────┬────────────────────────────┘
                      │ REST /wp-json/s3c/v1/
┌─────────────────────▼────────────────────────────┐
│  WordPress Plugin (PHP)                          │
│  MySQL: s3c_subscribers, s3c_upload_jobs,        │
│         s3c_inventory_rows, s3c_reference        │
└─────────────────────┬────────────────────────────┘
                      │ nightly SFTP sync
┌─────────────────────▼────────────────────────────┐
│  Raspberry Pi Research Agent (Python)            │
│  SQLite local cache · 24/7 operation             │
│                                                  │
│  Lookup chain:                                   │
│    1. Local SQLite cache                         │
│    2. endoflife.date API                         │
│    3. GitHub activity / release tags             │
│    4. Repology / package registries              │
│    5. Claude Haiku (AI research)                 │
│    6. Gemini Flash (AI fallback)                 │
│    7. GPT-4o-mini (AI fallback)                  │
│    8. NVD 2.0 API (CVE enrichment)               │
└──────────────────────────────────────────────────┘
```

**Cron schedule (Pi):**
- Every 4 hours — research run, up to 500 items
- Every 6 hours — NVD CVE enrichment, up to 200 items
- Every 5 minutes — trigger WordPress job processor + re-enrichment
- 3:00 AM — Pi → IONOS reference DB sync

---

## Repository Structure

```
agent/
  svrt_agent.py           Research agent — full lookup chain, NVD CVE enrichment

docs/
  github-implementation-profile.md   Spec: .github/software-status.json convention
  draft-mcconnell-software-status-wellknown-00.md    IETF I-D source (kramdown-rfc)
  draft-mcconnell-software-status-wellknown-00.txt   IETF I-D plain text (submitted)
  draft-mcconnell-software-status-wellknown-00.xml   IETF I-D XML (xml2rfc)

pwa/
  src/
    api/                  WordPress REST API client
    components/           Nav, StatusBadge, CveBadge
    contexts/             Auth context
    pages/                Upload, Results, Reference DB, Docs, About, Privacy, Terms
    styles/               Global CSS custom properties

reference-db/
  products/               76+ YAML product lifecycle definitions (community-curated)

scripts/
  mac/s3c_scan_mac.py     macOS scanner
  linux/s3c_scan_linux.py Linux scanner
  windows/s3c_scan_windows.ps1  Windows scanner
  seed_known_eol.py       Seed well-known EOL products into the reference DB

sync/
  push_to_ionos.sh        Nightly Pi → IONOS SFTP sync + unknown-software pull

pi-dashboard/
  status.py               Pi monitoring dashboard (queue depth, cost tracking)

wordpress-plugin/
  svrt/svrt.php           WordPress plugin — REST API, job processing, reference DB
```

---

## Scanner Quick Start

Download and run the scanner for your platform:

**macOS**
```bash
curl -O https://askmcconnell.com/s3c/scanners/s3c_scan_mac.py
python3 s3c_scan_mac.py --quick
```

**Linux**
```bash
curl -O https://askmcconnell.com/s3c/scanners/s3c_scan_linux.py
python3 s3c_scan_linux.py --quick
```

**Windows** (PowerShell, run as Administrator)
```powershell
Invoke-WebRequest https://askmcconnell.com/s3c/scanners/s3c_scan_windows.ps1 -OutFile s3c_scan_windows.ps1
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\s3c_scan_windows.ps1 -Quick
```

Upload the resulting CSV at [askmcconnell.com/s3c](https://askmcconnell.com/s3c/).

---

## Standards Initiative

S3C-Tool is the reference implementation for a proposed IETF standard: a machine-readable, vendor-authoritative way for software projects to declare their own lifecycle status.

### IETF Internet-Draft

**draft-mcconnell-software-status-wellknown-00**
*A Well-Known URI for Software Lifecycle Status*

Proposes `/.well-known/software-status.json` as an IETF-registered Well-Known URI (following RFC 8615 / security.txt precedent) where vendors can publish authoritative EOL dates, LTS windows, and support status for their products.

- **Datatracker**: https://datatracker.ietf.org/doc/draft-mcconnell-software-status-wellknown/
- **Source**: [`docs/draft-mcconnell-software-status-wellknown-00.md`](docs/draft-mcconnell-software-status-wellknown-00.md)
- **Plain text**: [`docs/draft-mcconnell-software-status-wellknown-00.txt`](docs/draft-mcconnell-software-status-wellknown-00.txt)

### GitHub Implementation Profile

A companion convention for open-source projects: publish `.github/software-status.json` in your repository to declare authoritative EOL dates for each release series. S3C-Tool already checks this file as part of its lookup chain.

- **Spec**: [`docs/github-implementation-profile.md`](docs/github-implementation-profile.md)

**Minimal example** (add to your repo at `.github/software-status.json`):
```json
{
  "schema_version": "1.0",
  "name": "Your Project",
  "vendor": "Your Org",
  "versions": [
    { "version": "2.0", "status": "active", "support_ends": null },
    { "version": "1.x", "status": "eol", "eol_date": "2024-12-31" }
  ]
}
```

---

## Self-Hosting

### Requirements

- WordPress site (shared hosting works — IONOS, SiteGround, etc.)
- MySQL 5.7+ / PHP 8.0+
- Raspberry Pi or Linux box for the research agent
- Python 3.9+ with `paramiko`, `anthropic`, `requests` on the Pi

### WordPress Plugin

1. Upload `wordpress-plugin/svrt/svrt.php` to `wp-content/plugins/svrt/`
2. Activate in WP Admin → Plugins
3. Add to `wp-config.php` or hosting environment:
   ```
   S3C_QUEUE_SECRET=<random-secret>
   S3C_ADMIN_TOKEN=<strong-token>
   ```
4. Point a cron trigger (UptimeRobot, external ping) at:
   `https://yoursite.com/wp-json/s3c/v1/process?secret=YOUR_SECRET`

### Research Agent (Pi)

```bash
git clone https://github.com/askmcconnell/s3c-tool ~/s3c
pip3 install anthropic paramiko requests pyyaml
```

Create `/home/pi/.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
NVD_API_KEY=<nvd-api-key>        # free at nvd.nist.gov/developers/request-an-api-key
SVRT_QUEUE_SECRET=<queue-secret>
WP_ADMIN_TOKEN=<admin-token>
WP_BASE=https://yoursite.com/wp-json/s3c/v1
IONOS_HOST=<sftp-host>
IONOS_USER=<sftp-user>
IONOS_PASS=<sftp-pass>
IONOS_REMOTE=/path/to/db/
```

Add crontabs:
```
0 */4 * * * flock -n /tmp/s3c_agent.lock bash -c 'cd ~/s3c && python3 agent/svrt_agent.py --max 500 >> logs/cron.log 2>&1'
0 */6 * * * flock -n /tmp/s3c_nvd.lock bash -c 'cd ~/s3c && python3 agent/svrt_agent.py --nvd-enrich --max 200 >> logs/nvd.log 2>&1'
*/5 * * * * curl -s "https://yoursite.com/wp-json/s3c/v1/process?secret=$SECRET" >> logs/wp_process.log 2>&1
0 3 * * * cd ~/s3c && bash sync/push_to_ionos.sh >> logs/sync.log 2>&1
```

### PWA

```bash
cd pwa
npm install
npm run dev        # local dev at localhost:5173
npm run build      # production build → dist/
```

Deploy `dist/` to your web server under `/s3c/`.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to:
- Add products to the YAML reference database (`reference-db/products/`)
- Report bugs or missing EOL data
- Propose changes to the `software-status.json` schema

Pull requests and schema feedback welcome.

---

## Privacy

- Hostnames are stored as one-way SHA-256 hashes — never transmitted or stored in plain text
- Only software metadata (name, vendor, version) is uploaded — no file contents, credentials, or user data
- Full details at [askmcconnell.com/s3c/privacy](https://askmcconnell.com/s3c/privacy)

---

## License

MIT — see [LICENSE](LICENSE)

---

*Built and maintained by [Jim McConnell](https://askmcconnell.com) · Ask McConnell, LLC*
