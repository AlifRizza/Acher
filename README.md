# Acher

**Local-first activity tracker** — periodic screenshots, an active-app/tab timeline, manual hotkey captures with notes & tags, optional Google Drive sync, and CSV/XLSX timesheet export. Your data stays on your machine in SQLite + PNG files unless you explicitly turn on Drive sync.

- **Backend:** Python daemon (capture loop + retry-uploader + retention) and a local FastAPI read API.
- **Frontend:** React + Vite timeline UI that talks to the local API.
- **Platforms:** macOS (primary) and Windows. Browser tab detection for Chrome, Arc, and Brave.

> Acher is a learning-oriented, single-user app. The API binds to `127.0.0.1` only and is never exposed off-host.

---

## Features

- ⏱ **Automatic capture** — a screenshot every N minutes (default 3), tagged with the active app and, for supported browsers, the active tab title.
- ⌨️ **Manual capture** — a global hotkey (default ⌃⌥⇧S) pops a native dialog for an activity note + tags, then captures.
- 🗂 **Timeline UI** — browse, search, and filter captures by app; click any thumbnail for the full-size screenshot and its metadata.
- 📊 **Timesheet + export** — per-app time roll-up over any date range, downloadable as CSV or XLSX.
- ☁️ **Optional Drive sync** — uploads each screenshot to your own Google Drive with offline buffering and exponential-backoff retry. Off by default.
- 🧹 **Retention** — automatically deletes screenshots older than your chosen window (1 week → 6 months, or never).
- 🚀 **Autostart** — register the daemon to launch at login (launchd on macOS, Registry on Windows).

---

## Architecture

```
┌─────────────────────── acher daemon (one process) ───────────────────────┐
│  capture loop ──┐                                                         │
│  uploader     ──┼──► SQLite (WAL)  ◄──── FastAPI read API (127.0.0.1)     │
│  retention    ──┤        ▲                        ▲                       │
│  hotkey listener┘        │                        │                       │
└──────────────────────────┼────────────────────────┼──────────────────────┘
                           │                        │
                    PNG files on disk        React UI (Vite, proxies /api)
```

- The **daemon writes**; the **API reads**. SQLite runs in WAL mode so reads never block the writer.
- Screenshots live at `<app-data>/screenshots/YYYY-MM/`, the DB at `<app-data>/acher.db`.
  Run `acher paths` to see the resolved locations (macOS: `~/Library/Application Support/Acher/`).

---

## Requirements

- **Python ≥ 3.10**
- **Node ≥ 18** and npm (only for the frontend UI)
- **macOS** or **Windows**

---

## Installation

### 1. Clone and set up the backend

```bash
git clone https://github.com/<your-account>/Acher.git
cd Acher

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Core install (capture + API + hotkey + retention + CSV export):
pip install -e .

# Or include dev tools (pytest, ruff) for running the test suite:
pip install -e ".[dev]"
```

Optional extras (install only what you want):

```bash
pip install -e ".[drive]"    # Google Drive sync
pip install -e ".[export]"   # XLSX timesheet export (CSV works without this)
```

### 2. Initialize and grant permissions

```bash
acher init        # create the database + app-data directory
acher paths       # show where screenshots / DB / logs live
```

**macOS permissions** (required for real screenshots and tab detection — see
[`docs/permissions-setup.md`](docs/permissions-setup.md)):

- **Screen Recording** → your terminal app (else screenshots are blank).
- **Automation** → allow control of Chrome/Arc/Brave (for tab titles). macOS prompts on first use.
- **Accessibility** → your terminal app (required for the global hotkey).

### 3. Run the daemon

```bash
acher start       # foreground: capture loop + API + hotkey + retention
```

Leave it running. Press the hotkey (⌃⌥⇧S) any time to take a manual capture with a note.

### 4. Run the frontend UI

In a second terminal:

```bash
cd frontend
npm install
npm run dev       # serves the UI (prints a localhost URL, e.g. http://localhost:5173)
```

The dev server proxies `/api` to the backend on port `7823`, so the timeline and
screenshots load with no extra configuration. Open the printed URL in your browser.

To build the production bundle:

```bash
npm run build     # outputs to frontend/dist/
```

---

## Usage

### CLI

| Command | What it does |
|---|---|
| `acher start` | Run the daemon in the foreground (capture, API, hotkey, retention). |
| `acher capture [--note "…"] [--tags "a,b"]` | Take one manual capture now (no hotkey needed). |
| `acher purge` | Delete screenshots past the retention window now. |
| `acher auth` | Authorize Google Drive sync (needs the `[drive]` extra + OAuth creds). |
| `acher install` | Register Acher to launch at login. |
| `acher uninstall` | Remove the launch-at-login entry. |
| `acher config` | Print the active configuration. |
| `acher paths` | Print resolved data/screenshot/DB/log paths. |

