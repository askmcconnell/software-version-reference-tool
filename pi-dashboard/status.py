#!/usr/bin/env python3
"""
S3C-Tool Pi Dashboard — terminal status view
Run from Pi: python3 ~/svrt/pi-dashboard/status.py
Or via cron for email/log output: python3 ~/svrt/pi-dashboard/status.py --plain
"""

import os, sys, sqlite3, json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DB_PATH  = BASE_DIR / 'db' / 's3c_reference.db'
LOG_PATH = BASE_DIR / 'logs' / 'agent.log'

def color(text, code):
    if '--plain' in sys.argv:
        return text
    return f"\033[{code}m{text}\033[0m"

def green(t): return color(t, '32')
def red(t):   return color(t, '31')
def yellow(t):return color(t, '33')
def cyan(t):  return color(t, '36')
def bold(t):  return color(t, '1')

def bar(n, total, width=30):
    if total == 0: return '─' * width
    filled = min(width, int(n / total * width))
    return '█' * filled + '░' * (width - filled)

def main():
    print(f"\n{bold('═' * 60)}")
    print(f"  {bold('S3C-Tool Pi Dashboard')}  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{bold('═' * 60)}")

    if not DB_PATH.exists():
        print(red(f"\n  No database found at {DB_PATH}"))
        print("  Run: python3 ~/svrt/agent/svrt_agent.py --import-csv <file>\n")
        return

    db_size = DB_PATH.stat().st_size
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Reference counts
    total = conn.execute("SELECT COUNT(*) FROM s3c_reference").fetchone()[0]
    eol   = conn.execute("SELECT COUNT(*) FROM s3c_reference WHERE eol_status='eol'").fetchone()[0]
    supp  = conn.execute("SELECT COUNT(*) FROM s3c_reference WHERE eol_status='supported'").fetchone()[0]
    lts   = conn.execute("SELECT COUNT(*) FROM s3c_reference WHERE eol_status='lts'").fetchone()[0]
    unk   = conn.execute("SELECT COUNT(*) FROM s3c_reference WHERE eol_status='unknown'").fetchone()[0]

    # Queue counts
    q_pending = conn.execute(
        "SELECT COUNT(*) FROM s3c_research_queue WHERE status='pending'"
    ).fetchone()[0]
    q_done = conn.execute(
        "SELECT COUNT(*) FROM s3c_research_queue WHERE status='done'"
    ).fetchone()[0]

    # Submissions
    subs = conn.execute("SELECT COUNT(*) FROM s3c_field_submissions").fetchone()[0]
    hosts = conn.execute(
        "SELECT COUNT(DISTINCT hostname_hash) FROM s3c_field_submissions"
    ).fetchone()[0]

    print(f"\n  {bold('Reference Database')}")
    print(f"  {'─'*55}")
    print(f"  DB size        : {db_size/1024:.1f} KB")
    print(f"  Total entries  : {total:,}")
    print(f"  Submissions    : {subs:,} rows from {hosts} devices")
    print()
    print(f"  {green('Supported')}      : {supp:,}  {bar(supp, total)}")
    print(f"  {cyan('LTS')}           : {lts:,}  {bar(lts, total)}")
    print(f"  {red('EOL')}           : {eol:,}  {bar(eol, total)}")
    print(f"  {yellow('Unknown')}       : {unk:,}  {bar(unk, total)}")

    print(f"\n  {bold('Research Queue')}")
    print(f"  {'─'*55}")
    print(f"  Pending        : {q_pending:,}")
    print(f"  Completed      : {q_done:,}")

    # Source breakdown
    sources = conn.execute("""
        SELECT source, COUNT(*) as n FROM s3c_reference
        GROUP BY source ORDER BY n DESC
    """).fetchall()
    print(f"\n  {bold('By Source')}")
    print(f"  {'─'*55}")
    for s in sources:
        print(f"  {s['source']:<22}: {s['n']:,}  {bar(s['n'], total, 20)}")

    # Top EOL items
    top_eol = conn.execute("""
        SELECT software_name, version, eol_date, hit_count
        FROM s3c_reference WHERE eol_status='eol'
        ORDER BY hit_count DESC LIMIT 8
    """).fetchall()
    if top_eol:
        print(f"\n  {bold('Most-Seen EOL Software')}")
        print(f"  {'─'*55}")
        for r in top_eol:
            eol_dt = f" (EOL: {r['eol_date']})" if r['eol_date'] else ''
            print(f"  {red('●')} {r['software_name']:<28} v{r['version']:<12}{eol_dt}")

    # API cost tracking
    try:
        cost_today = conn.execute("""
            SELECT COUNT(*) as calls, SUM(cost_usd) as cost
            FROM s3c_api_cost_log WHERE call_date=date('now')
        """).fetchone()
        cost_month = conn.execute("""
            SELECT COUNT(*) as calls, SUM(cost_usd) as cost
            FROM s3c_api_cost_log WHERE call_date >= date('now','start of month')
        """).fetchone()
        cost_all = conn.execute("""
            SELECT COUNT(*) as calls, SUM(cost_usd) as cost
            FROM s3c_api_cost_log
        """).fetchone()
        q_remaining = conn.execute(
            "SELECT COUNT(*) FROM s3c_research_queue WHERE status='pending'"
        ).fetchone()[0]

        if cost_all and cost_all['calls']:
            avg = (cost_all['cost'] or 0) / cost_all['calls']
            est = q_remaining * avg
            print(f"\n  {bold('Claude API Cost')}")
            print(f"  {'─'*55}")
            c_today = cost_today['cost'] or 0
            c_month = cost_month['cost'] or 0
            c_all   = cost_all['cost'] or 0
            print(f"  Today      : {(cost_today['calls'] or 0):>6} calls   {green(f'${c_today:.4f}')}")
            print(f"  This month : {(cost_month['calls'] or 0):>6} calls   {green(f'${c_month:.4f}')}")
            print(f"  All time   : {(cost_all['calls'] or 0):>6} calls   {green(f'${c_all:.4f}')}")
            print(f"  Est. remaining queue ({q_remaining} items): {yellow(f'~${est:.2f}')}")
    except Exception:
        pass  # table may not exist yet on older DBs

    # Last agent runs
    runs = conn.execute("""
        SELECT * FROM s3c_agent_log ORDER BY id DESC LIMIT 5
    """).fetchall()
    if runs:
        print(f"\n  {bold('Recent Agent Runs')}")
        print(f"  {'─'*55}")
        for r in runs:
            print(f"  {r['run_date'][:16]}  resolved={r['items_out']}  api_calls={r['api_calls']}  {r['notes']}")

    # Last sync log entry
    sync_log = BASE_DIR / 'logs' / 'sync.log'
    if sync_log.exists():
        lines = sync_log.read_text().splitlines()
        last_sync_lines = [l for l in lines if 'Sync' in l or 'SUCCESS' in l or 'FAILED' in l]
        if last_sync_lines:
            print(f"\n  {bold('Last IONOS Sync')}")
            print(f"  {'─'*55}")
            for l in last_sync_lines[-3:]:
                print(f"  {l}")

    conn.close()
    print(f"\n{bold('═' * 60)}\n")


if __name__ == '__main__':
    main()
