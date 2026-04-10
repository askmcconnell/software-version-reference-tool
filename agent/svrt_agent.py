#!/usr/bin/env python3
"""
SVRT Research Agent — Raspberry Pi
Ask McConnell's Software Version Reference Tool

Runs locally on the Pi. Queries endoflife.date, scrapes manufacturer pages,
and uses Claude API as a last resort to populate the reference database.

Nightly cron pushes the SQLite DB to IONOS via rsync/sftp.

Usage:
    python3 svrt_agent.py              # full research run
    python3 svrt_agent.py --status     # print DB statistics
    python3 svrt_agent.py --lookup "nginx"         # lookup single product
    python3 svrt_agent.py --import-csv file.csv    # add CSV inventory to queue
    python3 svrt_agent.py --sync       # push DB to IONOS now
"""

import os, sys, json, re, csv, time, sqlite3, hashlib, argparse, logging
import urllib.request, urllib.error, urllib.parse
from datetime import datetime, date, timedelta
from pathlib import Path

# ── Load .env file if present (before any config reads) ───────────────────────
_ENV_FILE = Path.home() / '.env'
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _, _v = _line.partition('=')
            os.environ.setdefault(_k.strip(), _v.strip())

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent.parent        # ~/svrt/
DB_PATH      = BASE_DIR / 'db' / 'svrt_reference.db'
LOG_PATH     = BASE_DIR / 'logs' / 'agent.log'
SYNC_SCRIPT  = BASE_DIR / 'sync' / 'push_to_ionos.sh'
CLAUDE_KEY   = os.environ.get('ANTHROPIC_API_KEY', '')

EOL_DATE_API = 'https://endoflife.date/api'
CLAUDE_API   = 'https://api.anthropic.com/v1/messages'
CLAUDE_MODEL = 'claude-haiku-4-5'          # cheapest model

# Claude Haiku pricing (per million tokens)
CLAUDE_INPUT_COST_PER_M  = 0.80   # $0.80 / 1M input tokens
CLAUDE_OUTPUT_COST_PER_M = 4.00   # $4.00 / 1M output tokens

# Lookup chain confidence scores
CONF_ENDOFLIFE_DATE = 85
CONF_CLAUDE         = 60
CONF_MANUAL         = 95
CONF_COMMUNITY      = 90   # 3+ agreeing Claude calls

# TTLs (days before re-checking)
TTL_EOL_FACT    = 90
TTL_SUPPORTED   = 14
TTL_UNKNOWN     = 3

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger('svrt-agent')

# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def init_db(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS svrt_reference (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        lookup_key        TEXT NOT NULL UNIQUE,   -- lower(vendor:product:version)
        software_name     TEXT,
        vendor            TEXT,
        version           TEXT,
        platform          TEXT,
        eol_status        TEXT,    -- eol | supported | lts | unknown | no_patch
        eol_date          TEXT,
        latest_version    TEXT,
        latest_source_url TEXT,
        confidence        INTEGER DEFAULT 0,
        source            TEXT,    -- endoflife.date | claude | manual | community
        notes             TEXT,
        hit_count         INTEGER DEFAULT 0,
        created_at        TEXT,
        checked_at        TEXT,
        expires_at        TEXT,
        conflicting_data  TEXT     -- JSON array of conflicting facts
    );

    CREATE TABLE IF NOT EXISTS svrt_research_queue (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        lookup_key    TEXT NOT NULL UNIQUE,
        software_name TEXT,
        vendor        TEXT,
        version       TEXT,
        platform      TEXT,
        priority      INTEGER DEFAULT 5,   -- 1=urgent 10=low
        attempts      INTEGER DEFAULT 0,
        last_attempt  TEXT,
        status        TEXT DEFAULT 'pending'  -- pending | in_progress | done | failed
    );

    CREATE TABLE IF NOT EXISTS svrt_field_submissions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        lookup_key    TEXT,
        software_name TEXT,
        vendor        TEXT,
        version       TEXT,
        platform      TEXT,
        hostname_hash TEXT,
        scan_date     TEXT,
        submitted_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS svrt_agent_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        run_date   TEXT,
        phase      TEXT,
        items_in   INTEGER,
        items_out  INTEGER,
        api_calls  INTEGER,
        notes      TEXT
    );

    CREATE TABLE IF NOT EXISTS svrt_api_cost_log (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        call_date      TEXT DEFAULT (date('now')),
        call_ts        TEXT DEFAULT (datetime('now')),
        model          TEXT,
        input_tokens   INTEGER DEFAULT 0,
        output_tokens  INTEGER DEFAULT 0,
        cost_usd       REAL DEFAULT 0.0,
        product_name   TEXT,
        result_status  TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_ref_lookup ON svrt_reference(lookup_key);
    CREATE INDEX IF NOT EXISTS idx_ref_status ON svrt_reference(eol_status);
    CREATE INDEX IF NOT EXISTS idx_queue_status ON svrt_research_queue(status, priority);
    CREATE INDEX IF NOT EXISTS idx_cost_date ON svrt_api_cost_log(call_date);
    """)
    conn.commit()
    log.info("Database initialized at %s", DB_PATH)


# ── Lookup Key ────────────────────────────────────────────────────────────────

def make_lookup_key(vendor, product, version=''):
    """Canonical lookup key: sha256 prefix of vendor:product:major_version."""
    major = re.match(r'^(\d+)', str(version or ''))
    major = major.group(1) if major else ''
    raw = f"{vendor.lower().strip()}:{product.lower().strip()}:{major}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16] + f":{product.lower()[:40]}"


def normalize_product_name(name):
    """Strip version numbers and common suffixes for lookup."""
    name = re.sub(r'\s+\d[\d.x-]*$', '', name.strip())
    name = re.sub(r'\s+(CE|EE|SE|Pro|Enterprise|Community|Edition)$', '', name, flags=re.I)
    return name.strip()


# ── Reference DB Operations ───────────────────────────────────────────────────

def lookup_local(conn, vendor, product, version):
    """Check local DB first. Returns row dict or None."""
    key = make_lookup_key(vendor, product, version)
    row = conn.execute(
        "SELECT * FROM svrt_reference WHERE lookup_key=?", (key,)
    ).fetchone()

    if not row:
        return None

    # Check TTL
    expires = row['expires_at']
    if expires and datetime.fromisoformat(expires) < datetime.utcnow():
        log.debug("Cache expired for %s", key)
        return None

    # Increment hit count
    conn.execute("UPDATE svrt_reference SET hit_count=hit_count+1 WHERE id=?", (row['id'],))
    conn.commit()
    return dict(row)


def save_result(conn, vendor, product, version, platform, result):
    """Upsert a resolved result into the reference DB."""
    key    = make_lookup_key(vendor, product, version)
    status = result.get('eol_status', 'unknown')

    # Determine TTL
    if status == 'eol':
        ttl = TTL_EOL_FACT
    elif status in ('supported', 'lts'):
        ttl = TTL_SUPPORTED
    else:
        ttl = TTL_UNKNOWN

    now     = datetime.utcnow().isoformat()
    expires = (datetime.utcnow() + timedelta(days=ttl)).isoformat()

    conn.execute("""
        INSERT INTO svrt_reference
            (lookup_key, software_name, vendor, version, platform,
             eol_status, eol_date, latest_version, latest_source_url,
             confidence, source, notes, hit_count, created_at, checked_at, expires_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)
        ON CONFLICT(lookup_key) DO UPDATE SET
            eol_status=excluded.eol_status,
            eol_date=excluded.eol_date,
            latest_version=excluded.latest_version,
            latest_source_url=excluded.latest_source_url,
            confidence=excluded.confidence,
            source=excluded.source,
            notes=excluded.notes,
            checked_at=excluded.checked_at,
            expires_at=excluded.expires_at,
            hit_count=svrt_reference.hit_count+1
    """, (
        key, product, vendor, version, platform,
        status,
        result.get('eol_date', ''),
        result.get('latest_version', ''),
        result.get('source_url', ''),
        result.get('confidence', 0),
        result.get('source', 'unknown'),
        result.get('notes', ''),
        now, now, expires,
    ))
    conn.commit()


# ── Lookup Chain ──────────────────────────────────────────────────────────────

def query_endoflife_date(product_name):
    """
    Step 2: Query endoflife.date API.
    Returns dict with eol_status, eol_date, latest_version, confidence, source.
    """
    # Normalize to slug format used by endoflife.date
    slug = product_name.lower()
    slug = re.sub(r'[^a-z0-9-]', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')

    url = f"{EOL_DATE_API}/{slug}.json"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'SVRT-Agent/1.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # product not in endoflife.date
        log.warning("endoflife.date HTTP %d for %s", e.code, slug)
        return None
    except Exception as e:
        log.warning("endoflife.date error for %s: %s", slug, e)
        return None

    if not data:
        return None

    # data is a list of cycles; find the most recently released / relevant
    # Sort by releaseDate descending to get latest cycle
    try:
        cycles = sorted(
            data,
            key=lambda c: c.get('releaseDate') or '1970-01-01',
            reverse=True
        )
        latest = cycles[0]
        # Check if EOL
        eol_val = latest.get('eol', False)
        if eol_val is True or (isinstance(eol_val, str) and eol_val < date.today().isoformat()):
            status = 'eol'
        elif eol_val is False:
            status = 'supported'
        else:
            # Future date — still supported
            status = 'supported'

        # LTS check
        if latest.get('lts'):
            status = 'lts'

        return {
            'eol_status':      status,
            'eol_date':        eol_val if isinstance(eol_val, str) else '',
            'latest_version':  str(latest.get('latest') or latest.get('cycle') or ''),
            'source_url':      f"https://endoflife.date/{slug}",
            'confidence':      CONF_ENDOFLIFE_DATE,
            'source':          'endoflife.date',
            'notes':           f"Cycle: {latest.get('cycle')}",
        }
    except Exception as e:
        log.warning("endoflife.date parse error for %s: %s", slug, e)
        return None


def query_claude(vendor, product, version, platform, conn=None):
    """
    Step 3: Ask Claude Haiku about EOL status.
    Returns dict with eol_status, eol_date, latest_version, confidence, source.
    Logs token usage and cost to svrt_api_cost_log if conn is provided.
    """
    if not CLAUDE_KEY:
        log.warning("ANTHROPIC_API_KEY not set; skipping Claude lookup")
        return None

    prompt = f"""You are a software version lifecycle expert. Answer ONLY with a JSON object.

Product: {product}
Vendor: {vendor}
Version: {version}
Platform: {platform}

Respond with exactly this JSON (no other text):
{{
  "eol_status": "eol|supported|lts|unknown|no_patch",
  "eol_date": "YYYY-MM-DD or empty string",
  "latest_stable_version": "version string or empty",
  "source_url": "URL of official lifecycle page or empty",
  "confidence": 50,
  "notes": "brief explanation"
}}

Rules:
- eol = officially end of life or end of support
- no_patch = no security patches released for 12+ months but no official EOL
- lts = long term support (still receiving patches)
- supported = currently supported
- unknown = cannot determine with high confidence
- confidence: 30-80 based on how certain you are
- Only use data you are highly confident about. When uncertain, use "unknown"."""

    try:
        payload = json.dumps({
            'model': CLAUDE_MODEL,
            'max_tokens': 300,
            'messages': [{'role': 'user', 'content': prompt}]
        }).encode()

        req = urllib.request.Request(
            CLAUDE_API,
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'x-api-key': CLAUDE_KEY,
                'anthropic-version': '2023-06-01',
            }
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_data = json.loads(resp.read())

        # ── Token usage + cost logging ─────────────────────────────────────
        usage         = resp_data.get('usage', {})
        input_tokens  = usage.get('input_tokens', 0)
        output_tokens = usage.get('output_tokens', 0)
        cost_usd      = (input_tokens  / 1_000_000 * CLAUDE_INPUT_COST_PER_M +
                         output_tokens / 1_000_000 * CLAUDE_OUTPUT_COST_PER_M)
        log.debug("Claude tokens: in=%d out=%d cost=$%.5f", input_tokens, output_tokens, cost_usd)

        content = resp_data['content'][0]['text'].strip()
        # Extract JSON from response
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if not m:
            log.warning("Claude returned no JSON for %s", product)
            return None

        result = json.loads(m.group(0))
        eol_status = result.get('eol_status', 'unknown')

        # Log cost to DB
        if conn:
            try:
                conn.execute("""
                    INSERT INTO svrt_api_cost_log
                        (model, input_tokens, output_tokens, cost_usd, product_name, result_status)
                    VALUES (?,?,?,?,?,?)
                """, (CLAUDE_MODEL, input_tokens, output_tokens, cost_usd, product, eol_status))
                conn.commit()
            except Exception:
                pass

        return {
            'eol_status':      eol_status,
            'eol_date':        result.get('eol_date', ''),
            'latest_version':  result.get('latest_stable_version', ''),
            'source_url':      result.get('source_url', ''),
            'confidence':      min(80, max(30, int(result.get('confidence', 50)))),
            'source':          'claude',
            'notes':           result.get('notes', ''),
        }
    except Exception as e:
        log.warning("Claude API error for %s: %s", product, e)
        return None


def resolve(conn, vendor, product, version, platform='linux', force=False):
    """
    Full 3-step lookup chain.
    Returns result dict. Saves to DB. Updates research queue.
    """
    product_norm = normalize_product_name(product)

    # Step 1: Local DB cache
    if not force:
        cached = lookup_local(conn, vendor, product_norm, version)
        if cached:
            log.debug("Cache hit: %s", product_norm)
            return cached

    # Step 2: endoflife.date
    result = query_endoflife_date(product_norm)
    if result:
        log.info("✓ endoflife.date: %s → %s", product_norm, result['eol_status'])
        save_result(conn, vendor, product_norm, version, platform, result)
        return result

    # Step 3: Claude API
    result = query_claude(vendor, product_norm, version, platform, conn=conn)
    if result:
        log.info("✓ Claude: %s → %s (conf=%d)", product_norm, result['eol_status'], result['confidence'])
        save_result(conn, vendor, product_norm, version, platform, result)
        return result

    # Nothing found — store unknown
    result = {
        'eol_status':  'unknown',
        'eol_date':    '',
        'latest_version': '',
        'source_url':  '',
        'confidence':  0,
        'source':      'none',
        'notes':       'No data found in any source',
    }
    save_result(conn, vendor, product_norm, version, platform, result)
    return result


# ── CSV Import ────────────────────────────────────────────────────────────────

def import_csv(conn, csv_path, batch_size=100):
    """
    Import a SVRT inventory CSV into the research queue.
    Deduplicates by lookup_key. Prioritizes by hit_count in reference DB.
    """
    log.info("Importing CSV: %s", csv_path)
    added = skipped = 0

    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        batch = []

        for row in reader:
            vendor   = row.get('vendor', '')
            product  = row.get('software_name', row.get('filename', ''))
            version  = row.get('version', '')
            platform = row.get('platform', 'unknown')
            hostname = row.get('hostname_hash', '')
            scan_date = row.get('scan_date', '')

            if not product:
                continue

            product_norm = normalize_product_name(product)
            key = make_lookup_key(vendor, product_norm, version)

            # Record field submission
            conn.execute("""
                INSERT OR IGNORE INTO svrt_field_submissions
                    (lookup_key, software_name, vendor, version, platform, hostname_hash, scan_date)
                VALUES (?,?,?,?,?,?,?)
            """, (key, product_norm, vendor, version, platform, hostname, scan_date))

            # Add to research queue if not already done
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO svrt_research_queue
                        (lookup_key, software_name, vendor, version, platform, priority)
                    VALUES (?,?,?,?,?,5)
                """, (key, product_norm, vendor, version, platform))
                added += 1
            except Exception:
                skipped += 1

        conn.commit()

    log.info("CSV import: %d queued, %d skipped (already known)", added, skipped)
    return added


