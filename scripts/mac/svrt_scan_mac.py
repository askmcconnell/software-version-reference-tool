#!/usr/bin/env python3
"""
SVRT Mac File-Level Inventory Scanner
Ask McConnell's Software Version Reference Tool
Version: 1.0.0

Scans at the FILE level — not just Applications folder or system_profiler.
Captures: executables, frameworks, dylibs, Python/Node packages, CLI tools.

Output: svrt_inventory_HOSTNAME_DATE.csv  (upload to askmcconnell.com/svrt)

Usage:
    python3 svrt_scan_mac.py
    python3 svrt_scan_mac.py --output /path/to/output.csv
    python3 svrt_scan_mac.py --quick   # apps + CLI only, skip deep file scan
"""

import os, sys, csv, json, re, subprocess, hashlib, argparse, plistlib
from datetime import date, datetime
from pathlib import Path

# ── Output CSV columns (matches SVRT reference DB schema) ─────────────────────
FIELDNAMES = [
    'svrt_format_version',
    'scan_date',
    'hostname_hash',       # sha256 of hostname (privacy)
    'platform',
    'arch',
    'os_version',
    'filename',
    'filepath',
    'software_name',
    'vendor',
    'version',
    'file_version',        # may differ from product version
    'file_size_bytes',
    'file_type',           # app | framework | dylib | binary | script | package
    'parent_app',          # if inside a bundle
    'install_date',
    'source',              # how version was found: plist | cli | binary_header | package_db
]

SVRT_FORMAT_VERSION = '1.0'
TODAY = date.today().isoformat()

# ── Helpers ────────────────────────────────────────────────────────────────────
def hash_hostname():
    try:
        h = subprocess.run(['hostname'], capture_output=True, text=True).stdout.strip()
    except:
        h = 'unknown'
    return hashlib.sha256(h.encode()).hexdigest()[:16]

def get_arch():
    try:
        return subprocess.run(['uname', '-m'], capture_output=True, text=True).stdout.strip()
    except:
        return 'unknown'

def get_os_version():
    try:
        r = subprocess.run(['sw_vers', '-productVersion'], capture_output=True, text=True)
        return r.stdout.strip()
    except:
        return 'unknown'

def read_plist_safe(path):
    try:
        with open(path, 'rb') as f:
            return plistlib.load(f)
    except:
        return {}

# Binaries that must never be probed with --version:
#   GUI launchers  → open windows (jconsole, wish, osascript)
#   Keychain tools → trigger Passwords/security prompt (security, certtool, codesign)
#   Interactive REPLs → hang waiting for input (ftp, sftp, whois, bc, dc, telnet)
#   Destructive/dangerous system tools → never run with unknown flags
SKIP_VERSION_PROBE = {
    # Java GUI
    'java', 'javaws', 'jconsole', 'jvisualvm', 'appletviewer',
    # Tcl/Tk — opens a blank window
    'wish', 'wish8.6', 'wish8.5', 'tclsh', 'tclsh8.6',
    # macOS keychain / security — triggers Passwords app or auth dialog
    'security', 'certtool', 'codesign', 'spctl', 'pkgutil',
    'systemkeychain', 'login-keychain',
    # Interactive REPLs — wait for stdin, never return
    'ftp', 'sftp', 'telnet', 'nc', 'netcat', 'whois',
    'bc', 'dc', 'ed', 'ex', 'vi', 'vim', 'nano', 'pico', 'emacs',
    'python', 'python2', 'python3', 'ruby', 'irb', 'perl', 'php',
    'node', 'nodejs', 'lua', 'tclsh', 'rlwrap',
    # Shell / system tools that may prompt or cause side effects
    'su', 'sudo', 'login', 'passwd', 'chsh', 'newgrp',
    'osascript', 'open', 'launchctl',
    # Disk / filesystem — never probe
    'fsck', 'fsck_hfs', 'fsck_apfs', 'newfs', 'mount', 'umount', 'diskutil',
    'fdisk', 'pdisk', 'gpt',
    # Network daemons
    'sshd', 'httpd', 'ftpd', 'named', 'ntpd', 'sendmail', 'postfix',
}

