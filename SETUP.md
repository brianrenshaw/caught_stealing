# Setup Guide — New Machine

How to bring a new Mac online for the Lankford Legends fantasy baseball app. Covers the minimum dev setup, the full pipeline machine setup (launchd + MacWhisper), and the transition plan when migrating the always-on workload from one Mac to another.

## 1. Clone and install dependencies

```bash
# Install uv if missing (https://docs.astral.sh/uv/)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone
git clone https://github.com/brianrenshaw/caught_stealing.git fantasy_baseball_br
cd fantasy_baseball_br

# Sync deps (needs Python 3.11+, uv reads pyproject.toml)
uv sync

# Sanity check
uv run ruff check .
uv run pytest
```

## 2. Copy secrets and state from the old machine

These are gitignored on purpose — copy them via AirDrop, scp, or a private cloud folder.

| File / path | Purpose | Required for |
|---|---|---|
| `.env` | Yahoo + Anthropic keys, league ID, `AUTH_PASSWORD`, Fly.io token JSON | Everything |
| `CLAUDE.md` | Project instructions for Claude Code (gitignored globally) | Claude Code sessions |
| `fantasy_baseball.db` | All historical synced data | Skipping a fresh ETL re-run |
| `yahoo_token.json` (or wherever yfpy stored it) | OAuth token | Avoiding browser OAuth on first run |
| `data/content/manifest.json` | Index of already-ingested blogs/podcasts | Avoiding re-downloading content |
| `data/content/analysis/` | Past daily/weekly reports | Optional — historical reference |

Alternatively, run `uv run python -m app.etl.pipeline` to repopulate the DB from scratch. Yahoo OAuth will trigger a browser prompt on first call if no token is present.

## 3. Run the dev server

```bash
uv run uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000 and log in with `AUTH_PASSWORD`.

## 4. Install flyctl (optional — for manual Fly.io deploys)

GitHub Actions auto-deploys on push to `main` (see [.github/workflows/fly-deploy.yml](.github/workflows/fly-deploy.yml)), so manual deploys are rarely needed. To do them anyway:

```bash
brew install flyctl
flyctl auth login
flyctl status --app fantasy-baseball-br
```

`flyctl` is also required by [scripts/daily_content_ingest.sh](scripts/daily_content_ingest.sh) to upload daily reports to the Fly volume — install it if this machine will run the daily pipeline.

---

# Pipeline machine setup (always-on Mac)

The "pipeline machine" is the Mac that runs the daily content ingest, podcast transcription, and Claude analysis. Only one Mac should do this at a time (see transition plan below).

## 5. MacWhisper

1. Install MacWhisper from the Mac App Store or https://goodsnooze.gumroad.com/l/macwhisper
2. Open MacWhisper → Preferences → Watch Folders. Configure:
   - **Watch folder:** `~/Projects/fantasy_baseball_br/data/content/audio/pending/`
   - **Output folder:** `~/Projects/fantasy_baseball_br/data/content/audio/transcribed/`
   - **Output format:** `.txt`
3. Pick a transcription model (Large v3 is what the old machine uses; reduce if RAM-limited).
4. Make sure MacWhisper launches at login (System Settings → General → Login Items).

The downloader script ([scripts/podcast_transcriber.py](scripts/podcast_transcriber.py)) drops `.mp3` files plus a `.json` sidecar into `pending/`. MacWhisper picks them up and writes `.txt` to `transcribed/`. The collector script ([scripts/transcript_collector.py](scripts/transcript_collector.py)) then formats them into markdown with frontmatter.

## 6. launchd agents

Two agents run on the pipeline machine. Both expect paths under your home directory — replace `<USERNAME>` below with the new Mac's short username (`whoami`).

### `~/Library/LaunchAgents/com.fantasybaseball.content-ingest.plist`

Runs the full daily pipeline at 3 AM (blog fetch → podcast download → transcript collect → Yahoo sync → analysis → upload to Fly).

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.fantasybaseball.content-ingest</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/<USERNAME>/Projects/fantasy_baseball_br/scripts/daily_content_ingest.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>3</integer>
        <key>Minute</key><integer>0</integer>
    </dict>
    <key>Nice</key><integer>0</integer>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/Users/<USERNAME>/.local/bin</string>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/<USERNAME>/Projects/fantasy_baseball_br/data/content/logs/launchd_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/<USERNAME>/Projects/fantasy_baseball_br/data/content/logs/launchd_stderr.log</string>
</dict>
</plist>
```

