#!/usr/bin/env bash
#
# Acher one-command installer (macOS / Linux).
#
# Does everything end to end:
#   1. creates a Python venv and installs Acher
#   2. builds the React UI (so the daemon can serve it)
#   3. initializes the database
#   4. stops any old daemon, then registers Acher to auto-start at login
#   5. waits for it to come up and opens the GUI in your browser
#
# Re-running is safe (idempotent). Requires: python3, and node/npm for the UI.
#
# Usage:  ./install.sh
#
set -euo pipefail

# Resolve the repo root (this script's directory) so it works from anywhere.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="$(python3 -c 'import json; print(json.load(open("config.json")).get("port",7823))' 2>/dev/null || echo 7823)"
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

# --- 4. Stop any daemon already running, then register auto-start ---
# This prevents duplicates: a stale foreground/nohup daemon from a previous run
# would keep the old code and hold the port, so we clear it first. launchd is
# then the SINGLE thing that starts the daemon (its RunAtLoad starts it now),
# so we never get two daemons fighting over the port.
echo "==> Stopping any running Acher daemon"
acher uninstall >/dev/null 2>&1 || true
pkill -f "acher.cli start" 2>/dev/null || true
pkill -f "acher start" 2>/dev/null || true
sleep 1

echo "==> Registering auto-start at login"
acher install

# --- 5. Wait for it to come up, then open the GUI ---
echo -n "==> Waiting for Acher to start"
for _ in $(seq 1 40); do
  if curl -sf "${URL}/api/health" >/dev/null 2>&1; then break; fi
  echo -n "."; sleep 0.25
done
echo

# Fallback: if launchd didn't bring it up, start a detached daemon for now.
if ! curl -sf "${URL}/api/health" >/dev/null 2>&1; then
  echo "==> launchd didn't start it; starting in the background"
  nohup acher start >/dev/null 2>&1 &
  for _ in $(seq 1 40); do
    if curl -sf "${URL}/api/health" >/dev/null 2>&1; then break; fi
    echo -n "."; sleep 0.25
  done
  echo
fi

if curl -sf "${URL}/api/health" >/dev/null 2>&1; then
  echo "==> Acher is running at ${URL}"
  if command -v open >/dev/null 2>&1; then open "${URL}"          # macOS
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "${URL}" # Linux
  fi
else
  echo "!!  Acher did not respond yet. Check the log:"
  echo "    ~/Library/Application Support/Acher/acher.log"
fi

echo
echo "Done. Acher will now start automatically at login."
echo "  • Open the GUI:     ${URL}"
echo "  • Stop auto-start:  acher uninstall"
echo "  • macOS: grant Screen Recording (+ Accessibility for the hotkey) — see docs/permissions-setup.md"
