# Google Drive Sync — Setup (Phase 3)

Drive sync is **optional**. Acher works fully offline without it; turning it on
uploads each screenshot to your own Google Drive in the background, with retry
and offline buffering.

## 1. Install the optional dependencies

```bash
pip install -e ".[drive]"
```

This pulls in `google-api-python-client`, `google-auth`, and
`google-auth-oauthlib`. If they're missing, Acher still runs — it just refuses
Drive operations with a clear message.

## 2. Create a Google Cloud OAuth client

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and
   create (or pick) a project.
2. **APIs & Services → Library →** enable the **Google Drive API**.
3. **APIs & Services → OAuth consent screen:**
   - User type **External** is fine for personal use.
   - Add your own Google account under **Test users** (required while the app
     is in "testing" — otherwise consent is blocked).
4. **APIs & Services → Credentials → Create credentials → OAuth client ID:**
   - Application type: **Desktop app**.
   - Copy the **Client ID** and **Client secret**.

## 3. Put the credentials in `.env`

Copy `.env.example` to `.env` and fill in:

```
GOOGLE_OAUTH_CLIENT_ID=<your client id>
GOOGLE_OAUTH_CLIENT_SECRET=<your client secret>
```

`.env` is git-ignored — never commit it. The OAuth token Acher caches after
login lives in the app-data dir (`acher paths` → `app_data_dir`/`token.json`),
also outside the repo.

## 4. Authorize

```bash
acher auth
```

This opens a browser for consent (scope: `drive.file` — Acher only ever sees
files it creates). On success it caches the token and flips `drive_connected`
to `true` in `config.json`.

## 5. Run

```bash
acher start
```

The daemon now runs an uploader thread alongside capture. Each screenshot is
enqueued and uploaded into **`Acher Screenshots/YYYY-MM/`** in your Drive.

## How it behaves

- **Offline / errors:** uploads that fail stay queued and retry with exponential
  backoff (5s, 10s, 20s … capped at 5 min). Reconnecting drains the backlog.
- **Give-up:** after 10 failed attempts a screenshot is marked `failed` and left
  alone (a manual retry path comes with the Settings UI in a later phase).
- **Local-first:** the PNG and DB row are written first; upload is always a
  follow-on. Disabling Drive never affects capture.

## Verifying the stop condition

1. `acher auth`, then `acher start`. Confirm new screenshots appear in Drive
   under `Acher Screenshots/<this month>/`.
2. Turn off Wi-Fi. Let a few captures happen — they stay local, and
   `upload_queue` accumulates `pending` rows (each retry bumps `attempts`).
3. Turn Wi-Fi back on. Within one poll cycle the backlog uploads and the queue
   drains; the rows' `upload_status` flips to `uploaded`.
