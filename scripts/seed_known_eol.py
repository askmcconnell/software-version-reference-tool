#!/usr/bin/env python3
"""
Seed well-known EOL/supported entries directly into the SVRT reference DB
via the WordPress import API.  Run on the Pi so it picks up WP_ADMIN_TOKEN
from /home/svrt/.env automatically.

Usage:  python3 seed_known_eol.py
"""

import os, json, hashlib, urllib.request, urllib.error
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────
env_file = Path.home() / '.env'
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, _, v = line.partition('=')
            os.environ.setdefault(k.strip(), v.strip())

TOKEN = os.environ.get('WP_ADMIN_TOKEN', '')
API   = 'https://askmcconnell.com/wp-json/svrt/v1/admin/reference/import'

if not TOKEN:
    print("ERROR: WP_ADMIN_TOKEN not set in ~/.env")
    raise SystemExit(1)

# ── Key builder (must match svrt_lookup_reference() in the plugin) ─────────────
def make_key(vendor: str, product: str, major: str) -> str:
    raw = f"{vendor.lower().strip()}:{product.lower().strip()}:{major}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16] + ':' + product.lower().strip()[:40]

# ── Known entries ──────────────────────────────────────────────────────────────
# Add every major-version variant that might appear in a real inventory.
# confidence=95 = manual/authoritative (highest non-community tier).

