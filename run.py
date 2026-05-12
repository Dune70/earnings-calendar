#!/usr/bin/env python3
"""
Earnings Calendar – @MonitorFinanzas_Bot
Runs via Claude Routine every Friday 16:00 Buenos Aires (UTC-3)
"""
import base64, json, os, re, subprocess, sys, urllib.request
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from datetime import datetime, timedelta

def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.exists(env_path):
        return
    for enc in ('utf-16', 'utf-8-sig', 'utf-8'):
        try:
            with open(env_path, encoding=enc) as f:
                content = f.read()
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, _, v = line.partition('=')
                    os.environ.setdefault(k.strip(), v.strip())
            return
        except (UnicodeDecodeError, UnicodeError):
            continue

_load_env()
FINN_API = os.environ.get("FINN_API") or base64.b64decode("ZDdsdnAwcHIwMXFrN2x2dWsyb2dkN2x2cDBwcjAxcWs3bHZ1azJwMA==").decode()

TOKEN   = base64.b64decode("ODY3MzE3Nzc1NTpBQUhuWC1iME02UWFuSmJfWjBUZEp3cldiaE5yQ3RKVnRNZw==").decode()
CHAT_ID = "6543677004"
CAL_URL = "https://dune70.github.io/earnings-calendar/"
SOURCE  = "https://earningshub.com/earnings-calendar/next-week"
BACKUP  = "https://stockanalysis.com/earnings-calendar/"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
MONTHS  = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
SKIP_WORDS = {
    'THE','AND','FOR','NOT','ARE','ALL','CAN','WAS','ONE','OUR','OUT','DAY',
    'GET','HAS','HIM','HIS','HOW','NEW','NOW','OLD','SEE','TWO','WAY','WHO',
    'DID','ITS','LET','PUT','SAY','SHE','TOO','USE','MON','TUE','WED','THU',
    'FRI','SAT','SUN','JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP',
    'OCT','NOV','DEC','EST','UTC','CEO','CFO','IPO','ETF','EPS','NYSE','NASDAQ',
    'HTML','JSON','HTTP','API','CSS','USD','EPS','YOY','QOQ','TTM','GAAP',
    'OPEN','CLOSE','AFTER','BEFORE','MORE','NEXT','WEEK','THIS','VIEW','CALLS',
    'NEWS','QUOTE','STOCKS','SEARCH','POPULAR','CALENDAR','EARNINGS','INSIGHTS'
}

# ─── DATE HELPERS ──────────────────────────────────────────────────────────

def next_week_label():
    today = datetime.now()
    days = (7 - today.weekday()) % 7 or 7
    monday = today + timedelta(days=days)
    friday = monday + timedelta(4)
    if monday.month == friday.month:
        return f"{MONTHS[monday.month-1]} {monday.day}–{friday.day}, {friday.year}"
    return f"{MONTHS[monday.month-1]} {monday.day} – {MONTHS[friday.month-1]} {friday.day}, {friday.year}"

def next_week_days():
    today = datetime.now()
    days = (7 - today.weekday()) % 7 or 7
    monday = today + timedelta(days=days)
    day_names = ['Mon','Tue','Wed','Thu','Fri']
    return {f"{day_names[i]} {(monday + timedelta(i)).day}": monday + timedelta(i) for i in range(5)}

# ─── SCRAPING ──────────────────────────────────────────────────────────────

def fetch_html(url):
    try:
        r = subprocess.run(
            ["curl", "-sL", "-A", UA, "--max-time", "30", "--compressed", url],
            capture_output=True, text=True, timeout=40
        )
        if r.returncode == 0 and len(r.stdout) > 500:
            return r.stdout
    except Exception as e:
        print(f"  curl error: {e}")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  urllib error: {e}")
    return ""

def get_next_data(html):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return None

def parse_earningshub_next(data):
    """
    Explore earningshub __NEXT_DATA__ and extract calendar.
    Structure varies — tries common patterns.
    """
    try:
        props = data.get("props", {}).get("pageProps", {})

        # Pattern 1: direct 'earnings' list
        for key in ["earnings", "calendarData", "calendar", "data", "schedule"]:
            if key in props and isinstance(props[key], list):
                raw = props[key]
                print(f"  Found list under pageProps.{key} ({len(raw)} items)")
                return normalize_earningshub_list(raw)

        # Pattern 2: nested under a date-keyed dict
        for key, val in props.items():
            if isinstance(val, dict):
                # Check if keys look like dates
                keys = list(val.keys())
                if keys and re.match(r'\d{4}-\d{2}-\d{2}', str(keys[0])):
                    print(f"  Found date-keyed dict under pageProps.{key}")
                    return normalize_date_dict(val)

        print(f"  pageProps keys: {list(props.keys())[:15]}")
    except Exception as e:
        print(f"  parse_earningshub_next error: {e}")
    return None

