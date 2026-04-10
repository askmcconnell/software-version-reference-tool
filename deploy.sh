#!/usr/bin/env bash
# ============================================================
# SVRT — Deploy Script
# Builds the React PWA and deploys all assets to IONOS.
#
# Usage:
#   ./deploy.sh              — build + deploy PWA only
#   ./deploy.sh --plugin     — also redeploy WordPress plugin
#   ./deploy.sh --scanners   — also redeploy scanner scripts
#   ./deploy.sh --all        — PWA + plugin + scanners
#
# Reads credentials from .deploy.env in the same directory.
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.deploy.env"

# ── Load credentials ───────────────────────────────────────
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "ERROR: .deploy.env not found at $ENV_FILE"
    echo "Create it with: FTP_HOST, FTP_USER, FTP_PASS"
    exit 1
fi

: "${FTP_HOST:?FTP_HOST is required (set in .deploy.env)}"
: "${FTP_USER:?FTP_USER is required}"
: "${FTP_PASS:?FTP_PASS is required}"

# Remote paths (relative to SFTP root = web root)
SVRT_REMOTE_DIR="${SVRT_REMOTE_DIR:-/svrt}"
PLUGIN_REMOTE_PATH="${PLUGIN_REMOTE_PATH:-/wp-content/plugins/svrt/svrt.php}"
SCANNERS_REMOTE_DIR="${SCANNERS_REMOTE_DIR:-/svrt/scanners}"

# ── Parse flags ────────────────────────────────────────────
DEPLOY_PLUGIN=false
DEPLOY_SCANNERS=false
for arg in "$@"; do
    case "$arg" in
        --plugin)   DEPLOY_PLUGIN=true ;;
        --scanners) DEPLOY_SCANNERS=true ;;
        --all)      DEPLOY_PLUGIN=true; DEPLOY_SCANNERS=true ;;
    esac
done

# ── Load Node.js (nvm) ─────────────────────────────────────
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

# ── Build PWA ──────────────────────────────────────────────
echo ""
echo "==> Building SVRT React PWA..."
cd "$SCRIPT_DIR/pwa"
npm run build
cd "$SCRIPT_DIR"

DIST="$SCRIPT_DIR/pwa/dist"
BUILD_SIZE=$(du -sh "$DIST" | cut -f1)
echo "    Build size: $BUILD_SIZE"

# ── Deploy via Python/paramiko SFTP ───────────────────────
echo ""
echo "==> Deploying to ${FTP_HOST}..."

python3 - \
    "$FTP_HOST" "$FTP_USER" "$FTP_PASS" \
    "$DIST" "$SVRT_REMOTE_DIR" \
    "$DEPLOY_PLUGIN" "$SCRIPT_DIR/wordpress-plugin/svrt/svrt.php" "$PLUGIN_REMOTE_PATH" \
    "$DEPLOY_SCANNERS" \
    "$SCRIPT_DIR/scripts/mac/svrt_scan_mac.py" \
    "$SCRIPT_DIR/scripts/linux/svrt_scan_linux.py" \
    "$SCRIPT_DIR/scripts/windows/svrt_scan_windows.ps1" \
    "$SCANNERS_REMOTE_DIR" \
<< 'PYEOF'
import sys, os

# Locate paramiko — check brew/pip paths
for site_path in [
    '/Library/Python/3.9/lib/python/site-packages',
    '/usr/local/lib/python3.9/site-packages',
    '/usr/local/lib/python3.11/site-packages',
    os.path.expanduser('~/.local/lib/python3.11/site-packages'),
]:
    if os.path.isdir(site_path):
        sys.path.insert(0, site_path)

import paramiko

(host, user, password,
 dist, svrt_remote,
 deploy_plugin, plugin_local, plugin_remote,
 deploy_scanners,
 mac_scanner, linux_scanner, windows_scanner,
 scanners_remote) = sys.argv[1:15]

deploy_plugin   = deploy_plugin   == 'true'
deploy_scanners = deploy_scanners == 'true'

