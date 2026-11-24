# Graph Wiki

The project compiles source material into a persistent, interconnected knowledge graph represented as Obsidian-compatible Markdown.

## Language

**Typed Relationship**:
A directional semantic assertion from one source page to one target page using a declared relationship type.
_Avoid_: Typed link, semantic link

**Edge Identity**:
The unique `(source page, target page, relationship type)` identity of a Typed Relationship, independent of how it is represented in Markdown or YAML.
_Avoid_: Link identity

**Relationship Projection**:
A persisted expression of an Edge Identity in one of the vault's supported authoring or metadata forms.
_Avoid_: Relationship format, duplicate edge

**Relationship Vocabulary**:
The effective allowlist of relationship types for a vault, consisting of the framework vocabulary plus owner-declared extensions.
_Avoid_: Link types

**Graph Viewer**:
The read-only local browser surface that renders the vault graph and serves page details. It is a display layer, not a retrieval engine.
_Avoid_: Dashboard, Web UI, AI API

**Viewer Page Backend**:
The read-only `/api/graph` and `/api/page` routes the Graph Viewer's browser page fetches. It is not a public AI retrieval contract.
_Avoid_: AI API, search API

**Knowledge Pack**:
A bundled, versioned knowledge-domain contract that combines one Knowledge Profile with one Vault Layout and their supporting schema and routing guidance. Packs are public product resources, independent of any workflow that consumes them.
_Avoid_: Layout, Domain

**Content Pack**:
An immutable, content-addressed release derived from one committed vault state: manifest, inventory, typed edges, and a body CAS. Identified by `pack_id`; retrieval indexes are rebuildable sidecars.
_Avoid_: Knowledge Pack, snapshot, bundle

**Retrieval Index**:
A rebuildable, engine-specific sidecar over a Content Pack, identified by `index_id` and bound to its `content_pack_id`.
_Avoid_: index cache, vector store

**Knowledge Profile**:
The semantic contract for a vault: its purpose, scope, knowledge types, extraction policy, evidence requirements, freshness triggers, and retrieval priorities.
_Avoid_: Domain detector, Named Vault Profile, Writing Profile

**Vault Layout**:
The materialization contract that maps declared page types to paths and defines live content roots, system areas, and naming placeholders.
_Avoid_: Knowledge Profile, Folder structure

**Source File**:
A user-owned physical text file that supplies provenance and is deterministically normalized into one or more Ingest Documents.
_Avoid_: Document, Unit

**Ingest Document**:
A bounded, independently processable text input handled in one fresh model session. A small Source File produces one Ingest Document and a large Source File produces multiple Ingest Documents; this boundary never implies a Wiki page boundary.
_Avoid_: Unit, Packet, Chunk page, Virtual page
