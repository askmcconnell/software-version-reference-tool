#!/bin/bash
# SVRT Nightly Sync — Raspberry Pi → IONOS
# Pushes the SQLite reference DB and a CSV export to IONOS via curl FTP.
# Runs nightly via cron (MUST include cd prefix for correct log paths):
#   0 3 * * * cd /home/svrt/svrt && bash sync/push_to_ionos.sh >> logs/sync.log 2>&1
#
# Required env vars (set in /home/svrt/.env):
#   IONOS_HOST          — IONOS SFTP hostname (e.g. home183552103.1and1-data.host)
#   IONOS_USER          — IONOS SFTP username
#   IONOS_PASS          — IONOS SFTP password
#   IONOS_REMOTE        — remote SFTP path (e.g. /clickandbuilds/.../svrt/db/)
#   WP_ADMIN_TOKEN      — WordPress Bearer token for reference import API
#   WP_PROCESS_SECRET   — queue secret for /admin/unknown-software endpoint
#
# Optional:
#   WP_BASE         — WordPress API base (default: https://askmcconnell.com/wp-json/svrt/v1)
#   SLACK_WEBHOOK   — Slack webhook URL for notifications

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
DB_PATH="$BASE_DIR/db/svrt_reference.db"
EXPORT_DIR="$BASE_DIR/db/exports"
LOG_FILE="$BASE_DIR/logs/sync.log"
AGENT_SCRIPT="$BASE_DIR/agent/svrt_agent.py"

# Load env file if present
ENV_FILE="/home/svrt/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

# Validate required env vars
IONOS_HOST="${IONOS_HOST:-}"
IONOS_USER="${IONOS_USER:-}"
IONOS_PASS="${IONOS_PASS:-}"
IONOS_REMOTE="${IONOS_REMOTE:-/clickandbuilds/AskMcConnellGen2/svrt/db/}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

notify_slack() {
    local msg="$1"
    if [ -n "${SLACK_WEBHOOK:-}" ]; then
        curl -s -X POST "$SLACK_WEBHOOK" \
            -H 'Content-type: application/json' \
            --data "{\"text\":\"SVRT Sync: $msg\"}" >/dev/null 2>&1 || true
    fi
}

# ── Pre-flight checks ──────────────────────────────────────────────────────────

if [ ! -f "$DB_PATH" ]; then
    log "ERROR: Database not found at $DB_PATH"
    exit 1
fi

if [ -z "$IONOS_HOST" ] || [ -z "$IONOS_USER" ] || [ -z "$IONOS_PASS" ]; then
    log "ERROR: IONOS_HOST, IONOS_USER, or IONOS_PASS not set. Check $ENV_FILE"
    exit 1
fi

mkdir -p "$EXPORT_DIR"

# ── Export CSV snapshot ────────────────────────────────────────────────────────

DATE=$(date '+%Y-%m-%d')
CSV_EXPORT="$EXPORT_DIR/svrt_reference_$DATE.csv"
JSON_EXPORT="$EXPORT_DIR/svrt_stats.json"

log "Exporting reference DB to CSV + JSON (via Python)..."
python3 - "$DB_PATH" "$CSV_EXPORT" "$JSON_EXPORT" << 'PYEOF'
import sys, csv, json, sqlite3
from datetime import datetime