def run_version_flag(binary):
    """Try --version and -version; return first line of output.
    Skips known GUI launchers, interactive REPLs, and keychain tools.
    """
    name = os.path.basename(binary).lower()
    # Strip numeric suffixes for matching (e.g. python3.11 → python3)
    name_base = re.sub(r'[\d.]+$', '', name)
    if name in SKIP_VERSION_PROBE or name_base in SKIP_VERSION_PROBE:
        return None

    for flag in ['--version', '-version']:
        try:
            r = subprocess.run(
                [binary, flag],
                capture_output=True, text=True, timeout=3,
                env={**os.environ, 'LANG': 'C', 'TERM': 'dumb'},
                # Ensure no window can be created — close stdin
                stdin=subprocess.DEVNULL,
            )
            out = (r.stdout or r.stderr or '').strip()
            if out and any(c.isdigit() for c in out):
                return out.split('\n')[0][:120]
        except Exception:
            pass
    return None

def extract_version_from_string(s):
    """Pull first semver-like string from a line of text."""
    if not s:
        return None
    m = re.search(r'(\d+\.\d+[\.\d\-a-zA-Z+]*)', str(s))
    return m.group(1)[:50] if m else None

def file_mtime_date(path):
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).date().isoformat()
    except:
        return ''

def file_size(path):
    try:
        return os.path.getsize(path)
    except:
        return 0

def make_row(base, **overrides):
    row = dict(base)
    row.update(overrides)
    return row

# ── Scanners ───────────────────────────────────────────────────────────────────

def scan_applications(base_row, rows, quick=False):
    """Scan .app bundles in /Applications, ~/Applications, /System/Applications."""
    print("  Scanning .app bundles...", flush=True)
    app_dirs = [
        '/Applications',
        os.path.expanduser('~/Applications'),
        '/System/Applications',
    ]
    for app_dir in app_dirs:
        if not os.path.isdir(app_dir):
            continue
        for item in sorted(os.listdir(app_dir)):
            if not item.endswith('.app'):
                continue
            app_path = os.path.join(app_dir, item)
            info = read_plist_safe(os.path.join(app_path, 'Contents', 'Info.plist'))
            version = (info.get('CFBundleShortVersionString') or
                       info.get('CFBundleVersion') or '')
            name    = info.get('CFBundleName') or item.replace('.app','')
            bid     = info.get('CFBundleIdentifier','')
            vendor  = derive_vendor(bid, info.get('NSHumanReadableCopyright',''), item)
            # Main binary
            macos_dir = os.path.join(app_path, 'Contents', 'MacOS')
            bin_file  = item.replace('.app','')
            bin_path  = os.path.join(macos_dir, bin_file)
            if not os.path.exists(bin_path) and os.path.isdir(macos_dir):
                bins = os.listdir(macos_dir)
                if bins:
                    bin_file = bins[0]
                    bin_path = os.path.join(macos_dir, bin_file)

            rows.append(make_row(base_row,
                filename=item,
                filepath=app_path,
                software_name=name,
                vendor=vendor,
                version=version,
                file_version=info.get('CFBundleVersion',''),
                file_size_bytes=file_size(bin_path) if os.path.exists(bin_path) else 0,
                file_type='app',
                parent_app='',
                install_date=file_mtime_date(app_path),
                source='plist',
            ))

            if not quick:
                # Scan bundled frameworks within this app
                scan_bundled_frameworks(app_path, item.replace('.app',''), base_row, rows)


