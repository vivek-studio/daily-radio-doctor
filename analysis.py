"""Daily Radio Insights -- parser + analysis.

RULES (all from the brief):
  * Only DUE TODAY is ever read. New format: the DUE TODAY section. Old format: only lines that say "due today".
  * KO Ques row  = a NEW project kicking off, NOT work handed off -> never counted as workload.
  * Struck-off (~~x~~) row in DUE TODAY = the team finished it on the previous radio day -> not counted today;
    it is credited to the previous radio day (unless that day already listed the same project).
  * One project name counts once per day (old format lists Design and Copy separately; same name = same project).
"""
from __future__ import annotations
import re, statistics, difflib
from collections import defaultdict, Counter
from datetime import date, timedelta

MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
DATE_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})")
DATE_RE2 = re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})")
HDR_RE = re.compile(r"^\W*(DUE\s+TODAY|PROJECTS?\s+KICKING\s+OFF|IN\s+PIPELINE|FEEDBACK\s+AWAITED)\b", re.I)
END_RE = re.compile(r"^\W*(WRIKE\s+RESPONSES|SLACK\s+RESPONSES)\b", re.I)
ITEM_RE = re.compile(r"^\s*(?:\d+\s*[.)]|[-•*▪◦])\s*(.+?)\s*$")
ASSET_RE = re.compile(r"\(?\b(\d[\d,]*)\s*assets?\b\)?", re.I)
KO_RE = re.compile(r"\bKO\b[\s\-:]*(?:ques(?:tions?)?|q'?s)\b|\bkick[\s-]?off\s+ques", re.I)
DUE_TODAY_RE = re.compile(r"\bdue\b[^()]{0,25}?\btoday\b", re.I)
AMHO_RE = re.compile(r"\bAM\s*HO\b", re.I)
KINDS_RE = re.compile(r"\b(Bun|Der)\s+([A-Z])\b")
SEP = re.compile(r"\s+[-–—]\s+")
STRIKE_CHARS = "\u0336"
SEV = {"error": 0, "warn": 1, "info": 2}


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9& ]+", "", re.sub(r"\s+", " ", name.lower())).strip()


def parse_date_line(line: str):
    if "status" not in line.lower() and "@here" not in line.lower():
        return None
    m = DATE_RE.search(line)
    if m:
        d, mon, y = int(m.group(1)), MONTHS.get(m.group(2)[:3].lower()), int(m.group(3))
    else:
        m = DATE_RE2.search(line)
        if not m: return None
        mon, d, y = MONTHS.get(m.group(1)[:3].lower()), int(m.group(2)), int(m.group(3))
    try: return date(y, mon, d) if mon else None
    except ValueError: return None


def split_blocks(text: str):
    """Split a pasted blob into per-day blocks at each '@here <date> Project Status' line."""
    blocks, cur = [], None
    for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        d = parse_date_line(ln.strip())
        if d is not None:
            cur = {"date": d, "lines": [], "header": ln.strip()}
            blocks.append(cur)
        elif cur is not None:
            cur["lines"].append(ln)
    return blocks