def normalize_earningshub_list(raw):
    """Convert earningshub list format to our calendar format."""
    calendar = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        # Try to find day and tickers
        day_label = item.get("date") or item.get("day") or item.get("label", "")
        if not day_label:
            continue
        # Normalize day label to "Mon 5" format
        day_label = normalize_day_label(str(day_label))

        sections = []
        for timing, stype in [("beforeOpen", "before"), ("afterClose", "after"),
                               ("before_open", "before"), ("after_close", "after"),
                               ("before", "before"), ("after", "after")]:
            tickers_raw = item.get(timing, [])
            if isinstance(tickers_raw, list) and tickers_raw:
                tickers = extract_tickers_from_list(tickers_raw)
                if tickers:
                    display = tickers[:11]
                    more = len(tickers) - 11 if len(tickers) > 11 else 0
                    label = "Before Open" if stype == "before" else "After Close"
                    sec = {"label": label, "type": stype, "tickers": display}
                    if more:
                        sec["more"] = more
                    sections.append(sec)

        if sections:
            calendar.append({"day": day_label, "sections": sections})
    return calendar if calendar else None

def normalize_date_dict(date_dict):
    """Convert date-keyed dict to calendar format."""
    calendar = []
    day_names = ['Mon','Tue','Wed','Thu','Fri']
    for date_str, val in sorted(date_dict.items()):
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            if d.weekday() >= 5:
                continue
            day_label = f"{day_names[d.weekday()]} {d.day}"
        except:
            continue
        sections = []
        if isinstance(val, dict):
            for timing, stype in [("before", "before"), ("after", "after"),
                                   ("beforeOpen", "before"), ("afterClose", "after")]:
                tickers = extract_tickers_from_list(val.get(timing, []))
                if tickers:
                    display = tickers[:11]
                    more = len(tickers) - 11 if len(tickers) > 11 else 0
                    label = "Before Open" if stype == "before" else "After Close"
                    sec = {"label": label, "type": stype, "tickers": display}
                    if more:
                        sec["more"] = more
                    sections.append(sec)
        if sections:
            calendar.append({"day": day_label, "sections": sections})
    return calendar if calendar else None

def extract_tickers_from_list(items):
    """Extract ticker symbols from a list of strings or dicts."""
    tickers = []
    for item in items:
        if isinstance(item, str) and re.match(r'^[A-Z]{1,5}$', item.strip()):
            tickers.append(item.strip())
        elif isinstance(item, dict):
            for key in ["ticker", "symbol", "name", "stock"]:
                val = item.get(key, "")
                if val and re.match(r'^[A-Z]{1,5}$', str(val).strip()):
                    tickers.append(str(val).strip())
                    break
    return tickers

def normalize_day_label(raw):
    """Normalize various date formats to 'Mon 5'."""
    day_names = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
    for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"]:
        try:
            d = datetime.strptime(raw.strip(), fmt)
            return f"{day_names[d.weekday()]} {d.day}"
        except:
            pass
    # Already in short format?
    m = re.match(r'(Mon|Tue|Wed|Thu|Fri)\w*\s+(\d+)', raw, re.I)
    if m:
        return f"{m.group(1).capitalize()} {m.group(2)}"
    return raw

def fetch_finnhub(from_date, to_date):
    if not FINN_API:
        print("  FINN_API not set, skipping Finnhub")
        return None
    url = (f"https://finnhub.io/api/v1/calendar/earnings"
           f"?from={from_date}&to={to_date}&token={FINN_API}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"  Finnhub error: {e}")
        return None

    entries = data.get("earningsCalendar", [])
    if not entries:
        print("  Finnhub returned 0 entries")
        return None

    by_date = {}
    for entry in entries:
        date_str = entry.get("date", "")
        symbol = entry.get("symbol", "")
        hour = entry.get("hour", "")
        if not date_str or not symbol:
            continue
        if date_str not in by_date:
            by_date[date_str] = {"before": [], "after": []}
        bucket = "before" if hour == "bmo" else "after"
        by_date[date_str][bucket].append(symbol)

    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
    calendar = []
    for date_str in sorted(by_date.keys()):
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            if d.weekday() >= 5:
                continue
            day_label = f"{day_names[d.weekday()]} {d.day}"
        except Exception:
            continue
        sections = []
        for stype, label in [("before", "Before Open"), ("after", "After Close")]:
            tickers = sorted(by_date[date_str][stype])
            if tickers:
                display = tickers[:11]
                more = len(tickers) - 11 if len(tickers) > 11 else 0
                sec = {"label": label, "type": stype, "tickers": display}
                if more:
                    sec["more"] = more
                sections.append(sec)
        if sections:
            calendar.append({"day": day_label, "sections": sections})

    return calendar if calendar else None

# ─── HTML UPDATE ───────────────────────────────────────────────────────────

def update_html(calendar, label):
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')
    if not os.path.exists(html_path):
        print("  index.html not found, skipping")
        return
    with open(html_path, encoding='utf-8') as f:
        html = f.read()

    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"// ─── EARNINGS DATA ── {label} ─────────────────────────────────────",
        "// SOURCE: finnhub.io",
        f"// UPDATED: {today}",
        f"const WEEK_LABEL = '{label}';",
        "",
        "const calendarData = [",
    ]
    for i, day in enumerate(calendar):
        comma = "," if i < len(calendar) - 1 else ""
        lines.append("  {")
        lines.append(f"    day: '{day['day']}',")
        lines.append("    sections: [")
        secs = day.get('sections', [])
        for j, sec in enumerate(secs):
            sec_comma = "," if j < len(secs) - 1 else ""
            tickers_str = ", ".join(f"'{t}'" for t in sec['tickers'])
            more = sec.get('more', 0)
            more_str = f", more: {more}" if more else ""
            lines.append(
                f"      {{ label: '{sec['label']}', type: '{sec['type']}', "
                f"tickers: [{tickers_str}]{more_str} }}{sec_comma}"
            )
        lines.append("    ]")
        lines.append(f"  }}{comma}")
    lines.append("];")
    lines.append("")

    new_block = "\n".join(lines) + "\n"
    html_new = re.sub(
        r'// [^\n]*EARNINGS DATA.*?(?=// [^\n]*TODAY DETECTION)',
        new_block,
        html,
        flags=re.DOTALL
    )
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_new)
    print("  index.html updated")


