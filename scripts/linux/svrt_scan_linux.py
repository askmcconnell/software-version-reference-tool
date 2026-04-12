#!/usr/bin/env python3
"""
SVRT Linux File-Level Inventory Scanner
Ask McConnell's Software Version Reference Tool
Version: 1.0.0

Scans at the FILE level — dpkg/rpm packages, binary executables, shared
libraries, snap/flatpak, Python packages, Node global packages.

Output: svrt_inventory_linux_HOSTNAME_DATE.csv  (upload to askmcconnell.com/svrt)

Supports: Debian/Ubuntu (dpkg), RHEL/Fedora/CentOS (rpm), Arch (pacman),
          Alpine (apk), any distro (binary + ELF scanning)

Usage:
    python3 svrt_scan_linux.py
    python3 svrt_scan_linux.py --output /path/to/output.csv
    python3 svrt_scan_linux.py --quick        # packages + CLI only, skip .so scan
    python3 svrt_scan_linux.py --no-so        # skip shared library deep scan
    python3 svrt_scan_linux.py --no-snap      # skip snap/flatpak
"""

import os, sys, csv, json, re, subprocess, hashlib, argparse, struct
from datetime import date, datetime
from pathlib import Path

# ── Output CSV columns (matches SVRT reference DB schema v1.0) ─────────────────
FIELDNAMES = [
    'svrt_format_version',
    'scan_date',
    'hostname_hash',       # sha256 of hostname, first 16 chars (privacy)
    'platform',
    'arch',
    'os_version',
    'filename',
    'filepath',
    'software_name',
    'vendor',
    'version',
    'file_version',        # may differ from package version
    'file_size_bytes',
    'file_type',           # package | binary | library | script | snap | flatpak
    'parent_app',          # package name if binary/lib is from a package
    'install_date',
    'source',              # dpkg | rpm | pacman | apk | cli | elf_header | pip | npm | snap | flatpak
]

SVRT_FORMAT_VERSION = '1.0'
TODAY = date.today().isoformat()

# ── Helpers ────────────────────────────────────────────────────────────────────

def hash_hostname():
    try:
        h = subprocess.run(['hostname'], capture_output=True, text=True).stdout.strip()
    except Exception:
        h = 'unknown'
    return hashlib.sha256(h.encode()).hexdigest()[:16]

def get_arch():
    try:
        return subprocess.run(['uname', '-m'], capture_output=True, text=True).stdout.strip()
    except Exception:
        return 'unknown'

def get_os_version():
    """Return pretty OS version string from /etc/os-release."""
    release_file = '/etc/os-release'
    if os.path.exists(release_file):
        data = {}
        try:
            with open(release_file) as f:
                for line in f:
                    line = line.strip()
                    if '=' in line:
                        k, _, v = line.partition('=')
                        data[k.strip()] = v.strip().strip('"')
        except Exception:
            pass
        pretty = data.get('PRETTY_NAME') or data.get('NAME', '')
        version = data.get('VERSION_ID', '')
        if pretty:
            return pretty
        if version:
            return f"{data.get('NAME', 'Linux')} {version}"
    # Fallback: uname -r
    try:
        return subprocess.run(['uname', '-r'], capture_output=True, text=True).stdout.strip()
    except Exception:
        return 'linux'

