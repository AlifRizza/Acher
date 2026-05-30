# Acher — Project Status & Handoff

> Living handoff doc for resuming work in a fresh session. Last updated **2026-05-30**.
> Repo: **https://github.com/AlifRizza/Acher** (private). Current `main` = commit `ad14a42`.

Acher is a **local-first activity tracker**: periodic screenshots + a continuous
active-app/idle timeline, manual hotkey captures with notes/tags, optional Google
Drive sync, CSV/XLSX timesheet export, and a React timeline GUI. **The entire
project was vibe-coded** (built conversationally with an AI agent) — treat it as a
learning/experimentation project, not audited production software.

---

## 1. Architecture (one process)

```
acher daemon (one Python process)
├── capture loop      — screenshot + active app/tab every N min (paused when idle/locked)
├── activity watcher  — samples presence every ~5s → active/idle/locked spans
├── uploader          — Drive upload queue + retry (only if drive_connected)
├── retention         — deletes screenshots past the window, daily
├── hotkey listener   — ⌃⌥⇧S → note/tags dialog → manual capture
└── FastAPI server    — serves /api/* AND the built GUI, on 127.0.0.1:7823
```

- **Daemon writes, API reads.** SQLite in WAL mode so reads never block the writer.
- **Loopback only** (`127.0.0.1`) — never exposed off-host.
- Data lives in `~/Library/Application Support/Acher/` (macOS): `acher.db`,
  `screenshots/YYYY-MM/`, logs, `token.json`. Run `acher paths` to see them.

### Backend modules (`backend/acher/`)
`capture.py` · `daemon.py` · `db.py` · `config.py` · `queries.py` · `api.py` ·
`activity.py` · `uploader.py` · `drive.py` · `retention.py` · `hotkey.py` ·
`export.py` · `cli.py` · `platform/{base,mac,windows}.py`

### Frontend (`frontend/`, React + Vite + TS)
- Pages: `DayView` (timeline + screenshot grid), `TimesheetPage`, `Statistics`, `Settings`
- Components: `TimelineRow`, `ScreenshotPopup`, `ScreenshotCard`, `ScreenshotModal`, `MiniScrubber`, `SearchPanel`, `StatsBar`
- `lib/`: `api.ts` (fetch wrappers), `timeline.ts` (block reconstruction), `colors.ts`, `format.ts`
- `pages/Timeline.tsx` is the **old standalone grid — superseded by DayView, no longer routed** (left on disk; safe to delete).

---

## 2. Feature status

| Feature | Status | Notes |
|---|---|---|
| Auto screenshot capture | ✅ done, live-verified | every `interval_minutes`; real PNGs confirmed on disk |
| Active app / tab detection | ✅ done | `NSWorkspace` + AppleScript (Chrome/Arc/Brave/Safari) |
| Activity watcher (continuous spans) | ✅ done, live-verified | second-accurate app bars, not screenshot-inferred |
| Idle detection (pause capture) | ⚠️ code done, **needs real-world test** | Quartz idle; **fails open** without Accessibility perm |
| Screen-off/lock detection | ⚠️ code done, **needs real-world test** | pauses capture; verify by locking screen |
| Manual capture (hotkey ⌃⌥⇧S) | ✅ done; **keypress needs Accessibility** | CLI path `acher capture` verified |
| Day timeline UI (multi-row) | ✅ done | Computer Usage / Apps / Browser Tabs / Screenshots / Manual Entries |
| Screenshot grid (below timeline) | ✅ done | per-day, dims on search |
| Search (app/tab/note/tags) | ✅ done | `/api/search` |
| Timesheet + CSV export | ✅ done | CSV stdlib |
| Timesheet XLSX export | ✅ done, **optional dep** | needs `pip install -e ".[export]"` (openpyxl); else 501 |
| Statistics tab (bar + heatmap) | ✅ done | Chart.js |
| Settings tab (edit config) | ✅ done | `GET/PUT /api/config`; **applies on daemon restart** |
| Retention cleanup | ✅ done | `1_week`…`6_months`/`never`; `acher purge` |
| Google Drive sync | ⚠️ **code-complete, never live-tested** | needs real OAuth creds — see §6 |
| Autostart at login | ✅ done, live-verified (macOS) | launchd `RunAtLoad`+`KeepAlive` |
| One-command install | ✅ done (macOS/Linux) | `./install.sh` |
| Daemon serves GUI | ✅ done | FastAPI mounts `frontend/dist` at `/` |