ENTRIES = [

    # ── Internet Explorer ──────────────────────────────────────────────────────
    # IE 11 on Win10: EOL Jun 15 2022.  IE 10 and below: EOL Jan 12 2016.
    *[{
        'lookup_key':        make_key('microsoft corporation', 'internet explorer', str(v)),
        'software_name':     'Internet Explorer',
        'vendor':            'Microsoft Corporation',
        'version':           str(v),
        'platform':          'windows',
        'eol_status':        'eol',
        'eol_date':          '2022-06-15' if v == 11 else '2016-01-12',
        'latest_version':    '',
        'latest_source_url': 'https://learn.microsoft.com/en-us/lifecycle/products/internet-explorer-11',
        'confidence':        95,
        'ref_source':        'manual',
        'notes':             f'IE{v} end of support {"June 15, 2022" if v == 11 else "January 12, 2016"}',
    } for v in [6, 7, 8, 9, 10, 11]],

    # ── Windows XP / Vista / 7 / 8 / 8.1 — all EOL ───────────────────────────
    {
        'lookup_key':        make_key('microsoft corporation', 'windows xp', '5'),
        'software_name':     'Windows XP',
        'vendor':            'Microsoft Corporation',
        'version':           '5',
        'platform':          'windows',
        'eol_status':        'eol',
        'eol_date':          '2014-04-08',
        'latest_version':    '',
        'latest_source_url': 'https://learn.microsoft.com/en-us/lifecycle/products/windows-xp',
        'confidence':        95,
        'ref_source':        'manual',
        'notes':             'Windows XP end of support April 8, 2014',
    },
    {
        'lookup_key':        make_key('microsoft corporation', 'windows vista', '6'),
        'software_name':     'Windows Vista',
        'vendor':            'Microsoft Corporation',
        'version':           '6',
        'platform':          'windows',
        'eol_status':        'eol',
        'eol_date':          '2017-04-11',
        'latest_version':    '',
        'latest_source_url': 'https://learn.microsoft.com/en-us/lifecycle/products/windows-vista',
        'confidence':        95,
        'ref_source':        'manual',
        'notes':             'Windows Vista end of support April 11, 2017',
    },
    {
        'lookup_key':        make_key('microsoft corporation', 'windows 7', '6'),
        'software_name':     'Windows 7',
        'vendor':            'Microsoft Corporation',
        'version':           '6',
        'platform':          'windows',
        'eol_status':        'eol',
        'eol_date':          '2020-01-14',
        'latest_version':    '',
        'latest_source_url': 'https://learn.microsoft.com/en-us/lifecycle/products/windows-7',
        'confidence':        95,
        'ref_source':        'manual',
        'notes':             'Windows 7 end of support January 14, 2020',
    },
    {
        'lookup_key':        make_key('microsoft corporation', 'windows 8', '6'),
        'software_name':     'Windows 8',
        'vendor':            'Microsoft Corporation',
        'version':           '6',
        'platform':          'windows',
        'eol_status':        'eol',
        'eol_date':          '2016-01-12',
        'latest_version':    '',
        'latest_source_url': 'https://learn.microsoft.com/en-us/lifecycle/products/windows-8',
        'confidence':        95,
        'ref_source':        'manual',
        'notes':             'Windows 8 end of support January 12, 2016',
    },
    {
        'lookup_key':        make_key('microsoft corporation', 'windows 8.1', '6'),
        'software_name':     'Windows 8.1',
        'vendor':            'Microsoft Corporation',
        'version':           '6',
        'platform':          'windows',
        'eol_status':        'eol',
        'eol_date':          '2023-01-10',
        'latest_version':    '',
        'latest_source_url': 'https://learn.microsoft.com/en-us/lifecycle/products/windows-81',
        'confidence':        95,
        'ref_source':        'manual',
        'notes':             'Windows 8.1 end of support January 10, 2023',
    },

    # ── Google Chrome — supported, evergreen ──────────────────────────────────
    *[{
        'lookup_key':        make_key('google llc', 'google chrome', str(v)),
        'software_name':     'Google Chrome',
        'vendor':            'Google LLC',
        'version':           str(v),
        'platform':          'windows',
        'eol_status':        'supported',
        'eol_date':          '',
        'latest_version':    '134',
        'latest_source_url': 'https://chromereleases.googleblog.com/',
        'confidence':        85,
        'ref_source':        'manual',
        'notes':             'Chrome is evergreen — auto-updates, no fixed EOL',
    } for v in range(80, 135)],

    # ── Microsoft Edge — supported, evergreen ─────────────────────────────────
    *[{
        'lookup_key':        make_key('microsoft corporation', 'microsoft edge', str(v)),
        'software_name':     'Microsoft Edge',
        'vendor':            'Microsoft Corporation',
        'version':           str(v),
        'platform':          'windows',
        'eol_status':        'supported',
        'eol_date':          '',
        'latest_version':    '134',
        'latest_source_url': 'https://learn.microsoft.com/en-us/deployedge/microsoft-edge-support-lifecycle',
        'confidence':        85,
        'ref_source':        'manual',
        'notes':             'Edge is evergreen — auto-updates, no fixed EOL',
    } for v in range(80, 135)],

    # ── Norton 360 / Norton Antivirus — supported ─────────────────────────────
    *[{
        'lookup_key':        make_key('gen digital inc.', name, ''),
        'software_name':     name,
        'vendor':            'Gen Digital Inc.',
        'version':           '',
        'platform':          'windows',
        'eol_status':        'supported',
        'eol_date':          '',
        'latest_version':    '24.0',
        'latest_source_url': 'https://support.norton.com/',
        'confidence':        80,
        'ref_source':        'manual',
        'notes':             'Subscription-based; supported while subscription active',
    } for name in ['Norton 360', 'Norton Antivirus', 'Norton Security', 'Norton Internet Security']],

    # ── Firefox — supported (ESR available, regular releases every 4 weeks) ───
    *[{
        'lookup_key':        make_key('mozilla', 'firefox', str(v)),
        'software_name':     'Firefox',
        'vendor':            'Mozilla',
        'version':           str(v),
        'platform':          'windows',
        'eol_status':        'eol' if v < 115 else 'supported',
        'eol_date':          '' if v >= 115 else '2023-07-01',
        'latest_version':    '136.0',
        'latest_source_url': 'https://www.mozilla.org/en-US/firefox/releases/',
        'confidence':        85,
        'ref_source':        'manual',
        'notes':             'Firefox 115 ESR is oldest supported; v136 is current stable',
    } for v in range(50, 137)],

    # ── Apple macOS apps (bundled — supported with OS) ────────────────────────
    # latest_version reflects the version shipped with macOS Sequoia 15.x
    *[{
        'lookup_key':        make_key('apple inc.', name, ''),
        'software_name':     name,
        'vendor':            'Apple Inc.',
        'version':           '',
        'platform':          'macos',
        'eol_status':        'supported',
        'eol_date':          '',
        'latest_version':    latest,
        'latest_source_url': 'https://support.apple.com/en-us/111900',
        'confidence':        80,
        'ref_source':        'manual',
        'notes':             'Bundled macOS app — supported with current macOS release',
    } for name, latest in [
        ('Automator',         '2.10'),
        ('Numbers',           '14.3'),
        ('Shortcuts',         '6.0'),
        ('Pages',             '14.3'),
        ('Keynote',           '14.3'),
        ('Preview',           '11.0'),
        ('Safari',            '18.3'),
        ('Mail',              '18.0'),
        ('Calendar',          '14.0'),
        ('Contacts',          '15.0'),
        ('Maps',              '7.0'),
        ('Photos',            '10.0'),
        ('GarageBand',        '10.4.11'),
        ('iMovie',            '10.4.4'),
        ('TextEdit',          '1.19'),
        ('Terminal',          '2.14'),
        ('Activity Monitor',  '10.14'),
        ('Disk Utility',      '21.0'),
        ('System Preferences','15.0'),
        ('System Settings',   '15.0'),
    ]],

]

# ── Push to WordPress ──────────────────────────────────────────────────────────
print(f"Seeding {len(ENTRIES)} entries to {API}...")

body = json.dumps(ENTRIES).encode()
req  = urllib.request.Request(API, data=body, headers={
    'Content-Type':  'application/json',
    'Authorization': f'Bearer {TOKEN}',
})

try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
    print(f"✓ Imported: {result.get('imported', 0)}  Skipped: {result.get('skipped', 0)}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"✗ HTTP {e.code}: {body}")
except Exception as e:
    print(f"✗ Error: {e}")
