import os
from pathlib import Path

def data_dir() -> Path:
    env = os.environ.get("DAILY_RADIO_DATA")
    if env:
        base = Path(env)
    elif os.name == "nt" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"]) / "Daily Radio Insights"
    else:
        base = Path.home() / ".daily-radio-insights"
    base.mkdir(parents=True, exist_ok=True)
    return base