---

## 3. Verification baseline
- **Backend: 103 pytest tests pass** (`pytest backend/`), `ruff check backend/` clean.
- Test files: activity(12), api(10), autostart(7), capture_manual(4), config_api(7),
  hotkey(6), queries(10), retention(6), search(9), timesheet(11), uploader(8).
- Frontend `npm run build` clean; **fresh-clone build verified** (anyone can build it).
- DB schema **version 2** (screenshots, upload_queue, activity).

---

## 4. API endpoints (all `127.0.0.1:7823`, read-only except PUT /api/config)
`GET /api/health` · `GET /api/screenshots` · `GET /api/screenshots/{id}` ·
`GET /api/screenshots/{id}/image` · `GET /api/stats` · `GET /api/timesheet` ·
`GET /api/timesheet/export?fmt=csv|xlsx` · `GET /api/search?q=` ·
`GET /api/activity` · `GET /api/config` · `PUT /api/config`
Interactive docs at `/docs`. The GUI is served at `/`.

## 5. Config (`config.json`, editable in Settings tab)
| Key | Range / values | Notes |
|---|---|---|
| `interval_minutes` | **integer 1–120** | capture cadence (was fixed 1/3/5; now any int) |
| `idle_threshold_minutes` | 1–120 | no input this long → idle → capture pauses |
| `activity_sample_seconds` | 1–60 | how often the watcher samples |
| `retention_period` | 1_week / 1_month / 3_months / 6_months / never | |
| `hotkey` | e.g. `ctrl+alt+shift+s` | cmd/option accepted |
| `browsers` | subset of Chrome/Arc/Brave/Safari/Firefox | tab-title detection |
| `drive_connected` | bool | flipped true by `acher auth` |
| `port` | 1024–65535 | default 7823 |

**Important:** the daemon reads config **at startup**, so Settings changes (or
hand-edits) take effect only after a **daemon restart**.

---

## 6. Outstanding work / TODO (next sessions)

### Must-do to fully close current features
1. **Live-test idle + screen-off** during a real work session — confirm capture
   pauses (amber/gray on the Computer Usage row) and resumes. Needs macOS
   **Accessibility/Input-Monitoring** granted or idle silently fails open.
2. **Live-test the global hotkey** (⌃⌥⇧S) — needs Accessibility. `acher capture` works regardless.
3. **Google Drive sync, end-to-end** — the whole path is coded + unit-tested but
   **never run against real Drive**. Steps: create a Google Cloud OAuth "Desktop
   app" client → put `GOOGLE_OAUTH_CLIENT_ID/SECRET` in `.env` →
   `pip install -e ".[drive]"` → `acher auth` → `acher start` → verify upload +
   offline-buffer-then-drain. See `docs/drive-setup.md`.

### Portability ("works on my device, not others") — decided NOT to use Docker
Docker is the wrong fit: the daemon needs host screen/window/input/launchd access
a container can't reach. Better paths, in priority order:
1. **`acher doctor` command** — first-run check of Python version, Screen Recording
   + Accessibility permissions, port availability; print what's missing. Kills most
   "doesn't work on my machine."
2. **Pin dependencies** (lock file / version pins) for reproducible installs.
3. **Native packaging** (PyInstaller / py2app → `.app`) — the real "easy install
   for non-developers" answer; the macOS-native equivalent of Docker-for-distribution.
4. **`install.ps1`** — Windows equivalent of `install.sh`.

### Known feature gaps / future ideas (discussed, not built)
- **Multi-monitor capture** — `screencapture -x` grabs the **primary display only**.
  Spaces/swipe is fine (same display), but a second monitor isn't captured. Fix:
  capture all displays (one PNG per display + a `display_index` column) — capture
  code + schema change. **Laptop-only users are unaffected.**
