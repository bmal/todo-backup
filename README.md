# todo-backup

Python CLI that mirrors Microsoft To Do to local lossless JSON snapshots and derived Markdown.

## Installation

```sh
python3.13 -m venv .venv
.venv/bin/pip install -e .
source .venv/bin/activate
```

The `source` step puts `todo-backup` on your `PATH` for the current shell session. Re-run it in each new terminal, or add it to your shell profile.

## Configuration

By default, `todo-backup` reads config from `~/.config/todo-backup/config.json`:

```json
{
  "clientId": "your-application-client-id",
  "outputDir": "~/todo-backup-output",
  "tokenCachePath": "~/.local/share/todo-backup/msal_token_cache.json"
}
```

`outputDir` is optional and defaults to `~/todo-backup-output`, intentionally outside an Obsidian vault.
`tokenCachePath` is optional and defaults to `$XDG_DATA_HOME/todo-backup/msal_token_cache.json`, or `~/.local/share/todo-backup/msal_token_cache.json` when `XDG_DATA_HOME` is unset. The token cache is written outside this repository with user-only file permissions and should not be committed.

## Authentication

Run device-code login once before pulling data:

```sh
todo-backup --config ~/.config/todo-backup/config.json init-auth
```

The command requests Microsoft Graph delegated `Tasks.Read` and `offline_access` scopes. Later `pull` and `sync` commands acquire and refresh tokens silently from the cache. If Microsoft no longer accepts the cached refresh token, the command fails clearly and asks you to run `init-auth` again rather than using stale credentials.

To manually confirm silent acquisition after first login, run `init-auth`, then run `todo-backup --config ~/.config/todo-backup/config.json pull` twice. The `pull` commands should not print a device-code prompt.

## Usage

```sh
todo-backup --config ~/.config/todo-backup/config.json pull
todo-backup --config ~/.config/todo-backup/config.json sync
todo-backup --config ~/.config/todo-backup/config.json status
```

`pull` performs the initial export and checkpoints progress so rerunning it resumes interrupted work. `sync` uses stored Graph delta links for lazy incremental refreshes. `status` reads local `state.json` and snapshots, then prints each list's last sync time plus open/completed counts.

## Weekly Scheduling

Scheduling is not built into `todo-backup`; run the idempotent `sync` command from your scheduler of choice.

For `launchd` on macOS, save a plist like this as `~/Library/LaunchAgents/com.example.todo-backup.plist` and load it with `launchctl load ~/Library/LaunchAgents/com.example.todo-backup.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.example.todo-backup</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/you/Documents/todo-backup/.venv/bin/todo-backup</string>
    <string>--config</string>
    <string>/Users/you/.config/todo-backup/config.json</string>
    <string>sync</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>1</integer>
    <key>Hour</key>
    <integer>8</integer>
    <key>Minute</key>
    <integer>30</integer>
  </dict>
</dict>
</plist>
```

For cron, run `crontab -e` and add a weekly entry:

```cron
30 8 * * 1 /Users/you/Documents/todo-backup/.venv/bin/todo-backup --config /Users/you/.config/todo-backup/config.json sync
```
