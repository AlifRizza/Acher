# Acher — Pre-build Research

Research conducted before scaffolding. Confirmed stack: **Python (FastAPI) backend + React UI**. Primary platform: macOS. Secondary: Windows. Browsers in scope: Chrome, Arc, Brave (all Chromium, all support AppleScript on macOS).

---

## 1. ActivityWatch — what we're learning from

ActivityWatch is open-source, MIT licensed, Python-based. Worth borrowing concepts from; we will simplify aggressively.

### 1.1 Architecture (watcher / bucket / server)

- **Server** (`aw-server`) — central HTTP service; stores everything in a SQLite-backed bucket store and exposes a REST API. UI talks to the server, not directly to watchers.
- **Watchers** — small standalone processes, one per data source. Each watcher polls its source and POSTs events to the server. Examples:
  - `aw-watcher-window` — active app + window title
  - `aw-watcher-afk` — idle/active
  - `aw-watcher-web` — browser extension that reports active tab URL+title
- **Buckets** — one per (watcher, host) pair. Containers for events.
- **Events** — `{timestamp (UTC ISO8601), duration (seconds), data (JSON)}`. The `data` shape depends on the watcher's event type (e.g. `currentwindow` → `{app, title}`; `web.tab.current` → `{url, title, audible, incognito}`).
- **Heartbeats** — optimization: adjacent events with identical `data` within a "pulsetime" window get merged into one event whose duration spans both. This is how a 30-second poller produces "8 minutes on VS Code" instead of 16 separate rows.

### 1.2 Active-window detection per OS

From `aw-watcher-window`:

| OS | Strategy | Library |
|---|---|---|
| macOS | AppleScript via `osascript` querying System Events for the frontmost process and its `AXMain` window's `AXTitle` (alt strategy: JXA) | stdlib `subprocess` |
| Windows | `win32gui.GetForegroundWindow()` → `win32process.GetWindowThreadProcessId()` → process name; WMI fallback for elevated processes | `pywin32`, `wmi` |
| Linux | X11 via Xlib | `python-xlib` (not relevant for us) |

Polling-based. The watcher loop polls every few seconds and sends a heartbeat; the server merges identical adjacent heartbeats. No event subscriptions / hooks.

### 1.3 Browser tab detection

ActivityWatch uses a **browser extension** (`aw-watcher-web`) — Chrome/Firefox/Safari WebExtension that POSTs the active tab's URL+title to the local server.

**Pro:** uniform interface, captures URL not just title, works on any Chromium browser.
**Con:** user must install an extension in every browser; extension can be disabled; extra moving part.

**For Acher we will NOT use this approach.** We will use **AppleScript on macOS** to read the active tab title directly from Chrome / Arc / Brave (all three ship AppleScript dictionaries with `tell application "X" to get title of active tab of front window`). On Windows we will use **UI Automation** (`uiautomation` or `pywinauto`) to read Chrome's address-bar / tab title from the window's accessibility tree.

This is simpler for the user (no extensions to install) and is exactly what the spec asks for. Tradeoff: we get tab *title* but not *URL*. That matches the schema (`tab_title` only).

### 1.4 Data model — adopt vs. simplify

**Adopt:**
- Single SQLite store. Proven, simple, file-backed.
- UTC timestamps in ISO8601.
- Heartbeat-style merging *conceptually* — we record a row per screenshot tick, and the UI merges visually contiguous same-app blocks into a single timeline bar.

**Simplify (do differently):**
- **No bucket/watcher abstraction.** ActivityWatch's bucket model is built for arbitrary 3rd-party watchers. We own all our data, so a single `screenshots` table is enough. The spec already locked in this schema; we follow it.
- **No HTTP between watcher and server.** Our daemon writes directly to SQLite. FastAPI reads from the same SQLite file. One process boundary, not two.
- **Screenshots are first-class rows**, not separate from activity events. Every row = one screenshot tick = one timeline block.

---

## 2. ManicTime — what we're learning from

Commercial app, Windows-first, paid product. We're studying the UX, not the code.

### 2.1 Timeline UX (Day view)