def scan_bundled_frameworks(app_path, parent_name, base_row, rows):
    """Scan .framework bundles inside a .app bundle."""
    fw_dir = os.path.join(app_path, 'Contents', 'Frameworks')
    if not os.path.isdir(fw_dir):
        return
    for item in os.listdir(fw_dir):
        if not item.endswith('.framework'):
            continue
        fw_path = os.path.join(fw_dir, item)
        # Find plist
        info = {}
        for plist_candidate in [
            os.path.join(fw_path, 'Resources', 'Info.plist'),
            os.path.join(fw_path, 'Versions', 'A', 'Resources', 'Info.plist'),
            os.path.join(fw_path, 'Info.plist'),
        ]:
            if os.path.exists(plist_candidate):
                info = read_plist_safe(plist_candidate)
                break

        version = info.get('CFBundleShortVersionString') or info.get('CFBundleVersion') or ''
        name    = info.get('CFBundleName') or item.replace('.framework','')
        bid     = info.get('CFBundleIdentifier','')
        vendor  = derive_vendor(bid, info.get('NSHumanReadableCopyright',''), item)

        rows.append(make_row(base_row,
            filename=item,
            filepath=fw_path,
            software_name=name,
            vendor=vendor,
            version=version,
            file_version=info.get('CFBundleVersion',''),
            file_size_bytes=file_size(fw_path),
            file_type='framework',
            parent_app=parent_name,
            install_date=file_mtime_date(fw_path),
            source='plist',
        ))

        # Also catch .dylib files directly in Frameworks dir
        if item.endswith('.dylib'):
            rows.append(make_row(base_row,
                filename=item,
                filepath=fw_path,
                software_name=item,
                vendor=parent_name,
                version='',
                file_version='',
                file_size_bytes=file_size(fw_path),
                file_type='dylib',
                parent_app=parent_name,
                install_date=file_mtime_date(fw_path),
                source='filesystem',
            ))


def scan_cli_binaries(base_row, rows):
    """Scan executables in standard CLI paths and get versions."""
    print("  Scanning CLI binaries...", flush=True)
    scan_paths = [
        '/usr/bin', '/usr/sbin', '/usr/local/bin', '/usr/local/sbin',
        '/opt/homebrew/bin', '/opt/homebrew/sbin',
        '/opt/local/bin',   # MacPorts
        os.path.expanduser('~/.local/bin'),
    ]
    seen = set()
    for scan_dir in scan_paths:
        if not os.path.isdir(scan_dir):
            continue
        for fname in sorted(os.listdir(scan_dir)):
            fpath = os.path.join(scan_dir, fname)
            if fpath in seen or not os.path.isfile(fpath):
                continue
            # Skip obvious non-executables
            if '.' in fname and not fname.endswith(('.py','.sh','.rb','.pl')):
                continue
            seen.add(fpath)
            ver_line = run_version_flag(fpath)
            version  = extract_version_from_string(ver_line)

            rows.append(make_row(base_row,
                filename=fname,
                filepath=fpath,
                software_name=fname,
                vendor=get_bin_vendor(fname),
                version=version or '',
                file_version='',
                file_size_bytes=file_size(fpath),
                file_type='binary',
                parent_app='',
                install_date=file_mtime_date(fpath),
                source='cli' if version else 'filesystem',
            ))