### `~/Library/LaunchAgents/com.fantasybaseball.transcript-watcher.plist`

A long-running process that watches `transcribed/` and formats new `.txt` files as MacWhisper finishes them. Restarts if it crashes.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.fantasybaseball.transcript-watcher</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/<USERNAME>/.local/bin/uv</string>
        <string>run</string>
        <string>--project</string>
        <string>/Users/<USERNAME>/Projects/fantasy_baseball_br</string>
        <string>python</string>
        <string>-m</string>
        <string>scripts.transcript_collector</string>
        <string>--watch</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/<USERNAME>/Projects/fantasy_baseball_br</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/Users/<USERNAME>/.local/bin</string>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/<USERNAME>/Projects/fantasy_baseball_br/data/content/logs/watcher_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/<USERNAME>/Projects/fantasy_baseball_br/data/content/logs/watcher_stderr.log</string>
</dict>
</plist>
```

### Load the agents

```bash
mkdir -p ~/Projects/fantasy_baseball_br/data/content/logs

launchctl load ~/Library/LaunchAgents/com.fantasybaseball.content-ingest.plist
launchctl load ~/Library/LaunchAgents/com.fantasybaseball.transcript-watcher.plist

# Verify
launchctl list | grep fantasybaseball

# Trigger the daily ingest manually to test
launchctl start com.fantasybaseball.content-ingest
tail -f ~/Projects/fantasy_baseball_br/data/content/logs/ingest_$(date +%Y-%m-%d).log
```

To unload:
```bash
launchctl unload ~/Library/LaunchAgents/com.fantasybaseball.content-ingest.plist
launchctl unload ~/Library/LaunchAgents/com.fantasybaseball.transcript-watcher.plist
```

## 7. macOS settings

- **Energy / Sleep:** System Settings → Battery (or Energy Saver) → "Prevent automatic sleeping when display is off." launchd will wake the Mac for the 3 AM job if it's asleep, but the pipeline takes ~30 min and works better awake.
- **Full Disk Access:** May be required for `flyctl ssh sftp` and for MacWhisper to write into the project directory. Grant via System Settings → Privacy & Security → Full Disk Access.
- **Login items:** MacWhisper.

---

# Transition plan (old machine → new machine)

The pipeline doesn't tolerate two machines running it simultaneously well — you'd get duplicate Claude API spend, duplicate PDFs uploaded to Fly, and possible Yahoo token-refresh races. Use this sequence:

1. **On the new machine:** complete steps 1–7 above, but **do NOT load the launchd agents yet**. Verify the dev server runs and you can log in.
2. **Run a manual dry test on the new machine** without touching the old machine's schedule:
   ```bash
   uv run python -m scripts.daily_analysis --dry-run
   ./scripts/daily_content_ingest.sh    # full run, will upload to Fly
   ```
   Confirm content appears in `data/content/analysis/` and the Fly app picks up the upload.
3. **Cut over.** On a single morning:
   - Old machine: `launchctl unload` both plists.
   - New machine: `launchctl load` both plists.
   - Verify next morning's 3 AM run succeeded by checking `data/content/logs/`.
4. **(Optional) Keep the old machine as warm backup** for a week — code stays clone-able from GitHub, secrets stay in `.env`, but the launchd agents stay unloaded.

### If you must run both machines temporarily

- The podcast downloader skips files already in `pending/` or `transcribed/` based on filename, so duplicate runs are mostly harmless for that step.
- The daily Claude analysis is **not** idempotent — it will spend API tokens twice and upload two report copies to Fly with the same date prefix (the second `put` overwrites the first). Avoid running both.
- Easiest way to run both safely for a day: leave MacWhisper + the watcher loaded on both, but **only load the `content-ingest` plist on one machine**.

---

# Troubleshooting

- **Yahoo OAuth fails on first call:** delete the local token file and re-run; a browser window will open. On a headless box, run `uv run python -m scripts.capture_yahoo_token` and paste the JSON into `.env` as `YAHOO_ACCESS_TOKEN_JSON`.
- **launchd job didn't fire:** check `~/Library/LaunchAgents/.../launchd_stderr.log`. Common cause is `PATH` missing `/opt/homebrew/bin` so `uv` isn't found.
- **`flyctl ssh sftp` hangs in the daily script:** Fly's SSH can need a fresh `flyctl auth login` after long idle periods.
- **MacWhisper not picking up files:** check the Watch Folders pref points exactly at `data/content/audio/pending/` and that the folder exists.