db_path, csv_path, json_path = sys.argv[1], sys.argv[2], sys.argv[3]
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# CSV export
rows = conn.execute("""
    SELECT software_name, vendor, version, platform, eol_status, eol_date,
           latest_version, latest_source_url, confidence, source, checked_at
    FROM svrt_reference
    WHERE eol_status != 'unknown'
    ORDER BY hit_count DESC
""").fetchall()
with open(csv_path, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow([d[0] for d in conn.execute("SELECT software_name, vendor, version, platform, eol_status, eol_date, latest_version, latest_source_url, confidence, source, checked_at FROM svrt_reference LIMIT 0").description])
    w.writerows(rows)
print(f"CSV: {len(rows)} rows")

# JSON stats
def count(q): return conn.execute(q).fetchone()[0]
stats = {
    "total_entries":    count("SELECT COUNT(*) FROM svrt_reference"),
    "eol_count":        count("SELECT COUNT(*) FROM svrt_reference WHERE eol_status='eol'"),
    "supported_count":  count("SELECT COUNT(*) FROM svrt_reference WHERE eol_status='supported'"),
    "lts_count":        count("SELECT COUNT(*) FROM svrt_reference WHERE eol_status='lts'"),
    "unknown_count":    count("SELECT COUNT(*) FROM svrt_reference WHERE eol_status='unknown'"),
    "total_submissions":count("SELECT COUNT(*) FROM svrt_field_submissions"),
    "unique_hosts":     count("SELECT COUNT(DISTINCT hostname_hash) FROM svrt_field_submissions"),
    "last_sync":        datetime.utcnow().isoformat(),
}
with open(json_path, 'w') as f:
    json.dump(stats, f, indent=2)
print(f"JSON stats: {stats['total_entries']} entries")
conn.close()
PYEOF

CSV_ROWS=$(python3 -c "
import csv
with open('$CSV_EXPORT') as f:
    print(sum(1 for _ in csv.reader(f)) - 1)
" 2>/dev/null || echo 0)
log "CSV exported: $CSV_ROWS rows → $CSV_EXPORT"
cp "$CSV_EXPORT" "$EXPORT_DIR/svrt_reference_latest.csv"
log "Stats JSON written: $JSON_EXPORT"

# ── Push to IONOS via Python/paramiko SFTP ────────────────────────────────────

log "Pushing to IONOS ($IONOS_HOST) via SFTP..."

python3 - "$IONOS_HOST" "$IONOS_USER" "$IONOS_PASS" "$IONOS_REMOTE" \
          "$DB_PATH" "$CSV_EXPORT" "$JSON_EXPORT" << 'SFTP_PY'
import sys, os
sys.path.insert(0, os.path.expanduser('~/.local/lib/python3.11/site-packages'))
import paramiko

host, user, password, remote_dir = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
files = sys.argv[5:]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(host, username=user, password=password, timeout=30)
sftp = ssh.open_sftp()

# Ensure remote directory exists (mkdir -p equivalent)
parts = remote_dir.strip('/').split('/')
path = ''
for part in parts:
    path = path + '/' + part
    try:
        sftp.mkdir(path)
    except IOError:
        pass  # already exists

# Upload each file
for local_path in files:
    remote_name = os.path.basename(local_path)
    remote_path = remote_dir.rstrip('/') + '/' + remote_name
    print(f"  Uploading {remote_name} ({os.path.getsize(local_path)//1024} KB)...")
    sftp.put(local_path, remote_path)
    print(f"  ✓ {remote_name}")

sftp.close()
ssh.close()
print("All files uploaded successfully.")
SFTP_PY

if [ $? -eq 0 ]; then
    DB_SIZE=$(du -sh "$DB_PATH" | cut -f1)
    log "✓ SFTP sync SUCCESS — DB=$DB_SIZE, CSV=$CSV_ROWS rows"
else
    log "✗ SFTP sync FAILED — check $LOG_FILE"
    notify_slack "✗ Nightly sync FAILED. Check Pi logs."
    exit 1
fi

# ── Push resolved entries to WordPress REST API ────────────────────────────────

WP_API="${WP_API:-https://askmcconnell.com/wp-json/svrt/v1/admin/reference/import}"
WP_ADMIN_TOKEN="${WP_ADMIN_TOKEN:-}"

if [ -n "$WP_ADMIN_TOKEN" ]; then
    log "Pushing reference data to WordPress API..."
    python3 - "$DB_PATH" "$WP_API" "$WP_ADMIN_TOKEN" << 'WP_PY'
import sys, json, sqlite3, urllib.request

db_path, api_url, token = sys.argv[1], sys.argv[2], sys.argv[3]
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Export only resolved (non-unknown) entries updated in the last 2 days
rows = conn.execute("""
    SELECT lookup_key, software_name, vendor, version, platform,
           eol_status, eol_date, latest_version, latest_source_url,
           confidence, source as ref_source, notes, checked_at, expires_at
    FROM svrt_reference
    WHERE eol_status != 'unknown'
      AND checked_at >= datetime('now', '-2 days')
    ORDER BY hit_count DESC
    LIMIT 2000
""").fetchall()
conn.close()

if not rows:
    print("No new/updated entries to push.")
    sys.exit(0)

payload = [dict(r) for r in rows]
body    = json.dumps(payload).encode()
req     = urllib.request.Request(api_url, data=body, headers={
    'Content-Type':  'application/json',
    'Authorization': f'Bearer {token}',
})
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    print(f"WP import: {result.get('imported',0)} imported, {result.get('skipped',0)} skipped")
except Exception as e:
    print(f"WP import error: {e}")
    sys.exit(1)
WP_PY

    if [ $? -eq 0 ]; then
        log "✓ WordPress reference import complete"
    else
        log "⚠ WordPress import failed (files already synced via SFTP)"
    fi
else
    log "WP_ADMIN_TOKEN not set — skipping WordPress API import"
fi

DB_SIZE=$(du -sh "$DB_PATH" | cut -f1)
notify_slack "✓ Nightly sync complete. DB=$DB_SIZE, $CSV_ROWS known products."

# ── Pull GitHub YAML reference DB → upsert into local SQLite ─────────────────
# Community-curated YAML files at confidence=90 fill gaps between endoflife.date
# and Claude. Won't overwrite manual (95) entries.

if python3 -c "import yaml" 2>/dev/null; then
    log "Syncing GitHub YAML reference DB..."
    python3 "$AGENT_SCRIPT" --sync-yaml 2>&1 | \
        while IFS= read -r line; do log "  [yaml] $line"; done
    if [ $? -eq 0 ]; then
        log "✓ GitHub YAML sync complete"
    else
        log "⚠ GitHub YAML sync encountered errors (non-fatal)"
    fi
else
    log "PyYAML not installed — skipping GitHub YAML sync (run: pip3 install pyyaml)"
fi

# ── Pull unknown software from IONOS → seed Pi research queue ─────────────────
# IONOS has inventory rows where eol_status='unknown' (no match in reference DB).
# We fetch those as a CSV so the Pi knows what to research next (two-way sync).

WP_PROCESS_SECRET="${WP_PROCESS_SECRET:-}"
WP_BASE="${WP_BASE:-https://askmcconnell.com/wp-json/svrt/v1}"
UNKNOWN_CSV="$BASE_DIR/db/exports/ionos_unknown_software.csv"

if [ -n "$WP_PROCESS_SECRET" ] && [ -f "$AGENT_SCRIPT" ]; then
    log "Fetching unknown software list from IONOS..."
    UNKNOWN_URL="${WP_BASE}/admin/unknown-software?secret=${WP_PROCESS_SECRET}&limit=10000"

    HTTP_CODE=$(curl -s -o "$UNKNOWN_CSV" -w "%{http_code}" \
        --max-time 60 \
        "$UNKNOWN_URL" 2>/dev/null || echo "000")

    if [ "$HTTP_CODE" = "200" ] && [ -s "$UNKNOWN_CSV" ]; then
        # Sanity check: file should start with CSV header
        FIRST_LINE=$(head -1 "$UNKNOWN_CSV")
        if echo "$FIRST_LINE" | grep -q "software_name"; then
            UNKNOWN_COUNT=$(wc -l < "$UNKNOWN_CSV")
            UNKNOWN_COUNT=$((UNKNOWN_COUNT - 1))   # subtract header
            log "  → $UNKNOWN_COUNT unknown software items downloaded"

            python3 "$AGENT_SCRIPT" --import-csv "$UNKNOWN_CSV" 2>&1 | \
                while IFS= read -r line; do log "  [agent] $line"; done

            if [ $? -eq 0 ]; then
                log "✓ Research queue seeded from IONOS unknown software list"
            else
                log "⚠ Agent import encountered errors (queue may be partially seeded)"
            fi
        else
            log "⚠ IONOS unknown-software response doesn't look like CSV (got: $FIRST_LINE)"
        fi
    elif [ "$HTTP_CODE" = "200" ] && [ ! -s "$UNKNOWN_CSV" ]; then
        log "  → No unknown software to import (all rows resolved)"
    else
        log "⚠ Failed to fetch unknown software list (HTTP $HTTP_CODE)"
    fi
else
    if [ -z "$WP_PROCESS_SECRET" ]; then
        log "WP_PROCESS_SECRET not set — skipping unknown software pull"
    else
        log "Agent script not found at $AGENT_SCRIPT — skipping unknown software pull"
    fi
fi

# ── Cleanup old exports (keep 7 days) ─────────────────────────────────────────

find "$EXPORT_DIR" -name "svrt_reference_2*.csv" -mtime +7 -delete
log "Cleaned up old exports."

log "Sync complete."