def scan_python_packages(base_row, rows):
    """Enumerate installed Python packages via pip."""
    print("  Scanning Python packages...", flush=True)
    for pip_cmd in ['pip3', 'pip']:
        try:
            r = subprocess.run([pip_cmd, 'list', '--format=json'],
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and r.stdout:
                pkgs = json.loads(r.stdout)
                for pkg in pkgs:
                    rows.append(make_row(base_row,
                        filename=pkg['name'],
                        filepath=f'python:{pip_cmd}',
                        software_name=pkg['name'],
                        vendor='PyPI',
                        version=pkg.get('version',''),
                        file_version='',
                        file_size_bytes=0,
                        file_type='package',
                        parent_app='Python',
                        install_date='',
                        source='package_db',
                    ))
                return  # success, stop trying
        except:
            pass


def scan_homebrew(base_row, rows):
    """Enumerate Homebrew packages."""
    print("  Scanning Homebrew packages...", flush=True)
    brew = '/opt/homebrew/bin/brew' if os.path.exists('/opt/homebrew/bin/brew') else 'brew'
    try:
        r = subprocess.run([brew, 'list', '--versions'],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return
        for line in r.stdout.strip().split('\n'):
            parts = line.split()
            if len(parts) >= 2:
                name    = parts[0]
                version = parts[-1]
                rows.append(make_row(base_row,
                    filename=name,
                    filepath=f'/opt/homebrew/Cellar/{name}/{version}',
                    software_name=name,
                    vendor='Homebrew/Open Source',
                    version=version,
                    file_version='',
                    file_size_bytes=0,
                    file_type='package',
                    parent_app='Homebrew',
                    install_date='',
                    source='package_db',
                ))
    except:
        pass


def scan_node_packages(base_row, rows):
    """Enumerate globally installed npm packages."""
    print("  Scanning npm global packages...", flush=True)
    try:
        r = subprocess.run(['npm', 'list', '-g', '--json', '--depth=0'],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout:
            data = json.loads(r.stdout)
            for name, info in (data.get('dependencies') or {}).items():
                rows.append(make_row(base_row,
                    filename=name,
                    filepath=f'npm:global',
                    software_name=name,
                    vendor='npm',
                    version=info.get('version',''),
                    file_version='',
                    file_size_bytes=0,
                    file_type='package',
                    parent_app='Node.js',
                    install_date='',
                    source='package_db',
                ))
    except:
        pass


def scan_system_frameworks(base_row, rows):
    """Scan /Library/Frameworks and ~/Library/Frameworks for third-party frameworks."""
    print("  Scanning system frameworks...", flush=True)
    fw_dirs = [
        '/Library/Frameworks',
        os.path.expanduser('~/Library/Frameworks'),
    ]
    for fw_dir in fw_dirs:
        if not os.path.isdir(fw_dir):
            continue
        for item in sorted(os.listdir(fw_dir)):
            if not item.endswith('.framework'):
                continue
            fw_path = os.path.join(fw_dir, item)
            info = {}
            for candidate in [
                os.path.join(fw_path, 'Resources', 'Info.plist'),
                os.path.join(fw_path, 'Versions', 'A', 'Resources', 'Info.plist'),
            ]:
                if os.path.exists(candidate):
                    info = read_plist_safe(candidate)
                    break
            version = info.get('CFBundleShortVersionString') or info.get('CFBundleVersion') or ''
            name    = info.get('CFBundleName') or item.replace('.framework','')
            vendor  = derive_vendor(info.get('CFBundleIdentifier',''),
                                    info.get('NSHumanReadableCopyright',''), item)
            rows.append(make_row(base_row,
                filename=item,
                filepath=fw_path,
                software_name=name,
                vendor=vendor,
                version=version,
                file_version=info.get('CFBundleVersion',''),
                file_size_bytes=file_size(fw_path),
                file_type='framework',
                parent_app='',
                install_date=file_mtime_date(fw_path),
                source='plist',
            ))


# ── Vendor derivation ─────────────────────────────────────────────────────────
def derive_vendor(bundle_id, copyright, name):
    bid = bundle_id.lower()
    mapping = {
        'com.apple':     'Apple Inc.',
        'com.microsoft': 'Microsoft Corporation',
        'com.adobe':     'Adobe Inc.',
        'com.google':    'Google LLC',
        'org.mozilla':   'Mozilla Foundation',
        'com.mozilla':   'Mozilla Foundation',
        'com.electron':  'Electron / Open Source',
        'com.github':    'GitHub Inc.',
        'com.zoom':      'Zoom Video Communications',
        'com.slack':     'Slack Technologies',
        'com.discord':   'Discord Inc.',
        'com.dropbox':   'Dropbox Inc.',
        'com.jetbrains': 'JetBrains s.r.o.',
        'com.oracle':    'Oracle Corporation',
        'com.vmware':    'VMware Inc.',
        'com.cisco':     'Cisco Systems',
        'com.brother':   'Brother Industries',
        'com.canon':     'Canon Inc.',
        'com.epson':     'Seiko Epson Corporation',
    }
    for prefix, vendor in mapping.items():
        if bid.startswith(prefix):
            return vendor
    if copyright:
        c = re.sub(r'Copyright\s*©?\s*\d{4}[\-\d,\s]*', '', copyright).strip()
        if c:
            return c[:80]
    return ''

def get_bin_vendor(binary):
    known = {
        'python3':'Python Software Foundation','python':'Python Software Foundation',
        'ruby':'Ruby Community','perl':'Perl Foundation','php':'PHP Group',
        'node':'Node.js Foundation','npm':'npm Inc.','git':'Git SCM',
        'curl':'curl project','ssh':'OpenSSH','openssl':'OpenSSL/Apple',
        'bash':'GNU Project / Apple','zsh':'Zsh Community',
        'java':'Oracle / OpenJDK','go':'Google LLC','rustc':'Rust Foundation',
    }
    return known.get(binary.lower(), '')


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='SVRT Mac File-Level Scanner')
    parser.add_argument('--output', '-o', help='Output CSV path')
    parser.add_argument('--quick', action='store_true',
                        help='Quick scan: apps + CLI only, skip bundled frameworks')
    args = parser.parse_args()

    hostname_hash = hash_hostname()
    arch          = get_arch()
    os_version    = get_os_version()

    output_path = args.output or os.path.expanduser(
        f'~/Desktop/svrt_inventory_mac_{date.today().isoformat()}.csv'
    )

    base_row = {
        'svrt_format_version': SVRT_FORMAT_VERSION,
        'scan_date':           TODAY,
        'hostname_hash':       hostname_hash,
        'platform':            'macos',
        'arch':                arch,
        'os_version':          os_version,
        'filename':            '',
        'filepath':            '',
        'software_name':       '',
        'vendor':              '',
        'version':             '',
        'file_version':        '',
        'file_size_bytes':     0,
        'file_type':           '',
        'parent_app':          '',
        'install_date':        '',
        'source':              '',
    }

    rows = []
    print(f"SVRT Mac Scanner — {TODAY}", flush=True)
    print(f"  Platform : macOS {os_version} ({arch})", flush=True)
    print(f"  Host hash: {hostname_hash}", flush=True)
    print(f"  Output   : {output_path}", flush=True)
    print(f"  Mode     : {'Quick' if args.quick else 'Full'}", flush=True)
    print()

    scan_applications(base_row, rows, quick=args.quick)
    print(f"  Apps found: {len(rows)}", flush=True)

    pre = len(rows)
    scan_cli_binaries(base_row, rows)
    print(f"  CLI binaries found: {len(rows)-pre}", flush=True)

    pre = len(rows)
    scan_system_frameworks(base_row, rows)
    print(f"  System frameworks found: {len(rows)-pre}", flush=True)

    pre = len(rows)
    scan_python_packages(base_row, rows)
    print(f"  Python packages found: {len(rows)-pre}", flush=True)

    pre = len(rows)
    scan_homebrew(base_row, rows)
    print(f"  Homebrew packages found: {len(rows)-pre}", flush=True)

    pre = len(rows)
    scan_node_packages(base_row, rows)
    print(f"  npm global packages found: {len(rows)-pre}", flush=True)

    print(f"\n  Total rows: {len(rows)}", flush=True)
    print(f"  Writing CSV...", flush=True)

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    size_kb = os.path.getsize(output_path) // 1024
    print(f"  Done — {output_path} ({size_kb} KB, {len(rows)} rows)", flush=True)
    print(f"\n  Upload to: https://askmcconnell.com/svrt", flush=True)

if __name__ == '__main__':
    main()