def strike_info(raw: str):
    """-> (is_struck, partial, clean_text)."""
    s = raw.strip()
    uni = s.count(STRIKE_CHARS)
    s2 = s.replace(STRIKE_CHARS, "")
    html = bool(re.search(r"</?(s|del|strike)\b", s2, re.I))
    s2 = re.sub(r"</?(s|del|strike)\b[^>]*>", "", s2, flags=re.I)
    tild = "~" in s2
    clean = s2.replace("~", "").strip()
    if not (tild or html or uni): return False, False, clean
    if html or (uni and uni >= max(3, len(clean) // 2)): return True, False, clean
    body = ITEM_RE.match(s2)
    b = (body.group(1) if body else s2).strip()
    full = re.match(r"^~+.*~+[\s.]*$", b) is not None
    head = b.startswith("~")
    if full or head: return True, not full, clean       # name part is inside the strike
    return False, True, clean                              # tilde somewhere else: not treated as struck


def stage_of(rest: str):
    r = rest or ""
    if re.search(r"final\s+hand\s?-?\s?off", r, re.I): return "Final handoff", "Final handoff"
    m = re.search(r"\bRD\s?(\d+)\b", r, re.I)
    if m: return f"RD{m.group(1)}", "RD rounds"
    m = re.search(r"additional\s+revisions?\s*(\d+)?", r, re.I)
    if m: return ("Additional Revisions" + (f" {m.group(1)}" if m.group(1) else "")), "Additional revisions"
    m = re.search(r"\bteam\s+hand\s?-?\s?off\b", r, re.I)
    if m: return "Team handoff", "Final handoff"
    c = re.split(r"\(|\bdue\b", r, 1, flags=re.I)[0].strip(" -–—.,")
    return (c[:40].title() if c else "Unspecified"), "Other"


def parse_item(body: str, clean: str):
    parts = SEP.split(clean, 1)
    name = parts[0].strip()
    rest = parts[1].strip() if len(parts) > 1 else ""
    name = AMHO_RE.sub("", ASSET_RE.sub("", name)).strip(" ().-–—")
    name = re.sub(r"\s{2,}", " ", name)
    m = ASSET_RE.search(clean)
    assets = int(m.group(1).replace(",", "")) if m else None
    stage, fam = stage_of(rest)
    km = KINDS_RE.search(name)
    kind = km.group(1) if km else "Other"
    campaign = re.sub(r"\s{2,}", " ", KINDS_RE.sub("", name)).strip() if km else name
    return {
        "name": name, "key": norm(name), "rest": rest, "assets": assets, "stage": stage, "stage_family": fam,
        "ko": bool(KO_RE.search(clean)), "am_ho": bool(AMHO_RE.search(clean)), "tentative": bool(re.search(r"tentative", clean, re.I)),
        "kind": kind, "campaign": campaign,
    }


def parse_block(b, health):
    d, lines = b["date"], b["lines"]
    new_fmt = any(HDR_RE.match(l.strip()) for l in lines)
    fmt = "new" if new_fmt else "old"
    section, stream, items, ignored_other = None, "", [], 0
    seen_any_item = False
    for ln in lines:
        s = ln.strip()
        if not s or re.fullmatch(r"[\W_]{4,}", s): continue
        if END_RE.match(s): break
        h = HDR_RE.match(s) if new_fmt else None
        if h:
            section = re.sub(r"\s+", " ", h.group(1).upper()); continue
        if s.upper() in ("NA", "N/A", "NONE", "-"): continue
        m = ITEM_RE.match(s)
        if not m:
            if new_fmt and section == "DUE TODAY" and (SEP.search(s) or ASSET_RE.search(s)):
                m = re.match(r"(.+)", s)
                health.append(dict(sev="info", kind="unnumbered", label="Unnumbered line read as an item", date=d, project=s[:60], detail="Line inside DUE TODAY has no number/bullet; read as a project row."))
            else:
                if len(s) < 40 and not new_fmt and not DUE_TODAY_RE.search(s) and not ASSET_RE.search(s): stream = s.strip(": ")
                continue
        body = m.group(1)
        if re.sub(r"[\W_]+", "", body).upper() in ("NA", "NONE", "NIL", "NOTHING", ""): continue   # "1. NA" = nothing due
        struck, partial, clean = strike_info(ln)
        clean = ITEM_RE.sub(r"\1", clean) if ITEM_RE.match(clean) else clean
        if new_fmt:
            if section != "DUE TODAY": ignored_other += 1; continue
        else:
            if not DUE_TODAY_RE.search(clean): ignored_other += 1; continue
        if partial and not struck:
            health.append(dict(sev="warn", kind="odd_strike", label="Tilde found but row not treated as struck", date=d, project=clean[:60], detail="A '~' sits inside the row but the project name is not struck, so the row IS counted. Check the row."))
        it = parse_item(body, clean)
        if not it["name"]:
            health.append(dict(sev="error", kind="no_name", label="Row without a project name", date=d, project="", detail=clean[:120])); continue
        it.update(struck=struck, stream=stream, raw=clean, date=d)
        items.append(it); seen_any_item = True
    return dict(date=d, format=fmt, items=items, ignored_other=ignored_other, header=b["header"], lines=len(lines))


def pct(a, b): return round(100 * a / b, 1) if b else 0.0
def med(v): return round(statistics.median(v), 1) if v else 0


def analyse(text_sources: list, cfg: dict) -> dict:
    health, blocks = [], []
    for src in text_sources:
        bl = split_blocks(src["text"])
        if not bl: health.append(dict(sev="error", kind="no_radio", label="No radio found in file", date=None, project="", detail=f"{src['name']}: no '@here <date> Project Status' line found.", file=src["name"]))
        for b in bl: b["file"] = src["name"]; blocks.append(b)
    # one block per date: a later duplicate replaces the earlier one
    by_date = {}
    for b in blocks:
        if b["date"] in by_date:
            health.append(dict(sev="warn", kind="dup_radio", label="Same date posted twice", date=b["date"], project="", detail=f"{by_date[b['date']]['file']} and {b['file']} both contain this date; the later one is used."))
        by_date[b["date"]] = b
    radios = [parse_block(by_date[k], health) for k in sorted(by_date)]
    for r in radios: r["file"] = by_date[r["date"]]["file"]
    rd = {r["date"]: r for r in radios}
    order = [r["date"] for r in radios]
    prev_of = {d: order[i - 1] for i, d in enumerate(order) if i}

    # ---- per radio day: work set (dedupe by name, never KO, never struck)
    work, kos, strucks = {}, {}, {}
    rows = []
    for r in radios:
        d = r["date"]; w, k, s = {}, {}, {}
        fmt_old_dup = []
        for it in r["items"]:
            tgt = k if it["ko"] else (s if it["struck"] else w)
            if it["ko"] and it["struck"]: tgt = k
            key = it["key"]
            if key in tgt:
                old = tgt[key]
                diff = old["assets"] and it["assets"] and old["assets"] != it["assets"]
                if old["stream"] != it["stream"] and not diff and fmt_old_dup is not None and r["format"] == "old": fmt_old_dup.append(it["name"])
                else: health.append(dict(sev="warn" if diff else "info", kind="dup_name", label="Same project twice on one day (counted once)", date=d, project=it["name"], detail=f"{old['stream'] or '-'} / {it['stream'] or '-'}: counted once." + (f" Asset counts differ ({old['assets']} vs {it['assets']}); the larger is used." if diff else "")))
                if it["assets"] and (old["assets"] is None or it["assets"] > old["assets"]): old["assets"] = it["assets"]
                if it["am_ho"]: old["am_ho"] = True
                old["streams"].add(it["stream"]); continue
            it["streams"] = {it["stream"]} if it["stream"] else set()
            tgt[key] = it
        work[d], kos[d], strucks[d] = w, k, s
        if fmt_old_dup: health.append(dict(sev="info", kind="dup_design_copy", label="Listed under both Design and Copy (counted once)", date=d, project=f"{len(set(fmt_old_dup))} project(s)", detail="Old format lists a project once per stream; one project name is counted once per day. " + "; ".join(sorted(set(fmt_old_dup)))[:300]))
        if not r["items"]:
            health.append(dict(sev="info", kind="empty_day", label="Nothing due today", date=d, project="", detail="DUE TODAY is empty/NA (or no 'due today' lines in the old format). Counted as a 0-asset radio day."))

    # ---- credit struck rows to previous radio day
    credited = defaultdict(list)
    for d, s in strucks.items():
        for key, it in s.items():
            p = prev_of.get(d)
            it["prev"] = p
            if p is None:
                it["credit"] = "no previous radio"; health.append(dict(sev="warn", kind="struck_first", label="Struck-off row on the first radio", date=d, project=it["name"], detail="No earlier radio, so the day it was finished cannot be derived. Not counted anywhere.")); continue
            if (d - p).days > 3: health.append(dict(sev="warn", kind="gap_credit", label="Struck-off row credited across a long gap", date=d, project=it["name"], detail=f"Previous available radio is {p} ({(d-p).days} days earlier); a radio in between may be missing."))
            if key in work[p]: it["credit"] = "already counted on previous radio"; continue
            if not cfg.get("credit_struck", True): it["credit"] = "credit switched off"; continue
            it["credit"] = "credited"
            c = dict(it); c["credited_from"] = d; credited[p].append(c)
    for p, lst in credited.items():
        for c in lst:
            if c["key"] not in work[p]: work[p][c["key"]] = c

    # ---- known asset counts per project, for the estimate
    known = defaultdict(list)
    for d in order:
        for it in work[d].values():
            if it["assets"]: known[it["key"]].append(it["assets"])
    for d in order:
        for it in work[d].values():
            it["est"] = int(round(statistics.median(known[it["key"]]))) if it["assets"] is None and known.get(it["key"]) else None

    # ---- rows (every counted item)
    items = []
    for d in order:
        for it in sorted(work[d].values(), key=lambda x: x["name"].lower()):
            items.append(dict(date=d.isoformat(), day=d.strftime("%a"), name=it["name"], campaign=it["campaign"], kind=it["kind"], stage=it["stage"], stage_family=it["stage_family"],
                              assets=it["assets"], est=it["est"], am_ho=it["am_ho"], stream=", ".join(sorted(x for x in it["streams"] if x)), credited_from=(it["credited_from"].isoformat() if it.get("credited_from") else ""),
                              raw=it["raw"], fmt=rd[d]["format"]))
            if it["assets"] is None:
                health.append(dict(sev="warn", kind="no_assets", label="Worked project without an asset count", date=d, project=it["name"], detail=("Same project has " + str(it["est"]) + " assets on other days (estimate only)." if it["est"] else "No asset count anywhere for this project.") + f" Row: {it['raw'][:90]}"))
    days, cal = [], {}
    if order:
        n = (order[-1] - order[0]).days
        for i in range(n + 1):
            d = order[0] + timedelta(days=i)
            w = work.get(d, {}).values()
            has = d in rd
            row = dict(date=d.isoformat(), day=d.strftime("%a"), radio=has, weekend=d.weekday() >= 5, format=rd[d]["format"] if has else "",
                       projects=len(w), assets=sum(x["assets"] or 0 for x in w), missing=sum(1 for x in w if x["assets"] is None),
                       est_extra=sum(x["est"] or 0 for x in w if x["assets"] is None), with_count=sum(1 for x in w if x["assets"] is not None),
                       credited=sum(1 for x in w if x.get("credited_from")), credited_assets=sum((x["assets"] or 0) for x in w if x.get("credited_from")),
                       ko=len(kos.get(d, {})), ko_assets=sum(x["assets"] or 0 for x in kos.get(d, {}).values()),
                       struck=len(strucks.get(d, {})), struck_assets=sum(x["assets"] or 0 for x in strucks.get(d, {}).values()),
                       am_ho=sum(1 for x in w if x["am_ho"]), am_ho_assets=sum(x["assets"] or 0 for x in w if x["am_ho"]),
                       final=sum(1 for x in w if x["stage_family"] == "Final handoff"), rd=sum(1 for x in w if x["stage_family"] == "RD rounds"),
                       rev=sum(1 for x in w if x["stage_family"] == "Additional revisions"))
            row["assets_est"] = row["assets"] + (row["est_extra"] if cfg.get("estimate_missing", True) else 0)
            days.append(row); cal[row["date"]] = row
    gap, gaps = [], []
    for x in days:
        if not x["radio"] and not x["weekend"]: gap.append(x["date"])
        elif x["radio"] and gap: gaps.append(gap); gap = []
    if gap: gaps.append(gap)
    n_gap = 0
    for g in gaps:
        n_gap += len(g)
        health.append(dict(sev="warn", kind="missing_radio", label="Weekday(s) with no radio", date=date.fromisoformat(g[0]), project=f"{len(g)} weekday(s)" , detail=f"No radio in the data from {g[0]} to {g[-1]} ({len(g)} weekdays). Leave, holiday, or radio not provided. Shown as a gap, not as 0 work."))
    rdays = [x for x in days if x["radio"]]
    A = [x["assets"] for x in rdays]

    # ---- projects
    P = defaultdict(lambda: dict(rounds=[], ko=None, ko_assets=None, struck=0, names=set()))
    for d in order:
        for it in work[d].values():
            p = P[it["key"]]; p["name"] = it["name"]; p["campaign"] = it["campaign"]; p["kind"] = it["kind"]
            p["rounds"].append((d, it["stage"], it["assets"], it["stage_family"], it.get("credited_from")))
        for it in kos[d].values():
            p = P[it["key"]]; p.setdefault("name", it["name"]); p.setdefault("campaign", it["campaign"]); p.setdefault("kind", it["kind"])
            if p["ko"] is None: p["ko"] = d; p["ko_assets"] = it["assets"]
        for it in strucks[d].values():
            p = P[it["key"]]; p.setdefault("name", it["name"]); p.setdefault("campaign", it["campaign"]); p.setdefault("kind", it["kind"]); p["struck"] += 1
    projects = []
    for key, p in P.items():
        r = p["rounds"]; a = [x[2] for x in r if x[2]]
        first = r[0][0] if r else None
        lead = (first - p["ko"]).days if (p["ko"] and first and first >= p["ko"]) else None
        projects.append(dict(name=p["name"], campaign=p["campaign"], kind=p["kind"], rounds=len(r), first=first.isoformat() if first else "", last=r[-1][0].isoformat() if r else "",
                             assets_total=sum(a), assets_max=max(a) if a else None, missing_rounds=sum(1 for x in r if x[2] is None), struck=p["struck"],
                             ko=p["ko"].isoformat() if p["ko"] else "", ko_to_first_days=lead, rework_rounds=sum(1 for x in r if x[3] in ("Additional revisions",) or re.match(r"RD([2-9])", x[1])),
                             journey=" → ".join(f"{x[1]} ({x[0].strftime('%d %b')})" for x in r)))
        if a and len(set(a)) > 1:
            health.append(dict(sev="info", kind="count_varies", label="Asset count differs between days for one project", date=None, project=p["name"], detail="Counts seen: " + ", ".join(str(x) for x in sorted(set(a))) + ". Each day uses its own number."))
    projects.sort(key=lambda x: (-x["assets_total"], x["name"]))
    # near-duplicate project names (typos / renames)
    names = sorted({v["name"] for v in P.values() if "name" in v})
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            va, vb = KINDS_RE.findall(a), KINDS_RE.findall(b)
            if va and vb and va != vb: continue
            if a != b and difflib.SequenceMatcher(None, norm(a), norm(b)).ratio() >= 0.93:
                health.append(dict(sev="warn", kind="near_name", label="Two very similar project names", date=None, project=f"{a}  ~  {b}", detail="Counted as two different projects. If it is one project, fix the spelling in the radio."))

    def group(keyfn, label):
        g = defaultdict(lambda: dict(items=0, assets=0, missing=0, days=set(), projects=set()))
        for it in items:
            k = keyfn(it); x = g[k]; x["items"] += 1; x["assets"] += it["assets"] or 0; x["missing"] += it["assets"] is None; x["days"].add(it["date"]); x["projects"].add(it["name"])
        out = [dict(**{label: k}, items=v["items"], assets=v["assets"], missing=v["missing"], days=len(v["days"]), projects=len(v["projects"]), share=pct(v["assets"], sum(A))) for k, v in g.items()]
        return sorted(out, key=lambda x: -x["assets"])
    stages, families, kinds, campaigns, streams = group(lambda i: i["stage"], "stage"), group(lambda i: i["stage_family"], "family"), group(lambda i: i["kind"], "kind"), group(lambda i: i["campaign"], "campaign"), group(lambda i: i["stream"] or "(not tagged)", "stream")

    # weekday / week / month
    wd = []
    for i, nme in enumerate("Mon Tue Wed Thu Fri Sat Sun".split()):
        v = [x["assets"] for x in rdays if date.fromisoformat(x["date"]).weekday() == i]
        wd.append(dict(day=nme, radios=len(v), total=sum(v), avg=round(sum(v) / len(v), 1) if v else 0, median=med(v), max=max(v) if v else 0,
                       projects=round(sum(x["projects"] for x in rdays if date.fromisoformat(x["date"]).weekday() == i) / len(v), 1) if v else 0))
    def bucket(fn):
        g = defaultdict(list)
        for x in rdays: g[fn(date.fromisoformat(x["date"]))].append(x)
        return [dict(period=k, radios=len(v), assets=sum(z["assets"] for z in v), projects=sum(z["projects"] for z in v), missing=sum(z["missing"] for z in v), avg=round(sum(z["assets"] for z in v) / len(v), 1),
                     ko=sum(z["ko"] for z in v), am_ho=sum(z["am_ho"] for z in v), est_extra=sum(z["est_extra"] for z in v)) for k, v in sorted(g.items())]
    weeks = bucket(lambda d: (d - timedelta(days=d.weekday())).isoformat())
    months = bucket(lambda d: d.strftime("%Y-%m"))
    roll = []
    for i, x in enumerate(rdays):
        seg = [z["assets"] for z in rdays[max(0, i - 6):i + 1]]; x["roll7"] = round(sum(seg) / len(seg), 1)

    # ---- headline stats
    tot_a, tot_p = sum(A), sum(x["projects"] for x in rdays)
    miss = sum(x["missing"] for x in rdays); est = sum(x["est_extra"] for x in rdays)
    top = sorted(rdays, key=lambda x: -x["assets"])
    rw_assets = sum(i["assets"] or 0 for i in items if i["stage_family"] == "Additional revisions" or re.match(r"RD([2-9])", i["stage"]))
    ko_all = sum(x["ko"] for x in rdays)
    leads = [p["ko_to_first_days"] for p in projects if p["ko_to_first_days"] is not None]
    stats = dict(radios=len(rdays), from_=days[0]["date"] if days else "", to=days[-1]["date"] if days else "", calendar_days=len(days),
                 assets=tot_a, projects=tot_p, avg=round(tot_a / len(rdays), 1) if rdays else 0, median=med(A), p90=round(sorted(A)[int(0.9 * (len(A) - 1))], 1) if A else 0,
                 max=max(A) if A else 0, max_date=top[0]["date"] if top else "", zero_days=sum(1 for a in A if a == 0), missing=miss, missing_pct=pct(miss, tot_p), est_extra=est,
                 ko=ko_all, struck=sum(x["struck"] for x in rdays), credited=sum(x["credited"] for x in rdays), credited_assets=sum(x["credited_assets"] for x in rdays),
                 am_ho=sum(x["am_ho"] for x in rdays), am_ho_assets=sum(x["am_ho_assets"] for x in rdays), unique_projects=len([p for p in projects if p["rounds"]]),
                 rework_assets=rw_assets, rework_pct=pct(rw_assets, tot_a), ko_lead_avg=round(sum(leads) / len(leads), 1) if leads else None,
                 missing_radio_days=n_gap, formats=dict(Counter(x["format"] for x in rdays)),
                 stdev=round(statistics.pstdev(A), 1) if len(A) > 1 else 0)
    ins = []
    if rdays:
        ins.append(("Workload", f"{tot_a:,} assets across {tot_p:,} project-handoffs over {len(rdays)} radio days: average {stats['avg']}/day, median {stats['median']}, 90th percentile {stats['p90']}."))
        ins.append(("Peak", f"Busiest day {top[0]['date']} ({top[0]['day']}) with {top[0]['assets']} assets over {top[0]['projects']} projects. " + (f"Top 5 days hold {pct(sum(x['assets'] for x in top[:5]), tot_a)}% of all assets." if len(rdays) >= 10 else "")))
        bw = max(wd, key=lambda x: x["avg"]); lw = min([x for x in wd if x["radios"]], key=lambda x: x["avg"])
        ins.append(("Weekday", f"{bw['day']} is the heaviest weekday (avg {bw['avg']} assets); {lw['day']} the lightest (avg {lw['avg']})."))
        if miss: ins.append(("Missing counts", f"{miss} of {tot_p} worked projects ({stats['missing_pct']}%) have no asset count; the real workload is higher than shown" + (f" (about +{est} assets if each repeated the count seen on its other days)." if est else ".")))
        else: ins.append(("Missing counts", "Every worked project had an asset count."))
        if tot_a: ins.append(("Rework", f"{stats['rework_pct']}% of assets ({rw_assets:,}) were handed off in RD2+ or Additional Revisions rounds, i.e. revision loops rather than first drafts."))
        if kinds: ins.append(("Mix", "Workload by type: " + ", ".join(f"{k['kind']} {k['share']}%" for k in kinds[:3]) + "."))
        if campaigns: ins.append(("Campaigns", f"Largest campaign: {campaigns[0]['campaign']} with {campaigns[0]['assets']:,} assets ({campaigns[0]['share']}%) in {campaigns[0]['projects']} project(s)."))
        if stats["am_ho"]: ins.append(("AM handoff", f"{stats['am_ho']} handoffs ({stats['am_ho_assets']:,} assets) were marked AM HO."))
        if ko_all: ins.append(("Kick-offs", f"{ko_all} KO Ques rows = new projects kicking off (not counted as workload)." + (f" Average {stats['ko_lead_avg']} days from KO row to first handoff, for the {len(leads)} projects where both are visible." if leads else "")))
        if stats["credited"]: ins.append(("Struck-off", f"{stats['struck']} struck-off rows; {stats['credited']} were credited to the previous radio day ({stats['credited_assets']} assets) because that day did not list them."))
        if len(A) >= 8:
            h = len(A) // 2; a1, a2 = sum(A[:h]) / h, sum(A[h:]) / (len(A) - h)
            ins.append(("Trend", f"Second half of the period averages {round(a2,1)} assets/day vs {round(a1,1)} in the first half ({'+' if a2>=a1 else ''}{pct(a2-a1, a1)}%)."))
        if stats["zero_days"]: ins.append(("Quiet days", f"{stats['zero_days']} radio day(s) had nothing worked (due today empty, or only KO / struck rows)."))
        if stats["missing_radio_days"]: ins.append(("Gaps", f"{stats['missing_radio_days']} weekday(s) have no radio in the data; see Limitations."))
    limitations = LIMITS
    health.sort(key=lambda h: (SEV[h["sev"]], str(h.get("date") or ""), h.get("project", "")))
    for h in health:
        if h.get("date"): h["date"] = h["date"].isoformat() if hasattr(h["date"], "isoformat") else h["date"]
    hs = Counter((h["kind"], h["label"], h["sev"]) for h in health)
    health_sum = [dict(kind=k, label=l, sev=s, count=c) for (k, l, s), c in sorted(hs.items(), key=lambda z: (SEV[z[0][2]], -z[1]))]
    # per-radio audit
    audit = []
    for r in radios:
        d = r["date"]
        audit.append(dict(date=d.isoformat(), day=d.strftime("%a"), format=r["format"], file=r["file"], rows_read=len(r["items"]), counted=len(work[d]), ko=len(kos[d]), struck=len(strucks[d]),
                          credited_in=sum(1 for x in work[d].values() if x.get("credited_from")), ignored=r["ignored_other"], assets=cal[d.isoformat()]["assets"], missing=cal[d.isoformat()]["missing"]))
    strike_rows = [dict(date=d.isoformat(), project=i["name"], stage=i["stage"], assets=i["assets"], previous_radio=i["prev"].isoformat() if i.get("prev") else "", outcome=i.get("credit", "")) for d in order for i in strucks[d].values()]
    ko_rows = [dict(date=d.isoformat(), project=i["name"], assets=i["assets"], tentative=i["tentative"], row=i["raw"], struck=i["struck"]) for d in order for i in kos[d].values()]
    return dict(stats=stats, insights=[dict(k=k, t=t) for k, t in ins], days=days, items=items, projects=projects, stages=stages, families=families, kinds=kinds, campaigns=campaigns,
                streams=streams, weekdays=wd, weeks=weeks, months=months, audit=audit, struck=strike_rows, kickoffs=ko_rows, health=dict(items=health, summary=health_sum), limitations=limitations)


LIMITS = [
    dict(t="Only DUE TODAY is read", d="Rows under Kicking Off, In Pipeline and Feedback Awaited are ignored by design, as are old-format rows that do not say 'due today'. Work done in the days before a due date is invisible; the app only sees the handoff day.", i="Workload is hand-off volume, not effort."),
    dict(t="Assets are counted on the due day, not when they were worked", d="An asset appears once per due round. A project handed off in RD1, RD2 and Final is counted three times (each round is real work), but long projects with one due date look like a spike.", i="Spiky days can be one big project."),
    dict(t="Asset count = what the radio says", d="Counts are whatever was typed in the radio at the time. Later scope changes, added or dropped assets are not reflected, and the same project can show different counts on different days.", i="Totals can be off by scope changes."),
    dict(t="Projects with no asset count count as 0", d="They are included in project totals but add 0 assets. The 'estimate' is the median count that same project had on other days; it is only an indication and is never part of the headline asset totals.", i="Headline assets are a floor."),
    dict(t="No time or people dimension", d="The radio has no hours, no designers and no complexity. 100 simple resizes and 100 new layouts weigh the same. Message Hours (Slack timestamps) is the place for time and people.", i="Cannot say who worked or how long."),
    dict(t="Struck-off credit is derived", d="A struck row means it was finished the previous radio day. The app credits the previous radio in the data, not necessarily the exact calendar day, and not at all if the previous radio is missing or already listed the project.", i="Some completions land one radio day off."),
    dict(t="KO Ques rows are excluded", d="They are new projects kicking off. If a KO row also contains real work in the same sentence, that work is not counted.", i="Check KO rows tab."),
    dict(t="Project identity = name before the first ' - '", d="A renamed or mistyped project becomes a new project (near-duplicates are flagged). The same name on one day counts once even if Design and Copy listed different stages.", i="Spelling matters."),
    dict(t="Missing radios look like gaps", d="Weekdays without a radio (leave, holiday, not provided) are shown as gaps, not zero. Weekends are not flagged. If a radio was never posted, its work is missing from the totals.", i="Averages use radio days only."),
    dict(t="Mixed old and new formats", d="The format is detected per day. Old-format rows only count when they literally say 'due today'; the new format counts everything under DUE TODAY. Differences in how teams wrote the radio can shift counts between periods.", i="Compare periods with care."),
    dict(t="AM HO and stage names are text-matched", d="Stage (RD1, Final handoff, Additional Revisions) and the AM HO marker are read from the wording; unusual wording lands in 'Other' / 'Unspecified'.", i="Stage mix is approximate."),
]
