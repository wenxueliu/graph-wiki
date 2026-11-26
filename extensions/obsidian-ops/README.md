# Graph Wiki Operations (Obsidian plugin)

Records note opens from Obsidian into the local Graph Wiki operations store.
Recording is opt-in and stays on this machine. The plugin is desktop-only: mobile
Obsidian cannot reach a viewer running on the desktop.

## Why

The Graph Viewer can only see pages opened through its own `/api/page` route.
Obsidian opens bypass that route entirely, so this plugin is the only supported
way to count Obsidian views.

## Install

1. Build or use an installation that ships `graph-wiki`.
2. Start the viewer with operations enabled and a fixed port:

   ```bash
   graph-wiki serve --ops --port 8765
   ```

3. Install the plugin into the vault:

   ```bash
   graph-wiki ops install-obsidian ~/brain --port 8765
   ```

   This copies `manifest.json`, `main.js`, and `data.json` into
   `<vault>/.obsidian/plugins/graph-wiki-ops/`. `data.json` carries the local
   ops token from `~/.graph-wiki/state/<vault-id>/ops/token`.

4. In Obsidian: **Settings → Community plugins → Graph Wiki Operations →
   Enable**. If community plugins are restricted, enable restricted mode off
   for this vault first.

5. Open a few notes, then check the event log:

   ```bash
   graph-wiki ops events ~/brain --limit 5
   ```

## Privacy

The plugin sends only `event`, vault-relative `page`, `source=obsidian`,
a random `client` id, and the timestamp. It never reads note bodies, search
queries, or other editor state. Requests go to `127.0.0.1` only.

## Dedupe

The plugin skips repeated opens of the same note within 5 seconds, and the
server applies a 30-minute dedupe window per page and client when building
reports. Adjust the report window with
`graph-wiki ops report --dedupe-minutes ...`.
