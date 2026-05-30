# Acher — Permissions Setup

Acher needs a few OS-level permissions to capture screenshots and read the
active window. macOS requires you to grant these manually in System Settings;
Windows needs nothing.

Do this once, before running `acher start` for the first time.

---

## macOS

### 1. Screen Recording — required

Without this, `screencapture` produces a black or wallpaper-only PNG.

1. Open **System Settings → Privacy & Security → Screen Recording**.
2. Click the **+** button.
3. Add the app you're running Acher from. Pick *one* of the following — it
   matches whichever process actually invokes the daemon:
   - **Terminal.app** — if you start Acher via `acher start` from Terminal.
   - **iTerm.app** — same, from iTerm2.
   - **Visual Studio Code** — if you start it from the VS Code terminal.
   - **Python** itself — if you run `python -m acher.daemon` directly. You'll
     find the executable at the path printed by `which python3` (often
     `/usr/local/bin/python3` or your venv's `bin/python3`).
4. Toggle it **on**.
5. **Quit and reopen** the terminal app. The permission only takes effect on
   restart; in-flight processes won't pick it up.

**Verify:** run `acher start` for one capture interval and check that
`~/Library/Application Support/Acher/screenshots/YYYY-MM/` contains a real
screenshot (not a black PNG).

### 2. Automation — required for browser tab titles

macOS prompts the first time Acher runs an AppleScript against Chrome / Arc /
Brave. You'll see a dialog like:

> "Terminal" wants access to control "Google Chrome". Allowing control will
> provide access to documents and data in "Google Chrome".

Click **OK**.

If you accidentally clicked "Don't Allow", undo it manually:

1. Open **System Settings → Privacy & Security → Automation**.
2. Find your terminal app.
3. Tick the browsers Acher should read titles from (Google Chrome, Arc,
   Brave Browser).

This permission persists per pair of (controlling app, controlled app), so
once Terminal has Chrome access, you won't be prompted again.

### 3. Accessibility — NOT required

Some activity trackers ask for Accessibility permission to read window
titles via the system-wide accessibility tree. Acher does not — `NSWorkspace`
gives us the frontmost app name without it, and we use AppleScript (not
Accessibility) for browser tabs.

If macOS does prompt you for Accessibility, it's fine to deny.

---

## Windows

No permissions to grant. UAC elevation is *not* required — Acher runs as the
current user and uses standard win32 APIs that work without admin rights.

The one caveat: capturing screenshots of an elevated-as-admin window (e.g.
Task Manager run as administrator) requires Acher itself to run elevated.
The default `acher start` does not elevate. If you need this, run Acher
from an elevated terminal — but most users don't.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Screenshots are black / show only the wallpaper | Screen Recording not granted, or terminal not restarted after granting | Re-do step 1 above; **quit and reopen** the terminal |
| `screencapture failed (exit 1): could not create image from display` | Same as above | Same as above |
| Browser tabs always show as no-tab (app name only) | Automation permission for that browser is missing or denied | System Settings → Privacy & Security → Automation; ensure each browser is ticked under your terminal app |
| All AppleScript calls fail with `errAEEventNotPermitted (-1743)` | Automation permission rejected | Same as above. If the dialog never appeared, click any tracked browser to bring it to the foreground and run `acher start` again — that should re-trigger the prompt |
| `osascript timed out` in logs | The browser is unresponsive (likely on a sync RPC, or a modal dialog is open) | This is benign — Acher just records the app name without the tab title. Will retry next tick |
