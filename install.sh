#!/usr/bin/env bash
#
# Acher one-command installer (macOS / Linux).
#
# Does everything end to end:
#   1. creates a Python venv and installs Acher
#   2. builds the React UI (so the daemon can serve it)
#   3. initializes the database
#   4. registers Acher to auto-start at login (background)
#   5. starts it now and opens the GUI in your browser
#
# Re-running is safe (idempotent). Requires: python3, and node/npm for the UI.
#
# Usage:  ./install.sh
#
set -euo pipefail

# Resolve the repo root (this script's directory) so it works from anywhere.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="$(python3 -c 'import json,sys; print(json.load(open("config.json")).get("port",7823))' 2>/dev/null || echo 7823)"
URL="http://127.0.0.1:${PORT}"

echo "==> Acher installer"
echo "    repo: $ROOT"

# --- 1. Python venv + backend install ---
if [ ! -d .venv ]; then
  echo "==> Creating virtualenv (.venv)"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "==> Installing Acher (pip)"
pip install --quiet --upgrade pip
pip install --quiet -e .

# --- 2. Build the frontend (optional but recommended) ---
if command -v npm >/dev/null 2>&1; then
  echo "==> Building the web UI"
  ( cd frontend && npm install --silent && npm run build >/dev/null )
else
  echo "!!  npm not found — skipping UI build. The daemon will run API-only."
  echo "    Install Node.js, then re-run this script to get the GUI."
fi

# --- 3. Initialize the database / app-data dir ---
echo "==> Initializing database"
acher init

# --- 4. Register auto-start at login ---
echo "==> Registering auto-start at login"
acher install

# --- 5. Start now (background) and open the browser ---
# `acher install` registers the login agent but doesn't necessarily start it
# this instant, so launch a detached daemon for the current session too.
if ! curl -sf "${URL}/api/health" >/dev/null 2>&1; then
  echo "==> Starting Acher in the background"
  nohup acher start >/dev/null 2>&1 &
fi

# Wait for the server to come up, then open the GUI.
echo -n "==> Waiting for Acher to start"
for _ in $(seq 1 40); do
  if curl -sf "${URL}/api/health" >/dev/null 2>&1; then break; fi
  echo -n "."; sleep 0.25
done
echo

if curl -sf "${URL}/api/health" >/dev/null 2>&1; then
  echo "==> Acher is running at ${URL}"
  if command -v open >/dev/null 2>&1; then open "${URL}"          # macOS
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "${URL}" # Linux
  fi
else
  echo "!!  Acher did not respond yet. Check the log:"
  echo "    $(acher paths | python3 -c 'import json,sys;print(json.load(sys.stdin)["log_path"])' 2>/dev/null || echo '~/Library/Application Support/Acher/acher.log')"
fi

echo
echo "Done. Acher will now start automatically at login."
echo "  • Open the GUI:     ${URL}"
echo "  • Stop auto-start:  acher uninstall"
echo "  • macOS: grant Screen Recording (+ Accessibility for the hotkey) — see docs/permissions-setup.md"
