# Daily Radio Insights v1.0.0
Turns a year of Sephora daily radios ("@here <date> Project Status") into workload insights. Same look as Vision Insights / Message Hours; same Google sign-in and push-to-sheet code.

Run: `start.bat` (Windows) or `./start.sh`, then open http://127.0.0.1:8766 (opens automatically).
Drop `.txt` / `.md` / `.docx` files or paste text. Old and new format can be mixed; the format is detected per day. Imported radios and settings are kept in a local SQLite file (`%APPDATA%\Daily Radio Insights`). "Load demo data" uses a synthetic year, not real data.

## Counting rules (all from the brief)
1. **Only DUE TODAY is read.** New format: the DUE TODAY section. Old format: only rows that say "due today". Kicking Off / In Pipeline / Feedback Awaited, WRIKE and SLACK RESPONSES are ignored.
2. **KO Ques = a new project kicking off**, never workload. Listed on the "Kick-offs & struck-off" tab.
3. **Struck-off (~~x~~) in DUE TODAY = finished the previous day.** Not counted on its own day. Credited to the previous radio in the data, unless that radio already listed the project (Settings can switch the credit off).
4. **One project name counts once per day** (Design + Copy lists in the old format are merged). Project name = text before the first " - ".
5. Rows like `1. NA` are "nothing due".
6. **Projects without an asset count are never ignored**: counted as projects, 0 assets, graphed, listed, and optionally estimated (hatched) from the same project's other days. The estimate is never mixed into headline totals.

## Tabs
Overview (workload per day/week/month + no-count chart + insights) · Days · Projects · Mix & patterns (weekday, calendar heat-map, campaigns, stages, rework, Bun/Der) · Missing counts · Kick-offs & struck-off · Radio audit (one line per radio) · **Limitations** (what the method cannot tell + every anomaly found in your radios).
The period selector at the top drives every tab. Click any day (chart, heat-map, table row) for its rows.

## Push to Google Sheet
15 tabs, one per view, whole data set (not only the selected period): Insights, Daily Workload (with chart), Items Worked, Projects, Campaigns, Stages, Stage Groups & Type, Weekdays, Weekly, Monthly, Missing Asset Counts, KO Kickoffs, Struck-off, Radio Audit, Limitations. Connect Google in Settings (@esga.co only), paste the sheet link, push.

`python tests/test_rules.py` checks the counting rules.