def sftp_mkdir_p(sftp, remote_dir):
    """Create remote directory and all parents (like mkdir -p)."""
    parts = remote_dir.strip('/').split('/')
    path  = ''
    for part in parts:
        path = path + '/' + part
        try:
            sftp.mkdir(path)
        except IOError:
            pass  # already exists

def upload_dir(sftp, local_dir, remote_dir):
    """Recursively upload a directory."""
    sftp_mkdir_p(sftp, remote_dir)
    count = 0
    for item in sorted(os.listdir(local_dir)):
        local_path  = os.path.join(local_dir, item)
        remote_path = remote_dir.rstrip('/') + '/' + item
        if os.path.isdir(local_path):
            count += upload_dir(sftp, local_path, remote_path)
        else:
            sftp.put(local_path, remote_path)
            size = os.path.getsize(local_path) // 1024
            print(f'    ✓  {remote_path}  ({size} KB)')
            count += 1
    return count

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(host, username=user, password=password, timeout=30)
sftp = ssh.open_sftp()

# ── PWA dist ──────────────────────────────────────────────────────────────────
print(f'\n  Uploading PWA → {svrt_remote}/')
total = upload_dir(sftp, dist, svrt_remote)
print(f'  → {total} files uploaded')

# Ensure .htaccess for React Router SPA is in place
htaccess = (
    "Options -MultiViews\n"
    "RewriteEngine On\n"
    "RewriteBase /svrt/\n"
    "RewriteRule ^index\\.html$ - [L]\n"
    "RewriteCond %{REQUEST_FILENAME} !-f\n"
    "RewriteCond %{REQUEST_FILENAME} !-d\n"
    "RewriteRule . /svrt/index.html [L]\n"
)
import io
sftp.putfo(io.BytesIO(htaccess.encode()), svrt_remote.rstrip('/') + '/.htaccess')
print(f'  ✓  {svrt_remote}/.htaccess (SPA routing)')

# ── WordPress plugin ──────────────────────────────────────────────────────────
if deploy_plugin:
    print(f'\n  Uploading WordPress plugin → {plugin_remote}')
    plugin_dir = os.path.dirname(plugin_remote)
    sftp_mkdir_p(sftp, plugin_dir)
    sftp.put(plugin_local, plugin_remote)
    size = os.path.getsize(plugin_local) // 1024
    print(f'  ✓  svrt.php ({size} KB)')

# ── Scanner scripts ───────────────────────────────────────────────────────────
if deploy_scanners:
    print(f'\n  Uploading scanner scripts → {scanners_remote}/')
    sftp_mkdir_p(sftp, scanners_remote)

    # .htaccess to prevent Apache CGI execution of .py files
    scanner_htaccess = (
        '<FilesMatch "\\.py$">\n'
        '    SetHandler default-handler\n'
        '    ForceType text/plain\n'
        '</FilesMatch>\n'
    )
    sftp.putfo(io.BytesIO(scanner_htaccess.encode()), scanners_remote.rstrip('/') + '/.htaccess')

    for scanner_path in [mac_scanner, linux_scanner, windows_scanner]:
        name        = os.path.basename(scanner_path)
        remote_path = scanners_remote.rstrip('/') + '/' + name
        sftp.put(scanner_path, remote_path)
        size = os.path.getsize(scanner_path) // 1024
        print(f'  ✓  {name} ({size} KB)')

sftp.close()
ssh.close()
print('\n  All uploads complete.')
PYEOF

# ── Summary ────────────────────────────────────────────────
echo ""
echo "==> Deploy complete!"
echo "    PWA live at:   https://askmcconnell.com/svrt/"
if [ "$DEPLOY_PLUGIN" = "true" ]; then
    echo "    Plugin:        deployed (activate in WP Admin if needed)"
fi
if [ "$DEPLOY_SCANNERS" = "true" ]; then
    echo "    Scanners:      https://askmcconnell.com/svrt/scanners/"
fi
echo ""
