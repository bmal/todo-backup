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
  "authority": "https://login.microsoftonline.com/consumers",
  "outputDir": "~/todo-backup-output",
  "tokenCachePath": "~/.local/share/todo-backup/msal_token_cache.json",
  "listDirectories": {
    "Someday": "On hold",
    "Old tasks": "Archive"
  },
  "requireListDirectories": true
}
```

`authority` is optional and defaults to `https://login.microsoftonline.com/consumers`, which is for personal Microsoft accounts. For an app registered in a work/school tenant, use `https://login.microsoftonline.com/<tenant-id>` instead.
`outputDir` is optional and defaults to `~/todo-backup-output`, intentionally outside an Obsidian vault.
`tokenCachePath` is optional and defaults to `$XDG_DATA_HOME/todo-backup/msal_token_cache.json`, or `~/.local/share/todo-backup/msal_token_cache.json` when `XDG_DATA_HOME` is unset. The token cache is written outside this repository with user-only file permissions and should not be committed.
`listDirectories` is optional. It maps exact Microsoft To Do list names to subdirectories under `lists/`, so a mapping of `"Someday": "On hold"` writes `lists/On hold/Someday.md`. Unmapped lists continue to write directly under `lists/`.
`requireListDirectories` is optional and defaults to `false`. When `true`, `pull`, `sync`, and `render` fail before writing Markdown if any Microsoft To Do list is missing from `listDirectories`.

## Authentication

### Microsoft App Registration

Create or update an app registration in Microsoft Entra / Azure Portal and copy its **Application (client) ID** into `clientId`.

For personal Microsoft To Do accounts, configure the app registration as follows:

- **Supported account types**: choose an option that includes personal Microsoft accounts, such as **Any Entra ID Tenant + Personal Microsoft accounts**.
- **Authentication**: enable **Allow public client flows**.
- **Redirect URI configuration**: add `https://login.microsoftonline.com/common/oauth2/nativeclient` if the portal requires a mobile/desktop redirect URI.
- **API permissions**: add Microsoft Graph delegated `Tasks.Read` and `offline_access`.

If you change an existing single-tenant app to support personal Microsoft accounts and the portal rejects the change, set the manifest's `api.requestedAccessTokenVersion` to `2`, save, then update `signInAudience` to `AzureADandPersonalMicrosoftAccount`.

Run device-code login once before pulling data:

```sh
todo-backup --config ~/.config/todo-backup/config.json init-auth
```

The command requests the Microsoft Graph delegated `Tasks.Read` scope. Add both `Tasks.Read` and `offline_access` to the app registration's delegated Microsoft Graph permissions, but only `Tasks.Read` is passed to MSAL because `offline_access` is a reserved scope there. Later `pull` and `sync` commands acquire and refresh tokens silently from the cache. If Microsoft no longer accepts the cached refresh token, the command fails clearly and asks you to run `init-auth` again rather than using stale credentials.

To manually confirm silent acquisition after first login, run `init-auth`, then run `todo-backup --config ~/.config/todo-backup/config.json pull` twice. The `pull` commands should not print a device-code prompt.

## Usage

```sh
todo-backup --config ~/.config/todo-backup/config.json pull
todo-backup --config ~/.config/todo-backup/config.json repull --yes
todo-backup --config ~/.config/todo-backup/config.json sync
todo-backup --config ~/.config/todo-backup/config.json render
todo-backup --config ~/.config/todo-backup/config.json status
```

`pull` performs the initial export and checkpoints progress so rerunning it resumes interrupted work. `repull --yes` deletes only `outputDir`, keeps the token cache, and performs a fresh pull. `sync` uses stored Graph delta links for lazy incremental refreshes. `render` regenerates Markdown from saved JSON snapshots without contacting Microsoft Graph. `status` reads local `state.json` and snapshots, then prints each list's last sync time plus open/completed counts.

Markdown output emphasizes active work: open tasks appear under `## To do`, completed tasks are kept in a collapsed `Completed` callout, and task/checklist Graph IDs are embedded as HTML comments so future tooling can map Markdown items back to Microsoft To Do objects. The JSON snapshots remain the canonical lossless backup.

The Graph task delta request intentionally uses the plain `/tasks/delta` endpoint and URL-encodes list IDs. Some Microsoft To Do list IDs contain characters such as `/` or `=`, and Microsoft Graph rejects unsupported delta query options such as `$expand=checklistItems`.

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
