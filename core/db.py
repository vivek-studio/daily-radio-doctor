"""Local SQLite store: settings + the imported radio sources (so a restart keeps your data)."""
import json, sqlite3, threading
from core.appdata import data_dir

_lock = threading.Lock()
DEFAULTS = {
    "credit_struck": True,       # struck-off item on day D = finished on the previous radio day -> credit it there
    "estimate_missing": True,    # show an ESTIMATE for projects with no asset count (from the same project's other days)
    "sheet_url": "",
}

def _conn():
    c = sqlite3.connect(str(data_dir() / "radio_insights.db"))
    c.row_factory = sqlite3.Row
    c.executescript("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);")
    return c

def get_settings() -> dict:
    with _lock, _conn() as c:
        s = dict(DEFAULTS)
        for r in c.execute("SELECT k,v FROM kv"):
            try: s[r["k"]] = json.loads(r["v"])
            except Exception: pass
        return s

def save_settings(s: dict) -> None:
    with _lock, _conn() as c:
        for k, v in s.items():
            c.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))

def get_sources() -> list:
    s = get_settings().get("_sources", [])
    return s if isinstance(s, list) else []

def set_sources(items: list) -> None:
    save_settings({"_sources": items})
