"use strict";

const { Plugin, requestUrl } = require("obsidian");

/**
 * Graph Wiki Operations
 *
 * Sends one view event per opened Markdown note to the local Graph Wiki
 * viewer.  Recording is opt-in: the viewer must be started with --ops, and
 * this plugin must be installed with `graph-wiki ops install-obsidian`.
 *
 * Privacy: only the vault-relative note path, a random client id, and the
 * timestamp leave the plugin.  No note body, search query, IP, or user agent
 * is sent.  Tokens and settings are read from data.json in this plugin folder.
 */
module.exports = class GraphWikiOpsPlugin extends Plugin {
  async onload() {
    const settings = (await this.loadData()) || {};
    const port = Number(settings.port) || 8765;
    const token = String(settings.token || "");
    const clientId = String(settings.clientId || "obsidian-unknown");
    if (!token) return;

    const endpoint = `http://127.0.0.1:${port}/api/ops/event`;
    const lastSent = new Map();

    const send = (file) => {
      if (!file || file.extension !== "md") return;
      const page = file.path.replace(/\.md$/, "");
      if (!page) return;
      const now = Date.now();
      const previous = lastSent.get(page) || 0;
      // The server also deduplicates a 30-minute window; this keeps rapid
      // leaf changes from producing unnecessary requests.
      if (now - previous < 5000) return;
      lastSent.set(page, now);
      requestUrl({
        url: endpoint,
        method: "POST",
        contentType: "application/json",
        headers: {
          "Content-Type": "application/json",
          "X-Graph-Wiki-Ops-Token": token,
        },
        body: JSON.stringify({
          event: "view",
          page,
          source: "obsidian",
          client: clientId,
          ts: new Date().toISOString(),
        }),
        throw: false,
      }).catch(() => {});
    };

    // Register after the workspace has restored its layout, otherwise every
    // restored leaf would look like a fresh human open on startup.
    this.app.workspace.onLayoutReady(() => {
      this.registerEvent(this.app.workspace.on("file-open", send));
    });
  }
};
