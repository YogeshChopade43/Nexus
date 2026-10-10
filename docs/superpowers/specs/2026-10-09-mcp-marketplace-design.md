# MCP Marketplace — design

Status: approved in conversation 2026-10-09; awaiting spec review.

## Goal

Replace the **MCP Servers** page with a **Marketplace**. It shows the servers listed in the official MCP Registry (registry.modelcontextprotocol.io). You can search them, open one, fill in only the settings it needs, and install it with one click. Installed servers are managed from the same page.

**Success means:**
- Finding a server takes seconds and works offline after the first sync.
- Installing a listed server never requires typing a command or JSON by hand.
- Every management feature the current page has still exists.

## Decisions

| Decision | Choice |
|---|---|
| Listing source | The official MCP Registry API only. There is no hand-curated list, and the 11-entry `CATALOG` is deleted. |
| Page | `/servers` stays the address, and its sidebar label becomes **Marketplace**. Browsing and managing installed servers happen on one page. |
| Registry access | A local copy in SQLite, synced in the background. Search runs against the copy, never against the live registry. |
| Installable kinds | Hosted (streamable HTTP), npm via `npx`, PyPI via `uvx`. Docker/OCI, NuGet, MCPB and SSE-only remotes are hidden, because Nexus can't run them. |
| Advanced paths | "Add custom server" and "Import config file" remain as secondary buttons. |

## Registry facts this relies on (checked 2026-10-09)

- **Listing endpoint:** `GET /v0/servers?version=latest&limit=100&cursor=…&updated_since=…` returns `{servers: [{server, _meta}], metadata: {nextCursor, count}}`.
- **`server` fields:** `name` (reverse-DNS, such as `io.github.org/x`), `title?`, `description`, `version`, `icons?`, `repository?`, `websiteUrl?`, `remotes?`, `packages?`.
- **`remotes[]`:** `{type: "streamable-http" | "sse", url, headers?: [{name, value, description, isRequired, isSecret}]}`. A `value` can contain `{placeholder}`.
- **`packages[]`:**
  - `{registryType: "npm" | "pypi" | "oci" | …, identifier, version, runtimeHint?, transport: {type}, runtimeArguments?, packageArguments?, environmentVariables?}`.
  - Each variable or argument has `name`, `description`, `isRequired`, `isSecret`, `default` and `value`, and the `value` can contain placeholders.
  - Arguments are `positional` or `named`.
- **Latency:** responses took 10–40 s and sometimes timed out.
- **Search:** `search=` matches names only.
- **Icons:** about 16% of listings have one.

## 1. Backend

### Storage (migration 9)
```sql
CREATE TABLE registry_servers (
  name TEXT PRIMARY KEY, title TEXT, description TEXT NOT NULL DEFAULT '', version TEXT,
  icon_url TEXT, repository_url TEXT, website_url TEXT,
  install_json TEXT,           -- the chosen install recipe (below); NULL = not installable, hidden
  kind TEXT,                   -- 'hosted' | 'local' | NULL
  updated_at TEXT              -- from _meta updatedAt
);
CREATE VIRTUAL TABLE registry_fts USING fts5(name, title, description, tokenize = 'porter unicode61');
CREATE TABLE registry_sync (id INTEGER PRIMARY KEY CHECK (id = 1), last_synced_at TEXT, status TEXT, error TEXT, count INTEGER);
```
- **Installed-server link:** `mcp_servers` gains a `registry_name TEXT` column. It is added in `store.init_table`, following that file's existing `ALTER TABLE` pattern.

### Sync (`app/mcp/registry.py`)
- **Base URL:** `NEXUS_REGISTRY_URL`, defaulting to the official registry, so tests can point at a fake.
- **Full sync:** pages `version=latest&limit=100` until `nextCursor` is empty.
- **Incremental sync:** the same request with `updated_since=<last_synced_at>`.
- **Writes:**
  - Each page is upserted, replacing the row and its search entry.
  - `isLatest: false` entries are ignored.
  - Listings with status `deleted` are removed.
- **Network:**
  - One request at a time, with a 60 s timeout.
  - Up to 3 retries per page with backoff (5 s, 20 s, 60 s).
  - A failed sync keeps the data already stored and records the error.
- **When it runs:**
  - At startup, if no sync has happened in the last 24 h.
  - Every 24 h while running, using the existing scheduler.
  - On demand from `POST /api/marketplace/refresh`. A second request while one is running is ignored.