- **Drive-only / delete-local-after-upload mode** — not possible today; app is
  local-first and the UI/`/image` endpoint serve from local paths. Would need the
  image endpoint to fetch from Drive (slower, needs auth, breaks offline).
- **Tag-painting timeline row** and a true range-select-and-tag UX (ManicTime-style)
  — needs a new table + write endpoints.
- **Storage estimate in the UI** — ~1.9 MB/screenshot measured; ~27 GB/mo at 3-min
  24/7, far less with realistic active hours + retention. Could surface this in Settings.
- **JPEG/quality option** to cut file size ~3–5× (capture-code change; currently PNG).

---

## 7. Resolved bugs (so they're not re-investigated)
- **Activity watcher not wired into daemon** (`b306ea5`) — two `daemon.run()` edits
  silently failed in an earlier commit; watcher wasn't started and capture wasn't
  gated. Fixed + `prime()` added so the first tick is gated accurately.
- **Manual capture recorded the dialog as the app** (`b08377a`) — the note dialog
  steals focus, so `get_active_window()` ran too late and saw "osascript". Fixed by
  detecting the window **before** the dialog and passing it through. (A suspected
  second bug — osascript returning the prompt — was investigated and disproved.)
- **`.gitignore` excluded `frontend/src/lib/`** (`718de93`) — a bare `lib/` rule
  (for Python build output) also matched the frontend; `api.ts`/`timeline.ts`/
  `colors.ts`/`format.ts` were never committed, so a fresh clone couldn't build.
  Fixed by anchoring build-dir rules to repo root (`/lib/`, `/dist/`, …).
- **Settings 404 + duplicate daemons** (`ad14a42`) — `install.sh` started a `nohup`
  daemon AND launchd; the stale nohup (old code, no `/api/config`) held the port.
  Fixed: install stops any running daemon first, launchd is the single starter.
- **Grid cards misaligned** (`ad14a42`) — `.card` `<button>` had no width inside its
  wrapper div; added `width:100%`.

---

## 8. How to run / operate

```bash
# One-command install (macOS/Linux): venv + deps + build UI + autostart + open GUI
./install.sh

# Manual / dev
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # + ".[drive]" for Drive, ".[export]" for XLSX
acher init                          # create DB
acher start                         # run daemon in foreground
# GUI: http://127.0.0.1:7823   (or `cd frontend && npm run dev` for live FE dev on :5180)

# Restart the background daemon to apply new code/config (THE reliable incantation):
.venv/bin/acher uninstall; pkill -f "acher.*start"; sleep 1; .venv/bin/acher install

acher capture --note "x" --tags "a,b"   # manual capture without the hotkey
acher purge                              # run retention now
acher paths                              # where data lives
```

### Env / gotchas
- `acher` lives in `.venv/bin/` — in a fresh shell use `.venv/bin/acher` or activate the venv.
- macOS needs **Screen Recording** (real screenshots) + **Accessibility** (hotkey,
  idle) granted to whatever launches the daemon. After a reboot launchd launches it,
  which may re-prompt — grant once more and it sticks.
- After changing the frontend, `npm run build` (the daemon serves `frontend/dist`),
  then **hard-refresh** the browser (⌘⇧R) to drop the cached bundle.
- Node v26 / npm 11 and Python (miniforge) are present on the dev machine.

---

## 9. Working notes for the next AI session
- **Verify every file write by re-reading.** This project was built in an environment
  where tool output was intermittently garbled/fabricated and some edits silently
  failed (see the resolved bugs — several were caused by edits that didn't land).
  Don't trust "success" without a grep/build/test confirming it.
- **Outward/persistent actions are the user's to run** (`acher install`, daemon
  restarts, `git push` of system changes, anything touching login items). Build &
  stage, then hand off the exact command.
- Keep changes **surgical** and run `pytest backend/` + `ruff check backend/` +
  `npm run build` before committing. End commit messages with the Co-Authored-By
  trailer already used throughout the history.
- There is **no `.claude/spec.md`** — the phase plan source of truth is
  `docs/research.md` plus this file.