- Three (or more) horizontal **timelines stacked vertically** for the same day:
  - **Computer usage** (active vs. away/idle)
  - **Applications** (one color per app, contiguous blocks)
  - **Tags** (user-assigned categories — empty until you tag)
- Auto-zooms on first open to the time range that actually contains data (no point showing 3am if you only worked 9–5).
- Click-drag on any timeline = select a time range. Mouse **snaps to block edges**, so selecting "the whole Chrome session" is one drag.
- Selecting a range surfaces an "Add tag" UI — that's the core interaction.

### 2.2 Screenshots — anchoring

Screenshots are pinned to the timeline at the exact second they were captured. Scroll/hover the timeline → the screenshot pane shows what was on screen at that moment. The screenshot is **context for the activity row**, not a separate concept.

### 2.3 Tags

Tags are the central UX concept. They are user-supplied labels applied to a time range. Recommendation in their docs: go general → specific (e.g. `Client X, Project Y, Task Z`). Order matters and is preserved.

### 2.4 What we adopt vs. defer

**Adopt:**
- Day view with horizontal time-blocks color-coded by app.
- Hover a block → thumbnail of the screenshot from that moment.
- Click a block → full-size screenshot modal.
- Manual entries (our "manual screenshot + note + tags") are the equivalent of ManicTime's tagged time.

**Defer / not building:**
- Drag-select-and-tag-a-range. Our manual entries are point-in-time, triggered by hotkey, not range selections. (If the user wants this later, it's an additive feature.)
- Computer-usage / AFK timeline. Out of scope for v1.
- Multiple stacked timelines. We render one timeline (apps) for v1.

---

## 3. Key design decisions for Acher

| Decision | Choice | Reason |
|---|---|---|
| Process model | Single Python daemon does capture + retry-uploader + serves FastAPI on `localhost:7823` | Spec asks for one process; avoids the AW-style watcher/server split |
| App detection (macOS) | `pyobjc` → `NSWorkspace.sharedWorkspace().frontmostApplication()` | Faster, no `osascript` subprocess per tick. Falls back to AppleScript if pyobjc is missing |
| Tab detection (macOS) | AppleScript via `osascript` — `tell app "Google Chrome" to get title of active tab of front window`. Same pattern for Arc and Brave | Already in spec. No extension required. Works for all three Chromium browsers we care about |
| App detection (Windows) | `win32gui.GetForegroundWindow()` + `win32process.GetWindowThreadProcessId()` + `psutil.Process(pid).name()` | Same approach as `aw-watcher-window`. Established pattern |
| Tab detection (Windows) | `uiautomation` library, find Chrome's "Address and search bar" element or active tab's name | UI Automation is the standard accessibility API on Windows |
| Screenshot (macOS) | `screencapture` CLI (`subprocess`) initially. `screencapturekit` optional later | CLI is reliable, requires Screen Recording permission (already in spec), no extra deps |
| Screenshot (Windows) | `mss` + `Pillow` | Standard, fast, no perms needed |
| Storage | SQLite via stdlib `sqlite3`. WAL mode for concurrent reader (FastAPI) + writer (daemon) | No new dep; WAL is the standard fix for the writer-blocks-reader problem |
| Web API | FastAPI + uvicorn | Modern, async, automatic OpenAPI docs (useful for a learning project) |
| Frontend | React + Vite (TypeScript). State: just `useState` / `useEffect` — no Redux | Spec says readable & beginner-friendly. Avoid over-engineering |
| Global hotkey | `pynput` cross-platform listener | Spec already specified pynput. Hotkey: ⌃⌥⇧S (Control+Option+Shift+S) on macOS, Ctrl+Alt+Shift+S on Windows |
| Drive client | `google-api-python-client` + `google-auth-oauthlib` | Official Google libs. OAuth installed-app flow |
| Concurrency | One daemon thread for capture loop, one for retry-uploader, FastAPI in main async event loop | Simple, easy to reason about |
| Browser detect strategy | `BROWSER_BUNDLE_IDS` constant maps app bundle id / process name → AppleScript app name. If frontmost matches, run the tab-title AppleScript; otherwise just record the app name | Keeps tab-detection cost zero for non-browser apps |

---

## 4. Recommended project layout

```
Acher/
├── README.md
├── CLAUDE.md
├── docs/
│   ├── research.md                 # this file
│   └── permissions-setup.md        # macOS Screen Recording + Accessibility (later)
├── .env.example                    # OAuth client id/secret placeholders
├── .gitignore
├── pyproject.toml                  # backend deps (poetry or pip-tools)
├── config.json                     # user-editable runtime config
├── backend/
│   ├── acher/
│   │   ├── __init__.py
│   │   ├── cli.py                  # `acher start|stop|status` entrypoint
│   │   ├── daemon.py               # capture loop + retry-worker orchestrator
│   │   ├── db.py                   # SQLite connection, migrations, queries
│   │   ├── config.py               # load/save config.json + validation
│   │   ├── capture.py              # per-tick: detect app+tab, screenshot, write row
│   │   ├── upload.py               # Drive client + retry queue logic
│   │   ├── retention.py            # cleanup job
│   │   ├── hotkey.py               # pynput listener → manual capture
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── app.py              # FastAPI app
│   │   │   ├── timeline.py         # GET /api/timeline?date=...
│   │   │   ├── screenshots.py      # GET /api/screenshots/{id}, /thumbnail
│   │   │   ├── timesheet.py        # GET /api/timesheet?from=&to=, CSV/XLSX export
│   │   │   ├── settings.py         # GET/PUT /api/settings
│   │   │   └── queue.py            # GET /api/queue, POST /api/queue/retry
│   │   └── platform/
│   │       ├── __init__.py         # platform = mac | windows; chooses impl at import
│   │       ├── base.py             # ABC: capture_screenshot, get_active_app, get_active_tab, paths
│   │       ├── mac.py              # macOS implementation
│   │       └── windows.py          # Windows implementation
│   └── tests/
│       └── ...
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── lib/api.ts              # fetch wrappers
│       ├── pages/
│       │   ├── Timeline.tsx
│       │   ├── Timesheet.tsx
│       │   └── Settings.tsx
│       └── components/
│           ├── TimelineDay.tsx
│           ├── ScreenshotModal.tsx
│           └── ...
└── scripts/
    ├── install-launchd.sh          # writes ~/Library/LaunchAgents/id.acher.daemon.plist
    └── install-windows-autostart.ps1
```

**Why this layout:**
- All OS-conditional code lives behind `platform/`. Business logic in `capture.py`, `upload.py`, `api/` etc. never imports `sys.platform` directly — they import from `acher.platform` and call the abstract methods. This satisfies the spec's "no `if sys.platform` scattered across business logic" constraint.
- FastAPI app split across files in `api/` so each route file is short and readable (this is a learning project — long files are harder to navigate).
- Frontend is a sibling tree, not nested in backend. Built React assets will be served by FastAPI as static files in production, but during dev Vite runs on its own port with a proxy to the backend.
- `scripts/` holds the platform-specific autostart installers. They live in the repo but won't run until Phase 9 (and require explicit user approval per the spec's stop conditions).