def run_cmd(cmd, timeout=5):
    """Run a command, return stdout string or empty string on failure."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ''

def run_version_flag(binary):
    """Try common version flags; return first meaningful line."""
    for flag in ['--version', '-version', '-v', 'version', '--Version']:
        try:
            r = subprocess.run(
                [binary, flag], capture_output=True, text=True, timeout=4,
                env={**os.environ, 'LANG': 'C'}
            )
            out = (r.stdout or r.stderr or '').strip()
            if out:
                first = out.split('\n')[0][:120]
                if any(c.isdigit() for c in first):
                    return first
        except Exception:
            pass
    return None

def extract_version(s):
    """Pull first semver-like string from a line of text."""
    if not s:
        return None
    m = re.search(r'(\d+\.\d+[\.\d\-+~a-zA-Z]*)', str(s))
    return m.group(1)[:50] if m else None

def file_mtime_date(path):
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).date().isoformat()
    except Exception:
        return ''

def file_size(path):
    try:
        return os.path.getsize(path)
    except Exception:
        return 0

def is_elf(path):
    """Quick check: does the file start with ELF magic bytes?"""
    try:
        with open(path, 'rb') as f:
            return f.read(4) == b'\x7fELF'
    except Exception:
        return False

def is_executable_script(path):
    """Check for shebang line in a file."""
    try:
        with open(path, 'rb') as f:
            return f.read(2) == b'#!'
    except Exception:
        return False

def make_row(base, **overrides):
    row = dict(base)
    row.update(overrides)
    return row

def derive_vendor(package_name, maintainer=''):
    """Best-effort vendor inference from package name and maintainer string."""
    name_lower = package_name.lower()
    vendor_map = {
        'python': 'Python Software Foundation',
        'perl': 'The Perl Foundation',
        'ruby': 'Ruby Core Team',
        'nodejs': 'OpenJS Foundation',
        'npm': 'OpenJS Foundation',
        'openssl': 'OpenSSL Project',
        'openssh': 'OpenBSD Project',
        'curl': 'Daniel Stenberg',
        'wget': 'GNU Project',
        'bash': 'GNU Project',
        'zsh': 'Zsh Development Group',
        'vim': 'Bram Moolenaar',
        'neovim': 'Neovim Contributors',
        'git': 'Software Freedom Conservancy',
        'gcc': 'GNU Project',
        'clang': 'LLVM Project',
        'llvm': 'LLVM Project',
        'docker': 'Docker Inc.',
        'containerd': 'Cloud Native Computing Foundation',
        'nginx': 'F5 Inc.',
        'apache': 'Apache Software Foundation',
        'mysql': 'Oracle Corporation',
        'mariadb': 'MariaDB Foundation',
        'postgresql': 'PostgreSQL Global Development Group',
        'redis': 'Redis Ltd.',
        'sqlite': 'D. Richard Hipp',
        'php': 'The PHP Group',
        'java': 'Oracle Corporation',
        'openjdk': 'OpenJDK Community',
        'mono': 'Mono Project',
        'golang': 'Google LLC',
        'rust': 'The Rust Foundation',
        'firefox': 'Mozilla Foundation',
        'chromium': 'Google LLC',
        'thunderbird': 'Mozilla Foundation',
        'libreoffice': 'The Document Foundation',
        'gimp': 'GIMP Development Team',
        'inkscape': 'Inkscape Project',
        'vlc': 'VideoLAN',
        'ffmpeg': 'FFmpeg Team',
        'glib': 'GNOME Foundation',
        'gtk': 'GNOME Foundation',
        'qt': 'The Qt Company',
        'kde': 'KDE Community',
        'gnome': 'GNOME Foundation',
        'xorg': 'X.Org Foundation',
        'wayland': 'Freedesktop.org',
        'systemd': 'systemd Authors',
        'dbus': 'Freedesktop.org',
        'udev': 'systemd Authors',
        'kernel': 'Linus Torvalds',
        'linux': 'Linus Torvalds',
        'grub': 'GNU Project',
        'snapd': 'Canonical Ltd.',
        'flatpak': 'Freedesktop.org',
        'apt': 'Debian Project',
        'dpkg': 'Debian Project',
        'rpm': 'Red Hat Inc.',
        'yum': 'Red Hat Inc.',
        'dnf': 'Red Hat Inc.',
        'pacman': 'Arch Linux',
        'pip': 'Python Software Foundation',
        'node': 'OpenJS Foundation',
    }
    for key, vendor in vendor_map.items():
        if key in name_lower:
            return vendor
    # Try to parse maintainer field (format: "Name <email>")
    if maintainer:
        m = re.match(r'^([^<,]+)', maintainer)
        if m:
            return m.group(1).strip()
    return ''

# ── Package Manager Scanners ───────────────────────────────────────────────────

def scan_dpkg(base_row, rows):
    """Debian/Ubuntu: dpkg-query for all installed packages."""
    print("  Scanning dpkg packages...", flush=True)
    out = run_cmd(['dpkg-query', '-W',
                   '-f=${Package}\t${Version}\t${Installed-Size}\t${Maintainer}\t${Status}\n'],
                  timeout=30)
    if not out:
        return
    count = 0
    for line in out.splitlines():
        parts = line.split('\t')
        if len(parts) < 5:
            continue
        pkg, version, size_kb, maintainer, status = parts[0], parts[1], parts[2], parts[3], parts[4]
        if 'installed' not in status:
            continue
        # Try to get install date from dpkg log
        install_date = ''
        rows.append(make_row(base_row,
            filename=pkg,
            filepath=f'/var/lib/dpkg/info/{pkg}.list',
            software_name=pkg,
            vendor=derive_vendor(pkg, maintainer),
            version=version,
            file_version=version,
            file_size_bytes=int(size_kb) * 1024 if size_kb.isdigit() else 0,
            file_type='package',
            parent_app='',
            install_date=install_date,
            source='dpkg',
        ))
        count += 1
    print(f"    → {count} dpkg packages", flush=True)


def scan_rpm(base_row, rows):
    """RHEL/Fedora/CentOS/SUSE: rpm -qa for all installed packages."""
    print("  Scanning rpm packages...", flush=True)
    fmt = '%{NAME}\t%{VERSION}-%{RELEASE}\t%{SIZE}\t%{VENDOR}\t%{INSTALLTIME:date}\n'
    out = run_cmd(['rpm', '-qa', f'--queryformat={fmt}'], timeout=30)
    if not out:
        return
    count = 0
    for line in out.splitlines():
        parts = line.rstrip('\n').split('\t')
        if len(parts) < 5:
            continue
        pkg, version, size_b, vendor, install_date = parts[0], parts[1], parts[2], parts[3], parts[4]
        # Parse install_date to ISO format
        iso_date = ''
        if install_date and install_date != '(none)':
            try:
                dt = datetime.strptime(install_date.strip(), '%a %d %b %Y %I:%M:%S %p %Z')
                iso_date = dt.date().isoformat()
            except Exception:
                iso_date = ''
        rows.append(make_row(base_row,
            filename=pkg,
            filepath=f'/var/lib/rpm/{pkg}',
            software_name=pkg,
            vendor=vendor if vendor and vendor != '(none)' else derive_vendor(pkg),
            version=version,
            file_version=version,
            file_size_bytes=int(size_b) if size_b.isdigit() else 0,
            file_type='package',
            parent_app='',
            install_date=iso_date,
            source='rpm',
        ))
        count += 1
    print(f"    → {count} rpm packages", flush=True)


def scan_pacman(base_row, rows):
    """Arch Linux: pacman -Q for all installed packages."""
    print("  Scanning pacman packages...", flush=True)
    out = run_cmd(['pacman', '-Q'], timeout=15)
    if not out:
        return
    count = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        pkg, version = parts[0], parts[1]
        rows.append(make_row(base_row,
            filename=pkg,
            filepath=f'/var/lib/pacman/local/{pkg}-{version}',
            software_name=pkg,
            vendor=derive_vendor(pkg),
            version=version,
            file_version=version,
            file_size_bytes=0,
            file_type='package',
            parent_app='',
            install_date='',
            source='pacman',
        ))
        count += 1
    print(f"    → {count} pacman packages", flush=True)


def scan_apk(base_row, rows):
    """Alpine Linux: apk info for all installed packages."""
    print("  Scanning apk packages...", flush=True)
    out = run_cmd(['apk', 'info', '-v'], timeout=15)
    if not out:
        return
    count = 0
    for line in out.splitlines():
        # Format: package-name-version
        # We need to split on last hyphen that precedes version (e.g., musl-1.2.3)
        m = re.match(r'^(.+?)-(\d+[\d.\-_a-zA-Z]*)$', line.strip())
        if m:
            pkg, version = m.group(1), m.group(2)
        else:
            pkg, version = line.strip(), ''
        rows.append(make_row(base_row,
            filename=pkg,
            filepath=f'/lib/apk/db/{pkg}',
            software_name=pkg,
            vendor=derive_vendor(pkg),
            version=version,
            file_version=version,
            file_size_bytes=0,
            file_type='package',
            parent_app='',
            install_date='',
            source='apk',
        ))
        count += 1
    print(f"    → {count} apk packages", flush=True)


# ── Binary / ELF Scanners ──────────────────────────────────────────────────────

def scan_cli_binaries(base_row, rows, quick=False):
    """Scan executables in standard binary paths."""
    print("  Scanning CLI binaries...", flush=True)
    scan_paths = [
        '/usr/bin', '/usr/sbin',
        '/usr/local/bin', '/usr/local/sbin',
        '/bin', '/sbin',
        os.path.expanduser('~/.local/bin'),
        '/opt/bin',
    ]
    seen = set()
    count = 0
    for scan_dir in scan_paths:
        if not os.path.isdir(scan_dir):
            continue
        try:
            entries = sorted(os.listdir(scan_dir))
        except PermissionError:
            continue
        for name in entries:
            fpath = os.path.join(scan_dir, name)
            real  = os.path.realpath(fpath)
            if real in seen:
                continue
            if not os.path.isfile(fpath):
                continue
            if not os.access(fpath, os.X_OK):
                continue
            seen.add(real)

            is_elf_bin = is_elf(fpath)
            is_script  = (not is_elf_bin) and is_executable_script(fpath)

            version_str = None
            source      = 'filesystem'

            if not quick:
                ver_line = run_version_flag(fpath)
                if ver_line:
                    version_str = extract_version(ver_line)
                    source = 'cli'

            rows.append(make_row(base_row,
                filename=name,
                filepath=fpath,
                software_name=name,
                vendor=derive_vendor(name),
                version=version_str or '',
                file_version=version_str or '',
                file_size_bytes=file_size(fpath),
                file_type='binary' if is_elf_bin else ('script' if is_script else 'binary'),
                parent_app='',
                install_date=file_mtime_date(fpath),
                source=source,
            ))
            count += 1
    print(f"    → {count} CLI binaries", flush=True)


def scan_shared_libraries(base_row, rows):
    """Scan .so files in standard library paths using ldconfig cache."""
    print("  Scanning shared libraries...", flush=True)
    lib_paths = [
        '/usr/lib', '/usr/lib64', '/usr/lib/x86_64-linux-gnu',
        '/usr/lib/aarch64-linux-gnu', '/usr/lib/arm-linux-gnueabihf',
        '/usr/local/lib', '/usr/local/lib64',
        '/lib', '/lib64', '/lib/x86_64-linux-gnu',
        '/lib/aarch64-linux-gnu',
    ]

    seen = set()
    count = 0

    # Use ldconfig -p to get canonical list of shared libraries
    ldconfig_out = run_cmd(['ldconfig', '-p'], timeout=10)
    if ldconfig_out:
        for line in ldconfig_out.splitlines():
            # Format:  libfoo.so.2 (libc6,x86-64) => /usr/lib/x86_64-linux-gnu/libfoo.so.2
            m = re.match(r'\s+(\S+)\s+\([^)]+\)\s+=>\s+(\S+)', line)
            if not m:
                continue
            lib_name, lib_path = m.group(1), m.group(2)
            if lib_path in seen:
                continue
            seen.add(lib_path)

            # Extract version from soname (e.g., libssl.so.3 → 3)
            soname_ver = extract_version(lib_name)
            software_name = re.sub(r'\.so.*$', '', lib_name)  # strip .so.x

            rows.append(make_row(base_row,
                filename=lib_name,
                filepath=lib_path,
                software_name=software_name,
                vendor=derive_vendor(software_name),
                version=soname_ver or '',
                file_version=soname_ver or '',
                file_size_bytes=file_size(lib_path),
                file_type='library',
                parent_app='',
                install_date=file_mtime_date(lib_path),
                source='elf_header',
            ))
            count += 1
    else:
        # Fallback: walk lib_paths directly
        for lib_dir in lib_paths:
            if not os.path.isdir(lib_dir):
                continue
            try:
                for name in os.listdir(lib_dir):
                    if not name.endswith('.so') and '.so.' not in name:
                        continue
                    fpath = os.path.join(lib_dir, name)
                    if fpath in seen or not os.path.isfile(fpath):
                        continue
                    seen.add(fpath)
                    soname_ver = extract_version(name)
                    software_name = re.sub(r'\.so.*$', '', name)
                    rows.append(make_row(base_row,
                        filename=name,
                        filepath=fpath,
                        software_name=software_name,
                        vendor=derive_vendor(software_name),
                        version=soname_ver or '',
                        file_version=soname_ver or '',
                        file_size_bytes=file_size(fpath),
                        file_type='library',
                        parent_app='',
                        install_date=file_mtime_date(fpath),
                        source='filesystem',
                    ))
                    count += 1
            except PermissionError:
                continue

    print(f"    → {count} shared libraries", flush=True)


# ── Containerization / Sandboxed App Scanners ─────────────────────────────────

def scan_snap(base_row, rows):
    """Scan installed snap packages."""
    print("  Scanning snap packages...", flush=True)
    out = run_cmd(['snap', 'list'], timeout=10)
    if not out:
        return
    count = 0
    for line in out.splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) < 3:
            continue
        name, version = parts[0], parts[1]
        revision = parts[2] if len(parts) > 2 else ''
        snap_path = f'/snap/{name}/current'
        rows.append(make_row(base_row,
            filename=name,
            filepath=snap_path,
            software_name=name,
            vendor=derive_vendor(name),
            version=version,
            file_version=f'rev{revision}' if revision else version,
            file_size_bytes=0,
            file_type='snap',
            parent_app='',
            install_date='',
            source='snap',
        ))
        count += 1
    print(f"    → {count} snap packages", flush=True)


def scan_flatpak(base_row, rows):
    """Scan installed flatpak applications."""
    print("  Scanning flatpak packages...", flush=True)
    out = run_cmd(['flatpak', 'list', '--app', '--columns=application,version,name'], timeout=10)
    if not out:
        return
    count = 0
    for line in out.splitlines():
        parts = line.split('\t')
        if len(parts) < 3:
            continue
        app_id, version, name = parts[0].strip(), parts[1].strip(), parts[2].strip()
        fp_path = f'/var/lib/flatpak/app/{app_id}'
        rows.append(make_row(base_row,
            filename=app_id,
            filepath=fp_path,
            software_name=name or app_id,
            vendor=app_id.split('.')[1] if app_id.count('.') >= 2 else '',
            version=version,
            file_version=version,
            file_size_bytes=0,
            file_type='flatpak',
            parent_app='',
            install_date='',
            source='flatpak',
        ))
        count += 1
    print(f"    → {count} flatpak packages", flush=True)


# ── Language Runtime Scanners ──────────────────────────────────────────────────

def scan_python_packages(base_row, rows):
    """Scan Python packages via pip3 / pip."""
    print("  Scanning Python packages...", flush=True)
    count = 0
    for pip_cmd in ['pip3', 'pip', 'python3 -m pip', 'python -m pip']:
        cmd = pip_cmd.split() + ['list', '--format=json']
        out = run_cmd(cmd, timeout=20)
        if not out:
            continue
        try:
            pkgs = json.loads(out)
        except json.JSONDecodeError:
            continue
        for pkg in pkgs:
            name    = pkg.get('name', '')
            version = pkg.get('version', '')
            rows.append(make_row(base_row,
                filename=name,
                filepath=f'pip:{name}',
                software_name=name,
                vendor='',
                version=version,
                file_version=version,
                file_size_bytes=0,
                file_type='package',
                parent_app='python',
                install_date='',
                source='pip',
            ))
            count += 1
        if count > 0:
            break  # only scan once
    print(f"    → {count} Python packages", flush=True)


def scan_node_packages(base_row, rows):
    """Scan globally installed npm packages."""
    print("  Scanning npm global packages...", flush=True)
    out = run_cmd(['npm', 'list', '-g', '--depth=0', '--json'], timeout=20)
    if not out:
        return
    count = 0
    try:
        data = json.loads(out)
        deps = data.get('dependencies', {})
    except json.JSONDecodeError:
        return
    for name, info in deps.items():
        version = info.get('version', '')
        rows.append(make_row(base_row,
            filename=name,
            filepath=f'npm-global:{name}',
            software_name=name,
            vendor='',
            version=version,
            file_version=version,
            file_size_bytes=0,
            file_type='package',
            parent_app='nodejs',
            install_date='',
            source='npm',
        ))
        count += 1
    print(f"    → {count} npm global packages", flush=True)


def scan_ruby_gems(base_row, rows):
    """Scan installed Ruby gems."""
    print("  Scanning Ruby gems...", flush=True)
    out = run_cmd(['gem', 'list', '--no-versions'], timeout=15)
    if not out:
        return
    # Get versions with: gem list (default output has versions)
    out_v = run_cmd(['gem', 'list'], timeout=15)
    gem_versions = {}
    for line in out_v.splitlines():
        m = re.match(r'^(\S+)\s+\(([^)]+)\)', line)
        if m:
            name = m.group(1)
            versions = m.group(2).split(', ')
            gem_versions[name] = versions[0]  # most recent
    count = 0
    for line in out.splitlines():
        name = line.strip()
        if not name or name.startswith('***'):
            continue
        version = gem_versions.get(name, '')
        rows.append(make_row(base_row,
            filename=name,
            filepath=f'gem:{name}',
            software_name=name,
            vendor='',
            version=version,
            file_version=version,
            file_size_bytes=0,
            file_type='package',
            parent_app='ruby',
            install_date='',
            source='gem',
        ))
        count += 1
    print(f"    → {count} Ruby gems", flush=True)


# ── Kernel & System Info ───────────────────────────────────────────────────────

def scan_kernel(base_row, rows):
    """Capture Linux kernel version as a row."""
    kernel_ver = run_cmd(['uname', '-r'])
    if not kernel_ver:
        return
    rows.append(make_row(base_row,
        filename='vmlinuz',
        filepath='/boot/vmlinuz',
        software_name='Linux Kernel',
        vendor='Linus Torvalds',
        version=kernel_ver,
        file_version=kernel_ver,
        file_size_bytes=file_size('/boot/vmlinuz') or 0,
        file_type='binary',
        parent_app='',
        install_date='',
        source='cli',
    ))


def scan_firmware(base_row, rows):
    """Capture BIOS/UEFI firmware version via dmidecode or /sys/class/dmi."""
    vendor  = ''
    version = ''
    date_   = ''

    # Try /sys/class/dmi/id first (no sudo needed)
    try:
        v = Path('/sys/class/dmi/id/bios_version').read_text().strip()
        if v:
            version = v
        vd = Path('/sys/class/dmi/id/bios_date').read_text().strip()
        if vd:
            date_ = vd
        vv = Path('/sys/class/dmi/id/sys_vendor').read_text().strip()
        if vv:
            vendor = vv
    except Exception:
        pass

    # Fall back to dmidecode if sysfs gave nothing
    if not version:
        try:
            out = subprocess.run(
                ['dmidecode', '-t', 'bios'],
                capture_output=True, text=True, timeout=10
            ).stdout
            m = re.search(r'Version:\s+(.+)', out)
            if m:
                version = m.group(1).strip()
            m = re.search(r'Release Date:\s+(.+)', out)
            if m:
                date_ = m.group(1).strip()
            m = re.search(r'Vendor:\s+(.+)', out)
            if m:
                vendor = m.group(1).strip()
        except Exception:
            pass

    if not version:
        return

    rows.append(make_row(base_row,
        filename='bios',
        filepath='firmware://bios',
        software_name='BIOS / UEFI Firmware',
        vendor=vendor or 'Unknown',
        version=version,
        file_version=version,
        file_size_bytes=0,
        file_type='firmware',
        parent_app='',
        install_date=date_,
        source='dmi',
    ))


def scan_systemd_units(base_row, rows):
    """Capture systemd version."""
    out = run_cmd(['systemctl', '--version'], timeout=5)
    if not out:
        return
    m = re.search(r'systemd\s+(\d+)', out)
    if m:
        version = m.group(1)
        rows.append(make_row(base_row,
            filename='systemd',
            filepath='/lib/systemd/systemd',
            software_name='systemd',
            vendor='systemd Authors',
            version=version,
            file_version=version,
            file_size_bytes=file_size('/lib/systemd/systemd'),
            file_type='binary',
            parent_app='',
            install_date='',
            source='cli',
        ))


# ── Detection Helpers ──────────────────────────────────────────────────────────

def detect_package_managers():
    """Return list of available package managers."""
    managers = []
    for cmd in ['dpkg-query', 'rpm', 'pacman', 'apk']:
        if run_cmd(['which', cmd]):
            managers.append(cmd)
    return managers

def has_cmd(cmd):
    return bool(run_cmd(['which', cmd]))


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='SVRT Linux File-Level Inventory Scanner v1.0'
    )
    parser.add_argument('--output', '-o', help='Output CSV path')
    parser.add_argument('--quick', action='store_true',
                        help='Packages + CLI only; skip .so and binary version probing')
    parser.add_argument('--no-so', action='store_true',
                        help='Skip shared library (.so) scan')
    parser.add_argument('--no-snap', action='store_true',
                        help='Skip snap and flatpak scan')
    args = parser.parse_args()

    hostname_hash = hash_hostname()
    arch          = get_arch()
    os_ver        = get_os_version()

    output_path = args.output or os.path.expanduser(
        f'~/svrt_inventory_linux_{hostname_hash[:8]}_{TODAY}.csv'
    )

    base_row = {
        'svrt_format_version': SVRT_FORMAT_VERSION,
        'scan_date':           TODAY,
        'hostname_hash':       hostname_hash,
        'platform':            'linux',
        'arch':                arch,
        'os_version':          os_ver,
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

    print(f"\nSVRT Linux Inventory Scanner v1.0", flush=True)
    print(f"  Platform : {os_ver} ({arch})", flush=True)
    print(f"  Host hash: {hostname_hash}", flush=True)
    print(f"  Output   : {output_path}", flush=True)
    print(f"  Quick    : {args.quick}", flush=True)
    print("", flush=True)

    rows = []

    # ── Kernel + Firmware ────────────────────────────────────────────────────
    print("Phase 1: System", flush=True)
    scan_kernel(base_row, rows)
    scan_firmware(base_row, rows)
    if has_cmd('systemctl') and not args.quick:
        scan_systemd_units(base_row, rows)

    # ── Package Managers ──────────────────────────────────────────────────────
    print("\nPhase 2: Package Managers", flush=True)
    if has_cmd('dpkg-query'):
        scan_dpkg(base_row, rows)
    if has_cmd('rpm'):
        scan_rpm(base_row, rows)
    if has_cmd('pacman'):
        scan_pacman(base_row, rows)
    if has_cmd('apk'):
        scan_apk(base_row, rows)

    # ── CLI Binaries ──────────────────────────────────────────────────────────
    print("\nPhase 3: CLI Binaries", flush=True)
    scan_cli_binaries(base_row, rows, quick=args.quick)

    # ── Shared Libraries ──────────────────────────────────────────────────────
    if not args.quick and not args.no_so:
        print("\nPhase 4: Shared Libraries", flush=True)
        scan_shared_libraries(base_row, rows)

    # ── Snap / Flatpak ────────────────────────────────────────────────────────
    if not args.no_snap:
        print("\nPhase 5: Sandboxed Apps", flush=True)
        if has_cmd('snap'):
            scan_snap(base_row, rows)
        if has_cmd('flatpak'):
            scan_flatpak(base_row, rows)

    # ── Language Runtimes ─────────────────────────────────────────────────────
    print("\nPhase 6: Language Runtimes", flush=True)
    if has_cmd('pip3') or has_cmd('pip'):
        scan_python_packages(base_row, rows)
    if has_cmd('npm'):
        scan_node_packages(base_row, rows)
    if has_cmd('gem'):
        scan_ruby_gems(base_row, rows)

    # ── Write CSV ─────────────────────────────────────────────────────────────
    print(f"\nWriting {len(rows):,} rows → {output_path}", flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    # ── Summary ───────────────────────────────────────────────────────────────
    by_type = {}
    for row in rows:
        t = row.get('file_type', 'unknown')
        by_type[t] = by_type.get(t, 0) + 1

    print(f"\n{'─'*50}", flush=True)
    print(f"  Total items : {len(rows):,}", flush=True)
    for ftype, cnt in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {ftype:<18}: {cnt:,}", flush=True)
    print(f"{'─'*50}", flush=True)
    print(f"\n  Output: {output_path}", flush=True)
    print(f"  Upload this file at: https://askmcconnell.com/svrt\n", flush=True)


if __name__ == '__main__':
    main()
