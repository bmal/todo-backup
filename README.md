# todo-backup

Python CLI that mirrors Microsoft To Do to local lossless JSON snapshots and derived Markdown.

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
```
