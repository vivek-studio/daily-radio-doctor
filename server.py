"""Daily Radio Insights -- local server. Run: python server.py  (opens http://127.0.0.1:8766)"""
from __future__ import annotations
import io, os, re, sys, threading, webbrowser, zipfile
from typing import List
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import db, google_auth, google_sheets as gs
from analysis import analyse

VERSION = "1.0.0"
HERE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="Daily Radio Insights")
NAVY, GREEN = {"red": 0.14, "green": 0.12, "blue": 0.31}, {"red": 0.83, "green": 0.95, "blue": 0.42}


def read_text(name: str, raw: bytes) -> str:
    if name.lower().endswith(".docx"):
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            x = z.read("word/document.xml").decode("utf8", "ignore")
        # keep strike-through: wrap struck runs in ~~ so the parser sees them
        def run(m):
            r = m.group(0); t = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", r))
            return f"~~{t}~~" if re.search(r"<w:strike\b(?![^>]*w:val=\"(?:0|false)\")", r) and t.strip() else t
        x = re.sub(r"<w:r[ >].*?</w:r>", run, x, flags=re.S)
        x = re.sub(r"</w:p>", "\n", x); x = re.sub(r"<[^>]+>", "", x)
        return x.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try: return raw.decode(enc)
        except Exception: continue
    return raw.decode("utf-8", "ignore")


def result() -> dict:
    cfg = db.get_settings()
    r = analyse(db.get_sources(), cfg)
    r["version"] = VERSION; r["settings"] = {k: v for k, v in cfg.items() if not k.startswith("_") and k != "google_account"}
    r["sources"] = [{"name": s["name"], "chars": len(s["text"])} for s in db.get_sources()]
    return r


@app.get("/api/state")
def state(): return result()


@app.post("/api/import")
async def import_files(files: List[UploadFile] = File(...), replace: bool = True):
    src = [] if replace else db.get_sources()
    for f in files: src.append({"name": f.filename or "radio.txt", "text": read_text(f.filename or "", await f.read())})
    db.set_sources(src); return result()


class PasteIn(BaseModel):
    text: str
    name: str = "Pasted radio"
    replace: bool = False


@app.post("/api/paste")
def paste(b: PasteIn):
    if not b.text.strip(): raise HTTPException(400, "Nothing pasted.")
    src = [] if b.replace else db.get_sources()
    src.append({"name": b.name or "Pasted radio", "text": b.text}); db.set_sources(src); return result()


@app.post("/api/demo")
def demo():
    f = os.path.join(HERE, "samples", "demo_year.txt")
    if not os.path.exists(f): raise HTTPException(404, "samples/demo_year.txt is missing.")
    db.set_sources([{"name": "demo_year.txt (synthetic)", "text": open(f, encoding="utf8").read()}]); return result()


@app.post("/api/clear")
def clear(): db.set_sources([]); return result()


class SettingsIn(BaseModel):
    settings: dict = {}


@app.put("/api/settings")
def put_settings(b: SettingsIn):
    cur = db.get_settings(); cur.update({k: v for k, v in b.settings.items() if k in db.DEFAULTS}); db.save_settings(cur); return result()


# ------------------------------------------------------------------ Google
@app.get("/api/google")
def g_status(): return {**google_auth.status(), "client": google_auth.client_status()}


@app.post("/api/google/connect")
def g_connect():
    try: return google_auth.connect()
    except Exception as e: raise HTTPException(400, str(e))


@app.post("/api/google/disconnect")
def g_disc(): return google_auth.reset()


class PushIn(BaseModel):
    sheet_url: str


