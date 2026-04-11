#!/usr/bin/env python3
"""
SVRT Research Agent — Raspberry Pi
Ask McConnell's Software Version Reference Tool

Runs locally on the Pi. Queries endoflife.date, then uses a multi-LLM
consensus engine (Claude Haiku + GPT-4o-mini + Gemini Flash in parallel,
Grok as optional tiebreaker) to populate the reference database.

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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta
from pathlib import Path
import threading
_db_write_lock = threading.Lock()

try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

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
OPENAI_KEY   = os.environ.get('OPENAI_API_KEY', '')
GOOGLE_KEY   = os.environ.get('GOOGLE_API_KEY', '')
XAI_KEY      = os.environ.get('XAI_API_KEY', '')        # Grok — tiebreaker, optional

EOL_DATE_API  = 'https://endoflife.date/api'
CLAUDE_API    = 'https://api.anthropic.com/v1/messages'
OPENAI_API    = 'https://api.openai.com/v1/chat/completions'
GEMINI_API    = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'
XAI_API       = 'https://api.x.ai/v1/chat/completions'
CLAUDE_MODEL  = 'claude-haiku-4-5'
OPENAI_MODEL  = 'gpt-4o-mini'
GEMINI_MODEL  = 'gemini-2.5-flash'
XAI_MODEL     = 'grok-3-mini'
GITHUB_TOKEN  = os.environ.get('GITHUB_TOKEN', '')
GITHUB_API    = 'https://api.github.com'
REPOLOGY_API  = 'https://repology.org/api/v1/project'

GITHUB_REPO   = 'askmcconnell/software-version-reference-tool'
GITHUB_YAML_PATH = 'reference-db/products'

# Pricing per million tokens (input / output)
CLAUDE_INPUT_COST_PER_M  = 0.80;  CLAUDE_OUTPUT_COST_PER_M  = 4.00
OPENAI_INPUT_COST_PER_M  = 0.15;  OPENAI_OUTPUT_COST_PER_M  = 0.60
GEMINI_INPUT_COST_PER_M  = 0.075; GEMINI_OUTPUT_COST_PER_M  = 0.30
XAI_INPUT_COST_PER_M     = 0.30;  XAI_OUTPUT_COST_PER_M     = 0.50

# Lookup chain confidence scores
CONF_ENDOFLIFE_DATE = 85
CONF_GITHUB         = 72   # GitHub archived/activity signal
CONF_REPOLOGY       = 70   # Repology cross-distro package signal
CONF_CLAUDE         = 60
CONF_MANUAL         = 95
CONF_CONSENSUS_3    = 92   # all 3 LLMs agree
CONF_CONSENSUS_2    = 82   # 2 of 3 LLMs agree
CONF_COMMUNITY      = 90   # GitHub YAML community entries

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
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
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


def _gh_headers():
    """Build GitHub API request headers, with auth token if available."""
    h = {'User-Agent': 'SVRT-Agent/1.0', 'Accept': 'application/vnd.github+json'}
    if GITHUB_TOKEN:
        h['Authorization'] = f'Bearer {GITHUB_TOKEN}'
    return h


def _normalize_pkg_name(name):
    """Normalize a package/product name for fuzzy comparison."""
    n = name.lower().strip()
    n = re.sub(r'^lib', '', n)           # strip lib prefix (libgif → gif)
    n = re.sub(r'[-_\s\.]+', '', n)      # strip separators
    n = re.sub(r'\d+$', '', n)           # strip trailing version numbers (python3 → python)
    return n


def _name_match_score(search_name, repo_name):
    """Return 0.0–1.0 similarity between a product name and a GitHub repo name."""
    a = _normalize_pkg_name(search_name)
    b = _normalize_pkg_name(repo_name)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    # Allow one to be a prefix of the other (min 3 chars)
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 3 and longer.startswith(shorter):
        return 0.75
    return 0.0


def query_github(vendor, product, version, platform, conn=None):
    """
    Step 2.5a: GitHub repo activity check.
    Searches GitHub for the best-matching repo, then interprets:
      - archived=True          → no_patch (conf=72)
      - pushed_at > 2 years    → no_patch (conf=65)
      - pushed_at 1–2 years    → no_patch (conf=55)
      - active (< 1 year)      → supported (conf=62), pulls latest release version
    Returns result dict or None if no reliable signal.
    """
    try:
        # Build search query: prefer vendor-qualified if vendor looks like an org name
        q = product
        if vendor and len(vendor) > 2:
            q = f'{product}+{vendor}'
        q = urllib.parse.quote_plus(q)
        url = f'{GITHUB_API}/search/repositories?q={q}+in:name&sort=stars&order=desc&per_page=10'
        req = urllib.request.Request(url, headers=_gh_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        items = data.get('items', [])
        if not items:
            return None

        # Keywords that identify distro packaging repos — not the upstream project
        _PACKAGING_OWNER_KEYWORDS = (
            'packages', 'packaging', 'ports', 'overlay', 'pkgs', 'pkg',
            'homebrew', 'aur', 'flatpak', 'snap', 'copr', 'ppa', 'rpm',
            'debian', 'ubuntu', 'fedora', 'solus', 'void', 'alpine',
            'gentoo', 'nixpkgs', 'archlinux',
        )

        # Find best name match among credible repos
        best_repo = None
        best_score = 0.0
        for repo in items:
            score = _name_match_score(product, repo['name'])
            if score <= best_score:
                continue
            # Skip packaging/distro repos — they reflect packaging activity, not the project
            owner = repo.get('owner', {}).get('login', '').lower()
            if any(kw in owner for kw in _PACKAGING_OWNER_KEYWORDS):
                log.debug("GitHub: skipping packaging repo %s", repo['full_name'])
                continue
            # Require minimum star count to filter out personal forks/clones
            # Exception: archived repos are useful signal regardless of stars
            if repo.get('stargazers_count', 0) < 50 and not repo.get('archived', False):
                log.debug("GitHub: skipping low-star repo %s (%d stars)",
                          repo['full_name'], repo.get('stargazers_count', 0))
                continue
            best_score = score
            best_repo = repo

        if best_score < 0.75 or not best_repo:
            log.debug("GitHub: no credible repo match for '%s' (best=%.2f)", product, best_score)
            return None

        repo_url    = best_repo['html_url']
        archived    = best_repo.get('archived', False)
        disabled    = best_repo.get('disabled', False)
        pushed_raw  = best_repo.get('pushed_at', '')
        owner_repo  = best_repo['full_name']

        if archived or disabled:
            log.info("GitHub: %s repo '%s' is archived/disabled → no_patch", product, owner_repo)
            return {
                'eol_status':     'no_patch',
                'eol_date':       '',
                'latest_version': version,
                'source_url':     repo_url,
                'confidence':     CONF_GITHUB,
                'source':         'github',
                'notes':          f'GitHub repo {owner_repo} is archived/disabled — no active maintenance.',
            }

        # Determine age of last push
        if pushed_raw:
            try:
                pushed_dt = datetime.strptime(pushed_raw[:10], '%Y-%m-%d')
                age_days  = (datetime.utcnow() - pushed_dt).days
            except Exception:
                age_days = 0
        else:
            age_days = 0

        # Try to get latest release version
        latest_ver = ''
        try:
            rel_url = f'{GITHUB_API}/repos/{owner_repo}/releases/latest'
            rel_req = urllib.request.Request(rel_url, headers=_gh_headers())
            with urllib.request.urlopen(rel_req, timeout=8) as rel_resp:
                rel_data = json.loads(rel_resp.read())
            tag = rel_data.get('tag_name', '')
            # Strip leading 'v' from tag names
            latest_ver = re.sub(r'^v', '', tag, flags=re.IGNORECASE)
        except Exception:
            pass

        if age_days > 730:  # > 2 years since last push
            conf = 65 if age_days > 1095 else 55   # > 3yr = 65, 2–3yr = 55
            log.info("GitHub: %s repo '%s' last pushed %d days ago → no_patch (conf=%d)",
                     product, owner_repo, age_days, conf)
            return {
                'eol_status':     'no_patch',
                'eol_date':       '',
                'latest_version': latest_ver or version,
                'source_url':     repo_url,
                'confidence':     conf,
                'source':         'github',
                'notes':          f'GitHub repo {owner_repo} last pushed {age_days} days ago — no recent activity.',
            }

        # Active repo
        log.info("GitHub: %s repo '%s' active (%d days) → supported (conf=62)", product, owner_repo, age_days)
        return {
            'eol_status':     'supported',
            'eol_date':       '',
            'latest_version': latest_ver or version,
            'source_url':     repo_url,
            'confidence':     62,
            'source':         'github',
            'notes':          f'GitHub repo {owner_repo} actively maintained (last push {age_days} days ago).',
        }

    except urllib.error.HTTPError as e:
        if e.code == 403:
            log.warning("GitHub: rate limited (403) for %s", product)
        elif e.code != 404:
            log.warning("GitHub HTTP %d for %s", e.code, product)
        return None
    except Exception as e:
        log.debug("GitHub error for %s: %s", product, e)
        return None


# Current distro repo identifiers in Repology (prefix-matched)
_REPOLOGY_CURRENT_REPOS = (
    'debian_12', 'debian_13', 'debian_bookworm', 'debian_trixie',
    'ubuntu_2404', 'ubuntu_2204', 'ubuntu_2310', 'ubuntu_2404',
    'fedora_41', 'fedora_42', 'fedora_40',
    'opensuse_tumbleweed', 'arch', 'alpine_316', 'alpine_320',
    'nixpkgs_stable',
)
_REPOLOGY_OLD_REPOS = (
    'debian_9', 'debian_10', 'debian_11', 'debian_wheezy', 'debian_jessie',
    'debian_stretch', 'debian_buster', 'debian_bullseye',
    'ubuntu_1804', 'ubuntu_2004',
)


def query_repology(vendor, product, version, platform, conn=None):
    """
    Step 2.5b: Repology cross-distro package status.
    Checks if the package exists in current stable Linux distros.
      - In current stable (Debian 12, Ubuntu 22+, Fedora 41+) → supported (conf=70)
      - Only in old/obsolete distros → no_patch (conf=65)
      - Unknown/not found → None
    Rate-limit: 1 req/sec is polite; we add a minimal sleep after each call.
    """
    # Repology is only useful for Linux packages
    if platform and platform.lower() not in ('linux', 'unknown', ''):
        return None

    pkg = product.lower().strip()
    # Repology slugifies names: spaces/underscores → hyphens, lowercase
    pkg_slug = re.sub(r'[\s_]+', '-', pkg)

    # Build list of slugs to try:
    # 1. Exact name (e.g. "libgif")
    # 2. Without leading "lib" (e.g. "giflib", "gif") — many Linux libs use the
    #    source package name which drops the lib prefix
    slugs_to_try = [pkg_slug]
    if pkg_slug.startswith('lib') and len(pkg_slug) > 4:
        stripped = pkg_slug[3:]          # libgif      → gif
        slugs_to_try.append(stripped)
        slugs_to_try.append(stripped + 'lib')   # libgif → giflib (common src pkg pattern)
        # Strip trailing digits too (libgnutls28 → gnutls28 → gnutls)
        stripped_no_digits = re.sub(r'\d+$', '', stripped)
        if stripped_no_digits != stripped:
            slugs_to_try.append(stripped_no_digits)

    packages = None
    used_slug = pkg_slug
    for slug in slugs_to_try:
        url = f'{REPOLOGY_API}/{urllib.parse.quote(slug)}'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'SVRT-Agent/1.0 (https://askmcconnell.com/svrt/)'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                packages = json.loads(resp.read())
            if packages:
                used_slug = slug
                log.debug("Repology: found '%s' under slug '%s'", product, slug)
                break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue   # try next slug
            log.debug("Repology HTTP %d for %s (slug=%s)", e.code, product, slug)
            continue
        except Exception as e:
            log.debug("Repology error for %s: %s", product, e)
            continue

    if not packages:
        return None

    # Filter to packages whose name closely matches our product
    matched = [p for p in packages
               if _name_match_score(product, p.get('name', p.get('srcname', ''))) >= 0.75]
    if not matched:
        matched = packages  # fall back to all if no name match

    # Separate current vs old repo entries
    in_current = [p for p in matched if any(p.get('repo', '').startswith(r) for r in _REPOLOGY_CURRENT_REPOS)]
    in_old_only = [p for p in matched if any(p.get('repo', '').startswith(r) for r in _REPOLOGY_OLD_REPOS)]

    if in_current:
        # Pick the entry with the newest-looking version
        newest = sorted(in_current, key=lambda p: p.get('version', ''), reverse=True)[0]
        latest_ver = newest.get('version', '')
        repo_name  = newest.get('repo', '')
        log.info("Repology: %s found in current repo '%s' → supported (conf=%d)", product, repo_name, CONF_REPOLOGY)
        return {
            'eol_status':     'supported',
            'eol_date':       '',
            'latest_version': latest_ver,
            'source_url':     f'https://repology.org/project/{used_slug}/versions',
            'confidence':     CONF_REPOLOGY,
            'source':         'repology',
            'notes':          f'Package found in {repo_name} (Repology). Version {latest_ver}.',
        }

    if in_old_only and not in_current:
        # Only in old distros — likely abandoned or replaced
        newest = sorted(in_old_only, key=lambda p: p.get('version', ''), reverse=True)[0]
        latest_ver = newest.get('version', '')
        repo_name  = newest.get('repo', '')
        log.info("Repology: %s only in old repos ('%s') → no_patch (conf=65)", product, repo_name)
        return {
            'eol_status':     'no_patch',
            'eol_date':       '',
            'latest_version': latest_ver,
            'source_url':     f'https://repology.org/project/{used_slug}/versions',
            'confidence':     65,
            'source':         'repology',
            'notes':          f'Package only found in older distros ({repo_name}) in Repology — no longer in current stable.',
        }

    return None


def query_precheck(vendor, product, version, platform, conn=None):
    """
    Step 2.5: GitHub + Repology pre-check before LLM fallback.
    Tries GitHub first (works well for open-source projects on any platform),
    then Repology (works well for Linux system packages).
    Returns a result dict, or None if neither source has useful signal.
    """
    # GitHub works for any platform (open-source tools show up regardless)
    gh = query_github(vendor, product, version, platform, conn=conn)
    if gh and gh.get('eol_status') not in ('unknown', None):
        return gh

    # Repology: Linux packages only
    rp = query_repology(vendor, product, version, platform, conn=conn)
    if rp and rp.get('eol_status') not in ('unknown', None):
        return rp

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


def _build_eol_prompt(vendor, product, version, platform):
    return f"""You are a software lifecycle expert. Answer ONLY with a JSON object — no other text.

