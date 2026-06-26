# todo-backup

Python CLI that mirrors Microsoft To Do to local lossless JSON snapshots and derived Markdown.

## Configuration

By default, `todo-backup` reads config from `~/.config/todo-backup/config.json`:

```json
{
  "clientId": "your-application-client-id",
  "outputDir": "~/todo-backup-output"
}
```

`outputDir` is optional and defaults to `~/todo-backup-output`, intentionally outside an Obsidian vault.

## Usage

```sh
todo-backup --config ~/.config/todo-backup/config.json pull
```