### Configuration — `config.json`

```json
{
  "interval_minutes": 3,
  "retention_period": "1_month",
  "hotkey": "ctrl+alt+shift+s",
  "browsers": ["Chrome", "Arc", "Brave"],
  "drive_connected": false,
  "port": 7823
}
```

- `interval_minutes` — capture cadence: `1`, `3`, or `5`.
- `retention_period` — `1_week`, `1_month`, `3_months`, `6_months`, or `never`.
- `hotkey` — modifiers + key, e.g. `ctrl+alt+shift+s` (`cmd`/`option` also accepted).
- `browsers` — which browsers to read tab titles from (`Chrome`, `Arc`, `Brave`, `Safari`).
- `port` — local API port (loopback only).

### Timesheet export

From the UI's **Timesheet** tab, pick a date range and click **Export CSV** / **Export XLSX**.
Or hit the API directly:

```bash
curl "http://127.0.0.1:7823/api/timesheet/export?fmt=csv" -o timesheet.csv
```

Time is estimated as *(screenshot count) × interval* — a simple sampling model.

### Google Drive sync (optional)

See [`docs/drive-setup.md`](docs/drive-setup.md) for the full walkthrough. In short:

```bash
pip install -e ".[drive]"
# create an OAuth "Desktop app" client in Google Cloud, put the id/secret in .env
acher auth                # browser consent, caches a token
acher start               # screenshots now upload to "Acher Screenshots/YYYY-MM/"
```

Offline captures queue locally and drain automatically when you reconnect.

### Autostart at login

```bash
acher install     # macOS: ~/Library/LaunchAgents/id.acher.daemon.plist
                  # Windows: HKCU\…\CurrentVersion\Run
acher uninstall   # remove it
```

---

## API reference

All endpoints are served on `http://127.0.0.1:<port>` (default `7823`):

| Method & path | Description |
|---|---|
| `GET /api/health` | Liveness probe. |
| `GET /api/screenshots` | Filtered, paged timeline (`app`, `q`, `start`, `end`, `is_manual`, `limit`, `offset`). |
| `GET /api/screenshots/{id}` | One screenshot's metadata. |
| `GET /api/screenshots/{id}/image` | The PNG bytes. |
| `GET /api/stats` | Totals, per-status, top apps, time span. |
| `GET /api/timesheet` | Per-app time roll-up (`start`, `end`). |
| `GET /api/timesheet/export` | Same, as a download (`fmt=csv\|xlsx`). |

Interactive docs are available at `/docs` (FastAPI Swagger UI) while the daemon runs.

---

## Project layout

```
Acher/
├── backend/
│   ├── acher/
│   │   ├── capture.py        # one capture tick (auto + manual)
│   │   ├── daemon.py         # orchestrates capture / uploader / API / hotkey / retention threads
│   │   ├── db.py             # SQLite schema, WAL connection, migrations
│   │   ├── queries.py        # read-side queries (timeline, stats, timesheet)
│   │   ├── api.py            # FastAPI read API
│   │   ├── uploader.py       # Drive upload queue + retry/backoff
│   │   ├── drive.py          # Google Drive v3 client + OAuth
│   │   ├── retention.py      # cleanup job
│   │   ├── hotkey.py         # global hotkey → manual capture
│   │   ├── export.py         # CSV / XLSX timesheet export
│   │   ├── config.py         # config.json load/save/validate
│   │   ├── cli.py            # `acher …` entrypoint
│   │   └── platform/         # OS-specific impls behind one interface (mac, windows)
│   └── tests/                # pytest suite
├── frontend/                 # React + Vite timeline UI
├── docs/                     # permissions + Drive setup + research notes
├── config.json               # user-editable runtime config
└── pyproject.toml
```

---

## Development

```bash
pip install -e ".[dev]"
pytest backend/                # run the test suite
ruff check backend/            # lint

cd frontend && npm run build   # type-check + build the UI
```

---

## Privacy

Acher captures screenshots of your screen on an interval. Everything is stored
**locally** by default — there is no telemetry and no network activity unless you
explicitly enable Google Drive sync. Secrets (`.env`, OAuth tokens) are
git-ignored and stored outside the repo.

---

## License

[MIT](LICENSE) © 2026 AlifRizza
