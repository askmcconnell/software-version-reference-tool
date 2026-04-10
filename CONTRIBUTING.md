# Contributing to SVRT

Thank you for helping improve the Software Version Reference Tool. Contributions are welcome in several forms — you don't need to write code to contribute.

---

## Ways to Contribute

### 1. Add Products to the Reference Database (no code required)

The `reference-db/` directory contains YAML files, one per software product, that define EOL/support status. These are ingested by the Pi research agent at 90-confidence — higher than AI guesses, lower than manual authoritative entries.

To add or correct a product:

1. Fork this repo
2. Create or edit a YAML file in `reference-db/products/` (see format below)
3. Open a pull request — include a source URL

**YAML format** (`reference-db/products/microsoft-office-365.yaml`):
```yaml
software_name: Microsoft 365
vendor: Microsoft Corporation
platform: windows        # windows | macos | linux | cross-platform
versions:
  - major: "2016"
    eol_status: eol
    eol_date: "2025-10-14"
    source_url: https://learn.microsoft.com/en-us/lifecycle/products/microsoft-office-2016
  - major: "2019"
    eol_status: supported
    eol_date: "2025-10-14"
    latest_version: "16.0"
    source_url: https://learn.microsoft.com/en-us/lifecycle/products/microsoft-office-2019
notes: Mainstream support ends Oct 2025 for Office 2019
```

Required fields: `software_name`, `vendor`, `platform`, `versions[].major`, `versions[].eol_status`, `versions[].source_url`

### 2. Improve the Research Agent

The Pi agent (`agent/svrt_agent.py`) handles the lookup chain. Good contributions:
- Better version normalization for edge cases
- New data sources (manufacturer lifecycle pages, other APIs)
- Improved Claude prompt engineering for accuracy

### 3. Fix Bugs or Add Features

Check open issues for `good first issue` tags. For larger changes, open an issue first to discuss the approach.

### 4. Improve the Scanner Scripts

Scripts in `scripts/` run on endpoints. Good contributions:
- Better detection of software in non-standard install locations
- Firmware detection (BIOS, network device firmware)
- Windows Package Manager (winget) integration
- Homebrew package list integration for Mac

---

## Development Setup

### PWA (frontend)
```bash
cd pwa
npm install
npm run dev
```

The PWA expects a WordPress backend running at `https://askmcconnell.com` by default. To point at your own instance, set `VITE_WP_BASE` in `pwa/.env.local`:
```
VITE_WP_BASE=https://your-wordpress-site.com/wp-json/svrt/v1
```

### Research Agent (Pi or any Linux box)
```bash
pip3 install anthropic paramiko requests
cp .env.example .env   # fill in your keys
python3 agent/svrt_agent.py --status
python3 agent/svrt_agent.py --run
```

---

## Code Style

- Python: PEP 8, f-strings, type hints on public functions
- PHP: WordPress coding standards
- JavaScript/JSX: plain JS (no TypeScript), functional components, no external UI libraries
- No AI-generated code submitted without human review

---

## Pull Request Checklist

- [ ] Source URL included for any EOL data
- [ ] No credentials or real hostnames in the diff
- [ ] Scanner changes tested on the target platform
- [ ] YAML validated (run `python3 reference-db/validate.py` once available)

---

## Reporting Issues

Open a GitHub issue with:
- Platform (Windows / Mac / Linux)
- Software name and version that was misidentified
- What SVRT reported vs. what the correct status is
- Source URL for the correct information

---

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