def _tables(r: dict):
    S = r["stats"]
    def t(title, head, keys, rows, wide=None): return (title, head, [[x.get(k, "") if x.get(k) is not None else "" for k in keys] for x in rows], wide)
    yn = lambda v: "Yes" if v else "No"
    days = [dict(x, radio=yn(x["radio"]), weekend=yn(x["weekend"])) for x in r["days"]]
    ins = [[i["k"], i["t"]] for i in r["insights"]]
    ins += [[], ["Headline", "value"]] + [[k, str(v)] for k, v in S.items()]
    hl = [[h["sev"], h["label"], h.get("date") or "", h.get("project", ""), h["detail"], h.get("file", "")] for h in r["health"]["items"]]
    lim = [["Built-in", l["t"], "", l["i"], l["d"], ""] for l in r["limitations"]]
    return [
        ("Insights", ["Topic", "Insight"], ins, 1),
        t("Daily Workload", ["Date", "Day", "Radio in data", "Weekend", "Format", "Assets worked", "Projects worked", "Projects with no asset count", "Estimated extra assets (for missing counts)", "Assets incl. estimate",
                              "Projects with count", "Credited from struck-off (projects)", "Credited assets", "KO Ques (not counted)", "Struck-off rows", "AM HO projects", "AM HO assets", "Final handoffs", "RD rounds", "Additional revisions", "7-radio-day avg assets"],
          ["date", "day", "radio", "weekend", "format", "assets", "projects", "missing", "est_extra", "assets_est", "with_count", "credited", "credited_assets", "ko", "struck", "am_ho", "am_ho_assets", "final", "rd", "rev", "roll7"], days),
        t("Items Worked", ["Date", "Day", "Project", "Campaign", "Type", "Stage", "Stage group", "Assets", "Estimate if no count", "AM HO", "Stream", "Credited from (struck-off on)", "Original row", "Radio format"],
          ["date", "day", "name", "campaign", "kind", "stage", "stage_family", "assets", "est", "am_ho", "stream", "credited_from", "raw", "fmt"], r["items"]),
        t("Projects", ["Project", "Campaign", "Type", "Rounds worked", "First", "Last", "Assets total", "Largest count", "Rounds w/o count", "Struck-off rows", "KO date", "KO to first handoff (days)", "Rework rounds", "Journey"],
          ["name", "campaign", "kind", "rounds", "first", "last", "assets_total", "assets_max", "missing_rounds", "struck", "ko", "ko_to_first_days", "rework_rounds", "journey"], r["projects"]),
        t("Campaigns", ["Campaign", "Handoffs", "Assets", "No-count handoffs", "Days active", "Projects", "Share of assets %"], ["campaign", "items", "assets", "missing", "days", "projects", "share"], r["campaigns"]),
        t("Stages", ["Stage", "Handoffs", "Assets", "No-count handoffs", "Days", "Projects", "Share %"], ["stage", "items", "assets", "missing", "days", "projects", "share"], r["stages"]),
        t("Stage Groups & Type", ["Group", "Handoffs", "Assets", "No-count handoffs", "Days", "Projects", "Share %"], ["family", "items", "assets", "missing", "days", "projects", "share"], r["families"] + [dict(x, family="Type: " + x["kind"]) for x in r["kinds"]]),
        t("Weekdays", ["Weekday", "Radios", "Total assets", "Avg assets", "Median", "Max", "Avg projects"], ["day", "radios", "total", "avg", "median", "max", "projects"], r["weekdays"]),
        t("Weekly", ["Week starting (Mon)", "Radio days", "Assets", "Projects", "No-count projects", "Avg assets/radio day", "KO", "AM HO", "Estimated extra"], ["period", "radios", "assets", "projects", "missing", "avg", "ko", "am_ho", "est_extra"], r["weeks"]),
        t("Monthly", ["Month", "Radio days", "Assets", "Projects", "No-count projects", "Avg assets/radio day", "KO", "AM HO", "Estimated extra"], ["period", "radios", "assets", "projects", "missing", "avg", "ko", "am_ho", "est_extra"], r["months"]),
        t("Missing Asset Counts", ["Date", "Day", "Project", "Stage", "Estimate from other days", "Original row"], ["date", "day", "name", "stage", "est", "raw"], [i for i in r["items"] if i["assets"] is None]),
        t("KO Kickoffs", ["Date", "Project", "Assets", "Tentative", "Original row", "Struck"], ["date", "project", "assets", "tentative", "row", "struck"], r["kickoffs"]),
        t("Struck-off", ["Radio date", "Project", "Stage", "Assets", "Previous radio", "Outcome"], ["date", "project", "stage", "assets", "previous_radio", "outcome"], r["struck"]),
        t("Radio Audit", ["Date", "Day", "Format", "File", "Due-today rows read", "Projects counted", "KO", "Struck", "Credited in", "Other rows ignored", "Assets", "No-count"], ["date", "day", "format", "file", "rows_read", "counted", "ko", "struck", "credited_in", "ignored", "assets", "missing"], r["audit"]),
        ("Limitations", ["Severity / type", "Label", "Date", "Project / impact", "Detail", "File"], lim + [list(h) for h in hl], 4),
    ]