---

## 5. Open items before Phase 1

None blocking. Phase 1 is pure scaffolding (folders, SQLite schema, config, .gitignore, .env.example) and is safe to start.

Items deliberately postponed:
- Google Cloud OAuth credentials — user said "local-only first, Drive in Phase 3."
- Screen Recording / Accessibility permissions — documented in Phase 2 README updates; user grants manually.
- launchd plist / Windows Registry — Phase 9; requires explicit approval per spec stop conditions.

---

## Sources

- [ActivityWatch documentation](https://docs.activitywatch.net/en/latest/)
- [ActivityWatch — Buckets and Events](https://docs.activitywatch.net/en/latest/buckets-and-events.html)
- [aw-watcher-window source (GitHub)](https://github.com/ActivityWatch/aw-watcher-window)
- [aw-watcher-web source (GitHub)](https://github.com/ActivityWatch/aw-watcher-web)
- [ManicTime — Time tracking with screenshots](https://manictime.com/features/time-tracking-with-screenshots)
- [ManicTime — Day view docs](https://docs.manictime.com/win-client/overview)
- [ManicTime — Tagging docs](https://docs.manictime.com/win-client/tagging)
- [ManicTime — How time selection works (blog)](https://blog.manictime.com/articles/2025-nov/selecting-time/)