Product: {product}
Vendor: {vendor}
Version: {version}
Platform: {platform}

Respond with exactly this JSON:
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
- no_patch = no security patches for 12+ months but no official EOL announced
- lts = long term support release (still patched)
- supported = currently supported
- unknown = cannot determine with high confidence
- confidence: 30-80 based on certainty. Use "unknown" when unsure."""


def _parse_llm_json(text):
    """Extract and parse the JSON object from an LLM response string.
    Handles plain JSON, markdown fences (```json...```), and extra prose."""
    # Strip markdown code fences if present
    text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.IGNORECASE)
    text = re.sub(r'\s*```$', '', text.strip())
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _log_api_cost(conn, model, input_tokens, output_tokens, cost_usd, product, status):
    if not conn:
        return
    try:
        with _db_write_lock:
            conn.execute("""
                INSERT INTO svrt_api_cost_log
                    (model, input_tokens, output_tokens, cost_usd, product_name, result_status)
                VALUES (?,?,?,?,?,?)
            """, (model, input_tokens, output_tokens, cost_usd, product, status))
            conn.commit()
    except Exception:
        pass


def query_openai(vendor, product, version, platform, conn=None):
    """Query GPT-4o-mini for EOL status."""
    if not OPENAI_KEY:
        return None
    prompt = _build_eol_prompt(vendor, product, version, platform)
    try:
        payload = json.dumps({
            'model': OPENAI_MODEL,
            'max_tokens': 300,
            'messages': [{'role': 'user', 'content': prompt}],
        }).encode()
        req = urllib.request.Request(OPENAI_API, data=payload, headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {OPENAI_KEY}',
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        usage        = data.get('usage', {})
        in_tok       = usage.get('prompt_tokens', 0)
        out_tok      = usage.get('completion_tokens', 0)
        cost         = in_tok / 1_000_000 * OPENAI_INPUT_COST_PER_M + out_tok / 1_000_000 * OPENAI_OUTPUT_COST_PER_M
        text         = data['choices'][0]['message']['content'].strip()
        result       = _parse_llm_json(text)
        if not result:
            return None
        status = result.get('eol_status', 'unknown')
        _log_api_cost(conn, OPENAI_MODEL, in_tok, out_tok, cost, product, status)
        return {
            'eol_status':     status,
            'eol_date':       result.get('eol_date', ''),
            'latest_version': result.get('latest_stable_version', ''),
            'source_url':     result.get('source_url', ''),
            'confidence':     min(80, max(30, int(result.get('confidence', 50)))),
            'source':         'openai',
            'notes':          result.get('notes', ''),
        }
    except Exception as e:
        log.warning("OpenAI error for %s: %s", product, e)
        return None


def query_gemini(vendor, product, version, platform, conn=None):
    """Query Gemini Flash for EOL status."""
    if not GOOGLE_KEY:
        return None
    prompt = _build_eol_prompt(vendor, product, version, platform)
    url = f"{GEMINI_API}?key={GOOGLE_KEY}"
    try:
        payload = json.dumps({
            'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': {'maxOutputTokens': 600, 'temperature': 0.1},
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        usage   = data.get('usageMetadata', {})
        in_tok  = usage.get('promptTokenCount', 0)
        out_tok = usage.get('candidatesTokenCount', 0)
        cost    = in_tok / 1_000_000 * GEMINI_INPUT_COST_PER_M + out_tok / 1_000_000 * GEMINI_OUTPUT_COST_PER_M
        text    = data['candidates'][0]['content']['parts'][0]['text'].strip()
        result  = _parse_llm_json(text)
        if not result:
            return None
        status = result.get('eol_status', 'unknown')
        _log_api_cost(conn, GEMINI_MODEL, in_tok, out_tok, cost, product, status)
        return {
            'eol_status':     status,
            'eol_date':       result.get('eol_date', ''),
            'latest_version': result.get('latest_stable_version', ''),
            'source_url':     result.get('source_url', ''),
            'confidence':     min(80, max(30, int(result.get('confidence', 50)))),
            'source':         'gemini',
            'notes':          result.get('notes', ''),
        }
    except Exception as e:
        log.warning("Gemini error for %s: %s", product, e)
        return None


def query_xai(vendor, product, version, platform, conn=None):
    """Query Grok as a tiebreaker — only called when 3-way consensus fails."""
    if not XAI_KEY:
        return None
    prompt = _build_eol_prompt(vendor, product, version, platform)
    try:
        payload = json.dumps({
            'model': XAI_MODEL,
            'max_tokens': 300,
            'messages': [{'role': 'user', 'content': prompt}],
        }).encode()
        req = urllib.request.Request(XAI_API, data=payload, headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {XAI_KEY}',
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        usage   = data.get('usage', {})
        in_tok  = usage.get('prompt_tokens', 0)
        out_tok = usage.get('completion_tokens', 0)
        cost    = in_tok / 1_000_000 * XAI_INPUT_COST_PER_M + out_tok / 1_000_000 * XAI_OUTPUT_COST_PER_M
        text    = data['choices'][0]['message']['content'].strip()
        result  = _parse_llm_json(text)
        if not result:
            return None
        status = result.get('eol_status', 'unknown')
        _log_api_cost(conn, XAI_MODEL, in_tok, out_tok, cost, product, status)
        return {
            'eol_status':     status,
            'eol_date':       result.get('eol_date', ''),
            'latest_version': result.get('latest_stable_version', ''),
            'source_url':     result.get('source_url', ''),
            'confidence':     min(80, max(30, int(result.get('confidence', 50)))),
            'source':         'xai',
            'notes':          result.get('notes', ''),
        }
    except Exception as e:
        log.warning("Grok error for %s: %s", product, e)
        return None


def run_consensus(vendor, product, version, platform, conn=None):
    """
    Query Claude, OpenAI, and Gemini in parallel.
    Apply majority vote on eol_status:
      3/3 agree → confidence CONF_CONSENSUS_3 (92), source='consensus'
      2/3 agree → confidence CONF_CONSENSUS_2 (82), source='consensus'
      0/3 agree → Grok tiebreaker if available, else best single result
    Returns result dict or None if all queries failed.
    """
    callers = {
        'claude': lambda: query_claude(vendor, product, version, platform, conn=conn),
        'openai': lambda: query_openai(vendor, product, version, platform, conn=conn),
        'gemini': lambda: query_gemini(vendor, product, version, platform, conn=conn),
    }

    results = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(fn): name for name, fn in callers.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as e:
                log.warning("Consensus worker %s raised: %s", name, e)
                results[name] = None

    valid = {name: r for name, r in results.items() if r and r.get('eol_status') not in ('unknown', None)}
    if not valid:
        log.info("Consensus: all LLMs returned unknown for %s", product)
        return None

    # Count votes per eol_status
    from collections import Counter
    vote_counts = Counter(r['eol_status'] for r in valid.values())
    top_status, top_count = vote_counts.most_common(1)[0]

    if top_count >= 2:
        conf = CONF_CONSENSUS_3 if top_count == 3 else CONF_CONSENSUS_2
        # Aggregate: pick best source_url and eol_date from agreeing results
        agreeing = [r for r in valid.values() if r['eol_status'] == top_status]
        best = max(agreeing, key=lambda r: r.get('confidence', 0))
        voters = [name for name, r in valid.items() if r and r['eol_status'] == top_status]
        log.info("✓ Consensus (%d/3): %s → %s (conf=%d) [%s]",
                 top_count, product, top_status, conf, ', '.join(voters))
        return {
            'eol_status':     top_status,
            'eol_date':       best.get('eol_date', ''),
            'latest_version': best.get('latest_version', ''),
            'source_url':     best.get('source_url', ''),
            'confidence':     conf,
            'source':         'consensus',
            'notes':          f"{top_count}/3 LLMs agree ({', '.join(voters)}). {best.get('notes', '')}".strip(),
        }

    # No majority — try Grok as tiebreaker
    log.info("No 3-LLM consensus for %s — trying Grok tiebreaker", product)
    grok = query_xai(vendor, product, version, platform, conn=conn)
    if grok and grok.get('eol_status') not in ('unknown', None):
        # Check if Grok breaks the tie
        grok_status = grok['eol_status']
        grok_votes  = vote_counts.get(grok_status, 0) + 1
        if grok_votes >= 2:
            agreeing = [r for r in valid.values() if r and r['eol_status'] == grok_status] + [grok]
            best = max(agreeing, key=lambda r: r.get('confidence', 0))
            log.info("✓ Grok broke the tie: %s → %s", product, grok_status)
            return {
                'eol_status':     grok_status,
                'eol_date':       best.get('eol_date', ''),
                'latest_version': best.get('latest_version', ''),
                'source_url':     best.get('source_url', ''),
                'confidence':     CONF_CONSENSUS_2,
                'source':         'consensus',
                'notes':          f"Grok tiebreaker agreed with one LLM. {best.get('notes', '')}".strip(),
            }

    # All 3 disagree and no tiebreaker — fall back to highest-confidence single result
    all_valid = list(valid.values())
    if grok and grok.get('eol_status') not in ('unknown', None):
        all_valid.append(grok)
    best = max(all_valid, key=lambda r: r.get('confidence', 0))
    log.info("No consensus for %s — using best single result: %s (conf=%d)",
             product, best['eol_status'], best.get('confidence', 0))
    return best


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
            # Don't trust a bare unknown (confidence=0, source='none') — fall through
            # so step 2.5 can try GitHub/Repology before giving up again.
            if cached.get('eol_status') == 'unknown' and cached.get('confidence', 0) == 0:
                log.debug("Cache: stale unknown for %s — re-running lookup chain", product_norm)
            else:
                log.debug("Cache hit: %s", product_norm)
                return cached

    # Step 2: endoflife.date
    result = query_endoflife_date(product_norm)
    if result:
        log.info("✓ endoflife.date: %s → %s", product_norm, result['eol_status'])
        save_result(conn, vendor, product_norm, version, platform, result)
        return result

    # Step 2.5: GitHub + Repology pre-check (free APIs, no LLM cost)
    result = query_precheck(vendor, product_norm, version, platform, conn=conn)
    if result:
        log.info("✓ precheck (%s): %s → %s (conf=%d)", result['source'], product_norm,
                 result['eol_status'], result.get('confidence', 0))
        save_result(conn, vendor, product_norm, version, platform, result)
        return result

    # Step 3: Multi-LLM consensus (Claude + GPT-4o-mini + Gemini Flash in parallel)
    result = run_consensus(vendor, product_norm, version, platform, conn=conn)
    if result:
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
    Runs endoflife.date first (free), then multi-LLM consensus as fallback.
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

        # Step 2.5: GitHub + Repology (free APIs, saves LLM calls)
        result = query_precheck(vendor, product, version, platform, conn=conn)
        if result:
            save_result(conn, vendor, product, version, platform, result)
            conn.execute("UPDATE svrt_research_queue SET status='done' WHERE lookup_key=?", (key,))
            conn.commit()
            resolved += 1
            time.sleep(0.5)  # Repology asks for ~1 req/sec politeness
            continue

        # Step 3: Multi-LLM consensus (Claude + OpenAI + Gemini in parallel)
        if item['attempts'] <= 2:
            api_calls += 1
            result = run_consensus(vendor, product, version, platform, conn=conn)
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

    # ── API Cost Summary (all models) ─────────────────────────────────────
    cost_alltime = conn.execute("""
        SELECT COUNT(*) as calls, SUM(cost_usd) as total_cost
        FROM svrt_api_cost_log
    """).fetchone()

    if cost_alltime and cost_alltime['calls']:
        print(f"\n  API Cost — All Models")
        print(f"  {'─'*50}")

        # Per-model breakdown
        model_rows = conn.execute("""
            SELECT model,
                   COUNT(*) as calls,
                   SUM(cost_usd) as total_cost
            FROM svrt_api_cost_log
            GROUP BY model ORDER BY total_cost DESC
        """).fetchall()
        for row in model_rows:
            print(f"  {row['model']:<28}: {row['calls']:>5} calls  ${row['total_cost']:.4f}")

        print(f"  {'─'*50}")

        # Today / month / all-time totals
        cost_today = conn.execute("""
            SELECT COUNT(*) as calls, SUM(cost_usd) as total_cost,
                   SUM(input_tokens) as total_in, SUM(output_tokens) as total_out
            FROM svrt_api_cost_log WHERE call_date=date('now')
        """).fetchone()
        cost_month = conn.execute("""
            SELECT COUNT(*) as calls, SUM(cost_usd) as total_cost
            FROM svrt_api_cost_log WHERE call_date >= date('now','start of month')
        """).fetchone()

        if cost_today and cost_today['calls']:
            print(f"  Today          : {cost_today['calls']:>5} calls  "
                  f"${cost_today['total_cost']:.4f}  "
                  f"({(cost_today['total_in'] or 0) + (cost_today['total_out'] or 0):,} tokens)")
        if cost_month and cost_month['calls']:
            print(f"  This month     : {cost_month['calls']:>5} calls  "
                  f"${cost_month['total_cost']:.4f}")
        print(f"  All time       : {cost_alltime['calls']:>5} calls  "
              f"${cost_alltime['total_cost']:.4f}")

        q_remaining = conn.execute(
            "SELECT COUNT(*) FROM svrt_research_queue WHERE status='pending'"
        ).fetchone()[0]
        avg_cost = cost_alltime['total_cost'] / cost_alltime['calls'] if cost_alltime['calls'] else 0.00056
        print(f"  Queue remaining: {q_remaining:>5} items  ~${q_remaining * avg_cost * 3:.2f} est. (3 LLMs/item, assumes no GitHub/Repology hits)")

    print(f"{'═'*55}\n")


# ── GitHub YAML Reference DB Sync ────────────────────────────────────────────

def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'SVRT-Agent/1.0'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def sync_github_yaml(conn):
    """
    Pull community-curated YAML product files from the GitHub reference-db and
    upsert into svrt_reference at confidence=90 ('github-yaml' source).

    Won't overwrite entries that already have a higher confidence score
    (e.g. manual=95 seeded entries).

    Requires PyYAML:  pip3 install pyyaml
    """
    if not _YAML_AVAILABLE:
        log.error("PyYAML not installed. Run: pip3 install pyyaml")
        return 0

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_YAML_PATH}"
    log.info("Fetching YAML file list from GitHub: %s", api_url)

    try:
        files = fetch_json(api_url)
    except Exception as e:
        log.error("GitHub API error: %s", e)
        return 0

    yaml_files = [f for f in files if f['name'].endswith('.yaml') and f['type'] == 'file']
    log.info("Found %d YAML files in reference-db/products/", len(yaml_files))

    upserted = skipped = errors = 0
    now = datetime.utcnow().isoformat()

    for file_meta in yaml_files:
        raw_url = file_meta['download_url']
        fname   = file_meta['name']

        try:
            req = urllib.request.Request(raw_url, headers={'User-Agent': 'SVRT-Agent/1.0'})
            with urllib.request.urlopen(req, timeout=15) as r:
                raw_text = r.read().decode('utf-8')
            data = _yaml.safe_load(raw_text)
        except Exception as e:
            log.warning("Failed to load %s: %s", fname, e)
            errors += 1
            continue

        software_name = data.get('software_name', '')
        vendor        = data.get('vendor', '')
        platform      = data.get('platform', 'cross-platform')
        versions      = data.get('versions', [])

        if not software_name or not versions:
            log.warning("Skipping %s — missing software_name or versions", fname)
            errors += 1
            continue

        for v in versions:
            major      = str(v.get('major', ''))
            eol_status = v.get('eol_status', '')
            source_url = v.get('source_url', '')
            eol_date   = v.get('eol_date', '')
            latest_ver = v.get('latest_version', '')
            notes      = v.get('notes', '')

            if not eol_status or not source_url:
                continue

            key = make_lookup_key(vendor, software_name, major)

            # Don't overwrite higher-confidence entries
            existing = conn.execute(
                "SELECT confidence FROM svrt_reference WHERE lookup_key=?", (key,)
            ).fetchone()
            if existing and existing[0] > 90:
                skipped += 1
                continue

            ttl_days = TTL_EOL_FACT if eol_status == 'eol' else TTL_SUPPORTED
            expires  = (datetime.utcnow() + timedelta(days=ttl_days)).isoformat()

            conn.execute("""
                INSERT INTO svrt_reference
                    (lookup_key, software_name, vendor, version, platform,
                     eol_status, eol_date, latest_version, latest_source_url,
                     confidence, source, notes, hit_count, created_at, checked_at, expires_at)
                VALUES (?,?,?,?,?,?,?,?,?,90,'github-yaml',?,1,?,?,?)
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
                WHERE svrt_reference.confidence <= 90
            """, (
                key, software_name, vendor, major, platform,
                eol_status, eol_date, latest_ver, source_url,
                notes, now, now, expires,
            ))
            upserted += 1

        conn.commit()
        log.info("  ✓ %s — %d version(s)", fname, len(versions))

    log.info("GitHub YAML sync: %d upserted, %d skipped (higher conf), %d errors",
             upserted, skipped, errors)
    return upserted


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='SVRT Research Agent v1.0')
    parser.add_argument('--status',      action='store_true', help='Print DB stats and exit')
    parser.add_argument('--lookup',      metavar='PRODUCT',   help='Look up a single product')
    parser.add_argument('--import-csv',  metavar='FILE',      help='Import inventory CSV into queue')
    parser.add_argument('--sync',        action='store_true', help='Push DB to IONOS now')
    parser.add_argument('--sync-yaml',   action='store_true', help='Pull community YAML files from GitHub into reference DB')
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

    if args.sync_yaml:
        n = sync_github_yaml(conn)
        log.info("GitHub YAML sync complete: %d entries updated", n)
        return

    # Default: full research run
    log.info("SVRT Agent starting — %s", datetime.utcnow().isoformat())
    run_research(conn, max_items=args.max, delay_sec=args.delay)
    print_status(conn)


if __name__ == '__main__':
    main()
