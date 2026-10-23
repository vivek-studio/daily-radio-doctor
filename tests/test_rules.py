"""Run: python tests/test_rules.py   -- checks every counting rule from the brief."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from analysis import analyse

CFG = dict(credit_struck=True, estimate_missing=True)
def run(t, cfg=CFG): return analyse([dict(name="t", text=t)], cfg)
def day(r, d): return next(x for x in r["days"] if x["date"] == d)

OLD = """@here 01 October, 2025 Project Status
Design
1. Alpha Der A - Final handoff due today (10 assets)
2. Beta Bun A - RD2 due on 10/3 (99 assets)
3. Gamma Bun B - KO questions due today (13 assets)
4. Delta Der C - RD1 due today
Copy
1. Alpha Der A - Final handoff due today (10 assets)
2. Delta Der C - RD1 due today
WRIKE RESPONSES
1. Zeta Der A - RD1 due today (500 assets)
"""
NEW = """@here 02 October, 2025 Project Status
DUE TODAY
1. Alpha Der B - RD1 (20 assets)
2. Eps Bun A - KO Ques - RD1 tentatively due on 10/9 (61 assets)
3. ~~Beta Bun A - Final handoff (40 assets)~~
4. ~Gone Der A - RD2 (7 assets)~
PROJECTS KICKING OFF
1. NA
IN PIPELINE
1. Pipe Der A - RD1 due on 10/9 (300 assets)
FEEDBACK AWAITED
1. Fb Der A - Feedback awaited by 10/9 - RD3 due on 10/12 (200 assets)
"""
r = run(OLD + "\n" + NEW, dict(credit_struck=False))
a, b = day(r, "2025-10-01"), day(r, "2025-10-02")
assert a["projects"] == 2 and a["assets"] == 10 and a["missing"] == 1, a   # dedupe Design/Copy; RD2-due-10/3 ignored; KO ignored; Zeta after WRIKE ignored
assert a["ko"] == 1 and a["ko_assets"] == 13
assert b["projects"] == 1 and b["assets"] == 20, b                           # only DUE TODAY; KO + struck + other sections not counted
assert b["ko"] == 1 and b["struck"] == 2
# struck-off rows are credited to the previous radio day when it did not list them (Beta 40 + Gone 7)
r = run(OLD + "\n" + NEW)
a2 = day(r, "2025-10-01"); assert a2["credited"] == 2 and a2["credited_assets"] == 47, a2
assert a2["projects"] == 4 and a2["assets"] == 57, a2
# struck project that the previous radio already listed is not double counted
T = "@here 01 October, 2025 Project Status\nDUE TODAY\n1. Alpha Der A - RD1 (10 assets)\n@here 02 October, 2025 Project Status\nDUE TODAY\n1. ~~Alpha Der A - RD1 (10 assets)~~\n"
r3 = run(T); assert day(r3, "2025-10-01")["assets"] == 10 and day(r3, "2025-10-02")["assets"] == 0
# NA / empty
r4 = run("@here 03 October, 2025 Project Status\nDUE TODAY\n1. NA\n"); assert r4["stats"]["projects"] == 0 and r4["stats"]["radios"] == 1
print("all rule tests passed")