# ── Research Run ──────────────────────────────────────────────────────────────

def run_research(conn, max_items=200, delay_sec=0.5):
    """
    Process pending items from the research queue.
    Runs endoflife.date first (free), Claude as fallback.
    """
    log.info("Starting research run (max=%d items)", max_items)

    items = conn.execute("""
        SELECT * FROM svrt_research_queue
        WHERE status='pending'
        ORDER BY priority ASC, id ASC
        LIMIT ?
    """, (max_items,)).fetchall()

    if not items:
        log.info("Research queue is empty.")
        return

    api_calls = 0
    resolved  = 0
    unknown   = 0

    for item in items:
        key      = item['lookup_key']
        product  = item['software_name']
        vendor   = item['vendor'] or ''
        version  = item['version'] or ''
        platform = item['platform'] or 'unknown'

        # Mark in-progress
        conn.execute("""
            UPDATE svrt_research_queue
            SET status='in_progress', last_attempt=datetime('now'), attempts=attempts+1
            WHERE lookup_key=?
        """, (key,))
        conn.commit()

        # Check local cache first (fast path)
        cached = lookup_local(conn, vendor, product, version)
        if cached and cached.get('eol_status') != 'unknown':
            conn.execute("UPDATE svrt_research_queue SET status='done' WHERE lookup_key=?", (key,))
            conn.commit()
            resolved += 1
            continue

        # Step 2: endoflife.date (free, no delay needed)
        result = query_endoflife_date(product)
        if result:
            save_result(conn, vendor, product, version, platform, result)
            conn.execute("UPDATE svrt_research_queue SET status='done' WHERE lookup_key=?", (key,))
            conn.commit()
            resolved += 1
            time.sleep(0.2)  # gentle rate limit
            continue

        # Step 3: Claude (costs money — only if key is set)
        if CLAUDE_KEY and item['attempts'] <= 2:
            api_calls += 1
            result = query_claude(vendor, product, version, platform, conn=conn)
            if result:
                save_result(conn, vendor, product, version, platform, result)
                conn.execute("UPDATE svrt_research_queue SET status='done' WHERE lookup_key=?", (key,))
                conn.commit()
                resolved += 1
                time.sleep(delay_sec)
                continue

        # Unknown — mark done with unknown status
        save_result(conn, vendor, product, version, platform, {
            'eol_status': 'unknown', 'confidence': 0, 'source': 'none',
            'eol_date': '', 'latest_version': '', 'source_url': '',
            'notes': 'No data found',
        })
        conn.execute("UPDATE svrt_research_queue SET status='done' WHERE lookup_key=?", (key,))
        conn.commit()
        unknown += 1

    # Log run stats
    conn.execute("""
        INSERT INTO svrt_agent_log (run_date, phase, items_in, items_out, api_calls, notes)
        VALUES (datetime('now'), 'research', ?, ?, ?, ?)
    """, (len(items), resolved, api_calls, f"unknown={unknown}"))
    conn.commit()

    log.info("Research run complete: %d resolved, %d unknown, %d API calls", resolved, unknown, api_calls)


