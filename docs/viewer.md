English | [简体中文](viewer.zh-CN.md)

# Local Graph Viewer

`graph-wiki serve` starts a read-only HTTP server for browsing a vault as a graph in your browser.
It is a display layer: the page fetches the vault index, draws a force-directed graph, and shows a
page's summary, tags, links, and raw Markdown when you click a node. It never edits the vault.

The viewer is for humans. For AI retrieval, keep using the existing
[`zvec` pack index and CLI](#ai-retrieval-is-still-zvec-and-the-cli); the viewer does not add a
second search engine.

## Quick start

```bash
graph-wiki serve --vault ~/brain
```

```text
graph-wiki viewer: http://127.0.0.1:8765/
vault: /home/you/brain
Ctrl-C to stop
```

Open the URL, or pass `--open` to launch the default browser.

| Option | Default | What it does |
|---|---|---|
| `--vault PATH` | resolved config | Override `OBSIDIAN_VAULT_PATH`; `@name` selectors work |
| `--host HOST` | `127.0.0.1` | Bind address; `0.0.0.0` exposes the vault to your network |
| `--port PORT` | `8765` | Bind port; `0` chooses a free port |
| `--open` | off | Open the viewer in the default browser |
| `--verbose` | off | Log every HTTP request |

The server binds to loopback by default and has no authentication. If you explicitly bind a
non-loopback address, anyone who can reach that address can read the vault.

## What the page shows

- **Graph.** Nodes are sized by unique-neighbour degree and coloured by category. Typed
  relationships use their own colours and an arrow; plain wikilinks stay grey. Relation labels can
  be toggled.
- **Narrowing.** Search title, slug, category, tags, summary, and path; filter by category or tag;
  hide untyped links with **Typed only**. The header reports how many pages and links are visible.
- **Detail sidebar.** Click a node to see its category, tags, summary, incoming and outgoing
  relationships, and a raw Markdown preview. Actions open the page in Obsidian, focus the node,
  copy a deep link, or copy the page API URL.
- **Deep links.** `http://127.0.0.1:8765/?node=concepts/transformers` selects a page after the graph
  loads. The URL updates as you select nodes.
- **Refresh.** **Refresh** re-checks the vault. The server caches the payload by a
  `(path, mtime_ns, size)` fingerprint for one second, so unchanged files are not parsed again.

The page is deliberately not an editor. It does not render Markdown HTML, write files, or expose a
directory listing.

## Endpoints

The browser page needs only these routes:

| Route | Purpose |
|---|---|
| `GET /` | HTML shell and static assets |
| `GET /api/graph` | Graph payload consumed by the page: nodes, edges, stats, vault fingerprint |
| `GET /api/page?id=<page-id>` | Page frontmatter, raw Markdown body, and Obsidian URI |

`/api/page` accepts `max_bytes` for a bounded preview. `GET /api/graph` and `GET /api/page` support
`ETag` / `If-None-Match`.

Node ids are vault-relative paths without `.md` (`concepts/transformers`). Each node keeps the
wikilink `slug` as an alias. If two files share a slug, the viewer picks the target in the source
page's category (then the lexicographically first id) and marks the edge `ambiguous: true`.

The graph payload is schema-versioned:

```json
{
  "schema_version": 1,
  "generated_at": "2026-01-01T00:00:00+00:00",
  "vault": {
    "name": "brain",
    "path": "/home/you/brain",
    "fingerprint": "…"
  },
  "stats": {
    "pages": 42,
    "edges": 87,
    "typed_edges": 19,
    "untyped_edges": 68,
    "density": 0.0505,
    "categories": {"concepts": 20, "entities": 10},
    "tags": {"ml": 12},
    "isolated": []
  },
  "nodes": [
    {
      "id": "concepts/transformers",
      "slug": "transformers",
      "label": "Transformer Architecture",
      "title": "Transformer Architecture",
      "category": "concepts",
      "tags": ["ml", "architecture"],
      "summary": "The attention-based architecture introduced in Attention Is All You Need.",
      "path": "concepts/transformers.md",
      "tier": "core",
      "lifecycle": "active",
      "operational_state": "",
      "degree": 12,
      "in_degree": 5,
      "out_degree": 7
    }
  ],
  "edges": [
    {
      "id": "concepts/transformers|entities/vaswani|implements",
      "source": "concepts/transformers",
      "target": "entities/vaswani",
      "relation": "implements",
      "kind": "relationship",
      "typed": true,
      "weight": 1,
      "representations": ["relationships"],
      "ambiguous": false
    }
  ]
}
```

Edges are deduplicated by the framework's Edge Identity: `(source, target, relation)`. Repeated
plain links to the same target become one untyped edge with a higher `weight`.

## AI retrieval is still zvec and the CLI

The viewer is not a replacement for the retrieval stack:

- `zvec` is an optional BM25 + Jieba full-text index over immutable pack chunks. It answers
  "which chunks match this query" and has no graph edges.
- `graph-wiki context-pack` compiles a bounded, cited context slice.
- `graph-wiki graph-query` returns structural candidates, paths, and `should_read`.
- `graph-wiki graph-analyse` reports hubs, communities, and surprising connections.

If an agent can run the CLI, use those commands. The viewer's JSON is primarily the page's own
backend; it is not a stable AI retrieval contract. This keeps one search engine (zvec / the pack
index) instead of adding a second one.

## Read-only and security

- Only `GET` and `HEAD` are accepted; there is no write route.
- The vault is read in memory; the viewer does not create `.obsidian/frontmatter-index.json`.
- The default bind is loopback. The `Host` header is checked against the bound loopback host to
  reduce DNS-rebinding risk.
- Static routes are a whitelist. The page endpoint resolves ids to indexed paths and rejects
  anything outside the vault.
- Responses use a strict `script-src 'self'` Content-Security-Policy. The viewer ships its graph
  library locally, so it works offline and makes no external requests.

## Relationship to `wiki-export`

`wiki-export` writes static artifacts (`graph.json`, `graph.html`, GraphML, Cypher, OKF) for sharing
or external tools. `graph-wiki serve` is live and read-only: nothing is written, and the page
reflects vault edits when it refreshes. Use the exporter when you need a file to hand to someone
else; use the viewer when you want to browse.

## Troubleshooting

- **Port already in use.** Run `graph-wiki serve --port 0`; the printed URL contains the chosen port.
- **Empty graph.** Confirm the vault has Markdown pages outside system areas such as `_raw/`,
  `_archives/`, and `_readouts/`. Visit `/api/graph` to inspect the payload.
- **A page is missing.** The viewer excludes bookkeeping files (`index.md`, `log.md`, `hot.md`,
  `_insights.md`, and agent bootstrap files) wherever they appear, plus the root `README.md`.
- **Open in Obsidian does nothing.** Obsidian must be installed and registered for `obsidian://`
  links. The button uses the absolute vault path.
- **Large vault is slow to settle.** The initial force layout runs once, then physics is disabled.
  Use search or filters to narrow the graph, and Refresh only when you need it.
