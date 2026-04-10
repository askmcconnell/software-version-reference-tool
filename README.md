# SVRT — Software Version Reference Tool

A self-hosted SaaS tool that scans real machine inventories, detects end-of-life (EOL) and outdated software, and delivers actionable security reports — powered by a shared AI-enriched reference database.

**Live instance**: [askmcconnell.com/svrt](https://askmcconnell.com/svrt/)

---

## What It Does

1. **Scan** — run a lightweight scanner on Windows, Mac, or Linux endpoints
2. **Upload** — drag-drop the CSV into the web app
3. **Report** — get a color-coded EOL/outdated/supported breakdown per product
4. **Share** — every resolved product is cached in a shared reference DB, benefiting all users

Software status categories:
- **EOL** — end of life, no longer patched
- **Outdated** — supported but not on the latest version
- **No Patch** — known vulnerability, no fix available
- **LTS** — long-term support release
- **Supported** — current and patched

---

## Architecture

```
┌─────────────────────────────────────────────┐
│  React PWA (Vite)                           │
│  askmcconnell.com/svrt/                     │
└──────────────────┬──────────────────────────┘
                   │ REST /wp-json/svrt/v1/
┌──────────────────▼──────────────────────────┐
│  WordPress Plugin (PHP)                     │
│  MySQL: subscribers, jobs, inventory,       │
│         reference DB                        │
└──────────────────┬──────────────────────────┘
                   │ nightly SFTP sync
┌──────────────────▼──────────────────────────┐
│  Raspberry Pi Research Agent (Python)       │
│  SQLite local cache                         │
│  Lookup chain:                              │
│    1. Local SQLite                          │
│    2. endoflife.date API                    │
│    3. Claude Haiku (AI fallback)            │
└─────────────────────────────────────────────┘
```

---

## Repository Structure

```
agent/                  Raspberry Pi research agent
  svrt_agent.py         Main agent — lookup chain + queue processing

pwa/                    React/Vite frontend (PWA)
  src/
    api/                WordPress REST API client
    components/         Reusable UI components
    contexts/           Auth context
    pages/              All page-level components
    styles/             Global CSS custom properties

scripts/                Scanner scripts (run on endpoints)
  mac/svrt_scan_mac.py
  linux/svrt_scan_linux.py
  windows/svrt_scan_windows.ps1
  seed_known_eol.py     Seed well-known EOL products into the reference DB

sync/
  push_to_ionos.sh      Nightly Pi → IONOS sync + two-way unknown-software pull

pi-dashboard/
  status.py             Pi monitoring dashboard (queue stats, API cost tracking)

wordpress-plugin/
  svrt/svrt.php         WordPress plugin — REST API, job processing, reference DB

reference-db/           (planned) Community-curated YAML product definitions
```

---

## Scanner Quick Start

Download and run the scanner for your platform:

**Mac**
```bash
curl -O https://askmcconnell.com/svrt/scanners/svrt_scan_mac.py
python3 svrt_scan_mac.py
```

**Linux**
```bash
curl -O https://askmcconnell.com/svrt/scanners/svrt_scan_linux.py
python3 svrt_scan_linux.py
```

**Windows** (PowerShell, run as Administrator)
```powershell
Invoke-WebRequest https://askmcconnell.com/svrt/scanners/svrt_scan_windows.ps1 -OutFile svrt_scan.ps1
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\svrt_scan.ps1
```

Upload the resulting CSV at [askmcconnell.com/svrt](https://askmcconnell.com/svrt/).

---

## Self-Hosting

### Requirements

- WordPress site (any shared host)
- MySQL 5.7+
- PHP 7.4+
- Raspberry Pi (or any Linux box) for the research agent
- Python 3.9+ with `paramiko`, `anthropic` packages on the Pi
- UptimeRobot (free) for cron — IONOS and most shared hosts don't allow real crontabs

### WordPress Plugin Setup

1. Upload `wordpress-plugin/svrt/svrt.php` to `wp-content/plugins/svrt/`
2. Activate in WP Admin → Plugins
3. Set environment variables in your hosting panel (or `wp-config.php`):
   - `SVRT_QUEUE_SECRET` — random secret for the `/process` UptimeRobot cron endpoint
   - `SVRT_ADMIN_TOKEN` — strong token for Pi → WordPress API pushes
4. Point UptimeRobot at: `https://yoursite.com/wp-json/svrt/v1/process?secret=YOUR_SECRET`

### Research Agent (Pi) Setup

```bash
git clone https://github.com/YOUR_USERNAME/svrt.git ~/svrt
pip3 install anthropic paramiko requests
cp ~/svrt/agent/svrt_agent.py ~/svrt/agent/
```

Create `~/.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
WP_ADMIN_TOKEN=your-admin-token
WP_BASE=https://yoursite.com/wp-json/svrt/v1
WP_PROCESS_SECRET=your-queue-secret
IONOS_HOST=your-sftp-host
IONOS_USER=your-sftp-user
IONOS_PASS=your-sftp-pass
```

Add crontabs:
```
0 2 * * * cd /home/svrt/svrt && python3 agent/svrt_agent.py --run >> logs/agent.log 2>&1
30 2 * * * cd /home/svrt/svrt && bash sync/push_to_ionos.sh >> logs/sync.log 2>&1
```

### PWA Setup

```bash
cd pwa
npm install
npm run dev          # local dev
npm run build        # production build → dist/
```

Deploy `dist/` to your web server's SVRT subdirectory.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add products to the reference database, fix bugs, or propose new features.

---

## Privacy

- Hostnames are stored as one-way SHA-256 hashes — the original hostname is never transmitted or stored
- Only software metadata (name, vendor, version) is uploaded — no file contents, user data, or credentials
- See the [Privacy Architecture](docs/privacy.md) for full details

---

## License

MIT — see [LICENSE](LICENSE)