def push_to_github(label):
    base = os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(os.path.join(base, '.git')):
        print("  No git repo, skipping push")
        return False
    try:
        subprocess.run(["git", "-C", base, "add", "index.html"],
                       check=True, capture_output=True)
        commit = subprocess.run(["git", "-C", base, "commit", "-m", f"Earnings {label}"],
                                capture_output=True)
        if commit.returncode not in (0, 1):
            raise subprocess.CalledProcessError(commit.returncode, "git commit", commit.stderr)
        if commit.returncode == 1:
            print("  index.html sin cambios, push omitido")
            return True
        r = subprocess.run(["git", "-C", base, "push"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            print("  GitHub Pages push OK")
            return True
        print(f"  git push failed: {r.stderr.strip()}")
        return False
    except subprocess.CalledProcessError as e:
        print(f"  git error: {e.stderr.decode(errors='replace').strip() if e.stderr else e}")
        return False


# ─── TELEGRAM ──────────────────────────────────────────────────────────────

def send_telegram(text):
    payload = json.dumps({
        "chat_id": CHAT_ID,
        "text": text,
        "reply_markup": {
            "inline_keyboard": [[{
                "text": "\U0001f4ca Ver Calendario",
                "url": CAL_URL
            }]]
        }
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"}
    )
    resp = urllib.request.urlopen(req, timeout=15)
    result = json.loads(resp.read())
    return result.get("ok", False)

# ─── MESSAGE BUILDER ───────────────────────────────────────────────────────

def build_message(calendar, label):
    lines = [f"\U0001f4c5 Earnings – {label}"]
    for day in calendar:
        lines.append(f"\n{day['day']}")
        for sec in day.get("sections", []):
            emoji = "☀️" if sec["type"] == "before" else "\U0001f319"
            tickers = ", ".join(sec.get("tickers", [])[:6])
            more = sec.get("more", 0)
            if more:
                tickers += f" (+{more} mas)"
            lines.append(f"{emoji} {tickers}")
    return "\n".join(lines)

# ─── MAIN ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    label = next_week_label()
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Target: {label}")

    # Calculate next week date range
    week_days = next_week_days()
    dates = sorted(week_days.values())
    from_date = dates[0].strftime("%Y-%m-%d")
    to_date   = dates[-1].strftime("%Y-%m-%d")

    # Primary: Finnhub API
    print(f"Fetching Finnhub API ({from_date} to {to_date}) ...")
    calendar = fetch_finnhub(from_date, to_date)

    # Fallback 1: earningshub scraping
    if not calendar:
        print("  Trying earningshub.com fallback ...")
        html = fetch_html(SOURCE)
        print(f"  HTML: {len(html)} chars")
        next_data = get_next_data(html)
        if next_data:
            print("  __NEXT_DATA__ found, parsing ...")
            calendar = parse_earningshub_next(next_data)

    # Fallback 2: stockanalysis scraping
    if not calendar:
        print("  Trying stockanalysis.com fallback ...")
        html2 = fetch_html(BACKUP)
        next_data2 = get_next_data(html2)
        if next_data2:
            calendar = parse_earningshub_next(next_data2)

    if calendar:
        msg = build_message(calendar, label)
        print(f"  Calendar: {len(calendar)} days extracted")
        update_html(calendar, label)
        push_to_github(label)
    else:
        print("  WARNING: could not parse structured data, sending placeholder")
        msg = (
            f"\U0001f4c5 Earnings – {label}\n\n"
            "No se pudo parsear los datos automaticamente.\n"
            "Revisa el calendario completo:"
        )

    print(f"\nMessage preview:\n{msg[:300]}")
    ok = send_telegram(msg)
    print(f"\nTelegram: {'OK ✓' if ok else 'FAILED ✗'}")
