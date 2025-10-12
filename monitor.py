# monitor.py
import argparse, json, os, random, re, sys, time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ONLINE_URL = "https://pr-underworld.com/website/"
RANKING_URL = "https://pr-underworld.com/website/ranking/"

# Nur die gewünschten Jobcodes werden gemeldet
JOB_MAP = {
    # Templar Linie
    "220": "Templar",
    "224": "Master Breeder",
    "221": "Mercenary",
    "223": "Oracle",
    "222": "Cardinal",
    # Berserker Linie
    "120": "Berserker",
    "121": "Marksman",
    "124": "Beast Master",
    "123": "War Kahuna",
    "122": "Magus",
    # Overlord Linie
    "324": "Overlord",
    "320": "Slayer",
    "321": "Deadeye",
    "322": "Void Mage",
    "323": "Corruptor",
}

STATE_PATH = Path("data/state.json")
QUOTES_PATH = Path("data/quotes.txt")

def ensure_state():
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.exists():
        STATE_PATH.write_text("{}", encoding="utf-8")

def load_state():
    ensure_state()
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

def get_random_quote():
    if QUOTES_PATH.exists():
        lines = [l.strip() for l in QUOTES_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
        if lines:
            return random.choice(lines)
    return ""

def http_get(url):
    headers = {
        "User-Agent": "UW-JobWatcher/1.0 (+github actions)",
        "Accept": "text/html,application/xhtml+xml",
        "Cache-Control": "no-cache",
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text

JOB_CODE_RE = re.compile(r"/(\d{3})\.jpg")

def extract_job_code_from_img_src(src: str) -> str | None:
    m = JOB_CODE_RE.search(src)
    if not m:
        return None
    return m.group(1)

def parse_online(html: str) -> dict[str, str]:
    """Liest die Tabelle von der Startseite. Name in tds[0], Job-IMG in tds[2]."""
    soup = BeautifulSoup(html, "html.parser")
    current = {}
    for tbody in soup.find_all("tbody"):
        for tr in tbody.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
            name = tds[0].get_text(strip=True)
            job_img = tds[2].find("img")
            if not job_img:
                continue
            code = extract_job_code_from_img_src(job_img.get("src", ""))
            if code and code in JOB_MAP:
                current[name] = code
    return current

def parse_ranking(html: str) -> dict[str, str]:
    """Liest die Top 100. Name in tds[1], Job-IMG in tds[3]."""
    soup = BeautifulSoup(html, "html.parser")
    current = {}
    for tbody in soup.find_all("tbody"):
        for tr in tbody.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue
            name = tds[1].get_text(strip=True)
            job_img = tds[3].find("img")
            if not job_img:
                continue
            code = extract_job_code_from_img_src(job_img.get("src", ""))
            if code and code in JOB_MAP:
                current[name] = code
    return current

def merge_dicts(a: dict[str, str], b: dict[str, str]) -> dict[str, str]:
    """Priorisiert b bei Konflikten. So kann ein Lauf gezielt eine Quelle überschreiben."""
    out = dict(a)
    out.update(b)
    return out

def post_discord(webhook_url: str, content: str):
    if not webhook_url:
        print("Kein DISCORD_WEBHOOK_URL gesetzt", file=sys.stderr)
        return
    payload = {"content": content}
    r = requests.post(webhook_url, json=payload, timeout=15)
    try:
        r.raise_for_status()
    except Exception as e:
        print(f"Webhook Fehler {e} Status {r.status_code} Body {r.text}", file=sys.stderr)

def build_message(quote: str, player: str, old_code: str, new_code: str) -> str:
    old_name = JOB_MAP.get(old_code, old_code)
    new_name = JOB_MAP.get(new_code, new_code)
    prefix = f"{quote} " if quote else ""
    return f"{prefix}{player} rebirthed from {old_name} to {new_name}."

def run(source: str, dry_run: bool = False):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    state = load_state()
    before = state.get("players", {})
    if not isinstance(before, dict):
        before = {}

    current_total: dict[str, str] = {}

    if source in ("online", "both"):
        html = http_get(ONLINE_URL)
        current_total = merge_dicts(current_total, parse_online(html))
    if source in ("ranking", "both"):
        html = http_get(RANKING_URL)
        current_total = merge_dicts(current_total, parse_ranking(html))

    # Finde Job-Änderungen
    changes: list[tuple[str, str, str]] = []  # (name, old_code, new_code)
    for name, new_code in current_total.items():
        old_code = before.get(name)
        if old_code and old_code != new_code:
            # Nur melden, wenn beide Codes im erlaubten Set sind
            if old_code in JOB_MAP and new_code in JOB_MAP:
                changes.append((name, old_code, new_code))

    # Postings absetzen
    for name, old_code, new_code in changes:
        msg = build_message(get_random_quote(), name, old_code, new_code)
        if dry_run:
            print(msg)
        else:
            post_discord(webhook_url, msg)
        time.sleep(0.5)

    # State aktualisieren mit aktuellem Stand
    after = dict(before)
    after.update(current_total)
    state["players"] = after
    state["last_run_source"] = source
    save_state(state)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["online", "ranking", "both"], default="online")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(args.source, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