# ── Sync to IONOS ─────────────────────────────────────────────────────────────

def push_to_ionos():
    """Run the IONOS sync shell script."""
    if not SYNC_SCRIPT.exists():
        log.warning("Sync script not found: %s", SYNC_SCRIPT)
        return False
    import subprocess
    result = subprocess.run(['bash', str(SYNC_SCRIPT)], capture_output=True, text=True)
    if result.returncode == 0:
        log.info("Sync to IONOS: SUCCESS\n%s", result.stdout[:500])
        return True
    else:
        log.error("Sync to IONOS: FAILED\n%s", result.stderr[:500])
        return False


# ── Status ────────────────────────────────────────────────────────────────────

def print_status(conn):
    """Print DB statistics to stdout."""
    ref_count = conn.execute("SELECT COUNT(*) FROM svrt_reference").fetchone()[0]
    queue_pending = conn.execute(
        "SELECT COUNT(*) FROM svrt_research_queue WHERE status='pending'"
    ).fetchone()[0]
    queue_done = conn.execute(
        "SELECT COUNT(*) FROM svrt_research_queue WHERE status='done'"
    ).fetchone()[0]
    submissions = conn.execute("SELECT COUNT(*) FROM svrt_field_submissions").fetchone()[0]

    status_counts = conn.execute("""
        SELECT eol_status, COUNT(*) as cnt
        FROM svrt_reference GROUP BY eol_status ORDER BY cnt DESC
    """).fetchall()

    source_counts = conn.execute("""
        SELECT source, COUNT(*) as cnt
        FROM svrt_reference GROUP BY source ORDER BY cnt DESC
    """).fetchall()

    top_hits = conn.execute("""
        SELECT software_name, version, eol_status, hit_count, source
        FROM svrt_reference ORDER BY hit_count DESC LIMIT 10
    """).fetchall()

    print(f"\n{'═'*55}")
    print(f"  SVRT Reference Database Status")
    print(f"{'═'*55}")
    print(f"  DB path        : {DB_PATH}")
    print(f"  DB size        : {DB_PATH.stat().st_size / 1024:.1f} KB" if DB_PATH.exists() else "  DB: not found")
    print(f"\n  Reference rows : {ref_count:,}")
    print(f"  Field subs     : {submissions:,}")
    print(f"  Queue pending  : {queue_pending:,}")
    print(f"  Queue done     : {queue_done:,}")

    print(f"\n  EOL Status Breakdown:")
    for r in status_counts:
        bar = '█' * min(30, r['cnt'] // max(1, ref_count // 30))
        print(f"    {r['eol_status']:<12}: {r['cnt']:>6,}  {bar}")

    print(f"\n  By Source:")
    for r in source_counts:
        print(f"    {r['source']:<20}: {r['cnt']:>6,}")

    if top_hits:
        print(f"\n  Most Queried (top 10):")
        for r in top_hits:
            print(f"    [{r['eol_status']:<9}] {r['software_name']:<25} v{r['version']:<10} ({r['source']})")

    last_run = conn.execute(
        "SELECT * FROM svrt_agent_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if last_run:
        print(f"\n  Last Run: {last_run['run_date']}  →  {last_run['items_out']} resolved, "
              f"{last_run['api_calls']} API calls")

    # ── API Cost Summary ──────────────────────────────────────────────────
    cost_today = conn.execute("""
        SELECT COUNT(*) as calls, SUM(input_tokens) as total_in,
               SUM(output_tokens) as total_out, SUM(cost_usd) as total_cost
        FROM svrt_api_cost_log WHERE call_date=date('now')
    """).fetchone()
    cost_month = conn.execute("""
        SELECT COUNT(*) as calls, SUM(cost_usd) as total_cost
        FROM svrt_api_cost_log
        WHERE call_date >= date('now','start of month')
    """).fetchone()
    cost_alltime = conn.execute("""
        SELECT COUNT(*) as calls, SUM(cost_usd) as total_cost
        FROM svrt_api_cost_log
    """).fetchone()

    if cost_alltime and cost_alltime['calls']:
        print(f"\n  Claude API Cost (model: {CLAUDE_MODEL})")
        print(f"  {'─'*50}")
        if cost_today and cost_today['calls']:
            print(f"  Today          : {cost_today['calls']:>5} calls  "
                  f"${cost_today['total_cost']:.4f}  "
                  f"({(cost_today['total_in'] or 0) + (cost_today['total_out'] or 0):,} tokens)")
        if cost_month and cost_month['calls']:
            print(f"  This month     : {cost_month['calls']:>5} calls  "
                  f"${cost_month['total_cost']:.4f}")
        print(f"  All time       : {cost_alltime['calls']:>5} calls  "
              f"${cost_alltime['total_cost']:.4f}")
        # Queue cost estimate
        q_remaining = conn.execute(
            "SELECT COUNT(*) FROM svrt_research_queue WHERE status='pending'"
        ).fetchone()[0]
        avg_cost = cost_alltime['total_cost'] / cost_alltime['calls'] if cost_alltime['calls'] else 0.00056
        est_remaining = q_remaining * avg_cost
        print(f"  Queue remaining: {q_remaining:>5} items  ~${est_remaining:.2f} est.")

    print(f"{'═'*55}\n")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='SVRT Research Agent v1.0')
    parser.add_argument('--status',      action='store_true', help='Print DB stats and exit')
    parser.add_argument('--lookup',      metavar='PRODUCT',   help='Look up a single product')
    parser.add_argument('--import-csv',  metavar='FILE',      help='Import inventory CSV into queue')
    parser.add_argument('--sync',        action='store_true', help='Push DB to IONOS now')
    parser.add_argument('--max',         type=int, default=200, help='Max items per research run')
    parser.add_argument('--delay',       type=float, default=0.5, help='Seconds between Claude calls')
    parser.add_argument('--force',       action='store_true', help='Bypass cache (re-research all)')
    args = parser.parse_args()

    conn = get_db()
    init_db(conn)

    if args.status:
        print_status(conn)
        return

    if args.lookup:
        result = resolve(conn, '', args.lookup, '', force=args.force)
        print(json.dumps(result, indent=2))
        return

    if args.import_csv:
        import_csv(conn, args.import_csv)
        return

    if args.sync:
        push_to_ionos()
        return

    # Default: full research run
    log.info("SVRT Agent starting — %s", datetime.utcnow().isoformat())
    run_research(conn, max_items=args.max, delay_sec=args.delay)
    print_status(conn)


if __name__ == '__main__':
    main()