- **Startup:** never blocked. The page shows "Syncing… N servers".

### Install recipe (`plan(server) -> Recipe | None`)
1. **Hosted:** the first `remotes[]` entry of type `streamable-http` gives `{transport: "http", url, headers}`.
2. **npm:** otherwise, the first npm package (stdio) gives `npx -y <identifier>@<version>`, plus the runtime and package arguments.
3. **PyPI:** otherwise, the first PyPI package (stdio) gives `uvx <identifier>==<version>`, plus the arguments.
4. **Anything else:** `None`, so the listing is hidden.

**Form fields** come from three places:
- each distinct `{placeholder}` in the URL, header values or argument values;
- each environment variable;
- each required argument that has no fixed value.

Every field is `{key, label, description, required, secret, default}`, and the recipe stores templates that refer to these keys. Optional environment variables without a value are left out of the installed server's config.

### API (`/api/marketplace`)
| Endpoint | Purpose |
|---|---|
| `GET /?q=&kind=hosted\|local\|installed&sort=relevance\|updated&offset=&limit=` | Listing cards: name, title, description, publisher (from `name`), kind, icon, `installed_server_id`, and `requires`: `node`, `uv` or none. |
| `GET /{name:path}` | Full listing: recipe fields, links, whether its runtime is available (via `shutil.which("npx"/"uvx")`), and the installed server if any. |
| `POST /install` `{name, values}` | Checks required fields, fills the templates, then creates and starts the server through the existing `store.create_server` and manager start path, saving `registry_name`. Returns the server view. A hosted server that needs sign-in uses the existing OAuth flow. |
| `POST /refresh`, `GET /status` | Starts a sync; reports sync state, count and last sync time. |

**Installed matching:**
- Primarily by `registry_name`.
- For servers created before this feature, by the same URL (hosted) or the same package identifier in `args` (local).

## 2. Frontend

**Sidebar and address:** `/servers` stays, so bell links keep working. The label becomes **Marketplace**. `ServersPage.tsx` is replaced by `MarketplacePage.tsx` and helpers in `components/marketplace/`.

**Header:**
- search box, debounced;
- filters: All, Hosted, Runs on this computer, Installed;
- sort: Best match or Recently updated;
- buttons: Add custom server, Import config, Refresh;
- sync status line.

**Grid of cards:**
- icon, or the first letter of the title;
- title, publisher and a two-line description;
- a Hosted or Local tag;
- an **Installed** badge with a status dot;
- a "Needs Node.js" or "Needs uv" warning;
- "Load more" paging.

**Detail panel**, opened by clicking a card:
- **Not installed:** description, repository and website links, a generated form (secret fields masked, defaults pre-filled, required fields marked) and **Install**. Install is disabled when the runtime is missing and explains why.
- **Installed:** the current controls, moved over unchanged:
  - status and tools with their Allow/Ask/Block policies;
  - logs, restart, sign in/out, edit settings and remove.

**Deleted and kept:** `CATALOG` is removed from `catalog.ts`, and `parseMcpConfig` stays. Custom add and edit reuse the existing form modal.

**Mobile and accessibility:**
- Single-column cards on phones; the panel opens full-screen.
- Every control has an accessible name, as the existing Playwright check requires.

## 3. Testing

**Backend:** a fake registry, either an HTTP fixture or a mocked transport.
- A full sync over two pages.
- An incremental sync using `updated_since`, including a deleted listing.
- A failed page keeps the old data and records the error.
- Search matches descriptions, and filters work.
- Install recipes cover:
  - a hosted server with a `{api_key}` header;
  - npm with environment variables and arguments;
  - PyPI;
  - Docker only, which must be hidden;
  - SSE only, which must be hidden.
- Install creates and starts a server with the filled values and `registry_name`, and rejects a missing required value.
- Existing installed servers are matched by URL or package.

**Frontend (vitest):**
- Search and filters.
- The generated form, including masked secret fields.
- The panel for an installed versus an uninstalled server.
- Install disabled when the runtime is missing.

**End to end (Playwright):** the smoke journey installs a server from a fake registry, using the existing echo fixture server, and sees it marked Installed.

## Out of scope
- Installing Docker/OCI servers.
- Ratings and reviews.
- "Update available" notices for installed servers.
- Publishing to the registry.
- A curated "Featured" list.