@app.post("/api/push")
def push(b: PushIn):
    r = result()
    if not r["days"]: raise HTTPException(400, "Nothing to push: import radios first.")
    try:
        svc = gs.get_service(); sid = gs.extract_sheet_id(b.sheet_url)
        if not sid: raise HTTPException(400, "That does not look like a Google Sheet link.")
        reqs, gids = [], {}
        for title, head, body, wide in _tables(r):
            gid = gs.ensure_worksheet(svc, sid, title, rows=len(body) + 50, cols=len(head) + 2); gids[title] = gid
            gs.ensure_grid_size(svc, sid, gid, len(body) + 2, len(head))
            tab = gs.quote_tab(title); gs.clear_values(svc, sid, tab)
            gs.update_values(svc, sid, f"{tab}!A1", [head] + body, "RAW")
            n, c = len(body) + 1, len(head)
            reqs += [
                {"updateSheetProperties": {"properties": {"sheetId": gid, "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
                {"repeatCell": {"range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1}, "cell": {"userEnteredFormat": {"backgroundColor": NAVY, "wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE",
                    "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}}, "fields": "userEnteredFormat"}},
                {"setBasicFilter": {"filter": {"range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": n, "startColumnIndex": 0, "endColumnIndex": c}}}},
                {"autoResizeDimensions": {"dimensions": {"sheetId": gid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": c}}},
            ]
            if wide is not None:
                reqs.append({"updateDimensionProperties": {"range": {"sheetId": gid, "dimension": "COLUMNS", "startIndex": wide, "endIndex": wide + 1}, "properties": {"pixelSize": 520}, "fields": "pixelSize"}})
        dg, nd = gids["Daily Workload"], len(r["days"]) + 1
        def series(col, color): return {"series": {"sourceRange": {"sources": [{"sheetId": dg, "startRowIndex": 0, "endRowIndex": nd, "startColumnIndex": col, "endColumnIndex": col + 1}]}}, "targetAxis": "LEFT_AXIS", "color": color}
        reqs.append({"addChart": {"chart": {"spec": {"title": "Assets worked per day (due today, KO excluded)", "basicChart": {"chartType": "COLUMN", "legendPosition": "BOTTOM_LEGEND", "stackedType": "STACKED",
            "axis": [{"position": "BOTTOM_AXIS", "title": "Date"}, {"position": "LEFT_AXIS", "title": "Assets"}],
            "domains": [{"domain": {"sourceRange": {"sources": [{"sheetId": dg, "startRowIndex": 0, "endRowIndex": nd, "startColumnIndex": 0, "endColumnIndex": 1}]}}}],
            "series": [series(5, {"red": .29, "green": .25, "blue": .62}), series(8, {"red": .9, "green": .6, "blue": .1})], "headerCount": 1}},
            "position": {"overlayPosition": {"anchorCell": {"sheetId": dg, "rowIndex": 1, "columnIndex": 22}, "widthPixels": 900, "heightPixels": 380}}}}})
        gs.batch_update(svc, sid, reqs)
        db.save_settings({"sheet_url": b.sheet_url})
        return {"ok": True, "url": gs.open_sheet_tab_url(b.sheet_url, "Daily Workload"), "tabs": [t[0] for t in _tables(r)]}
    except HTTPException: raise
    except gs.SheetsSyncError as e: raise HTTPException(400, str(e))
    except Exception as e: raise HTTPException(500, f"Push failed: {e}")


@app.get("/")
def index(): return FileResponse(os.path.join(HERE, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8766"))
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
