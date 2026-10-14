-- Nexus on PostgreSQL: the whole schema of a fresh install, equivalent to SQLite's init_db plus every migration
-- (generated from it; regenerate after adding a migration). Applied once, by init_db, when DATABASE_URL is set.
-- Timestamps stay TEXT and booleans INTEGER, as on SQLite, so the same SQL and values work on both.

-- SQLite behaviour the app's SQL relies on.
CREATE OR REPLACE FUNCTION instr(haystack TEXT, needle TEXT) RETURNS INTEGER
    LANGUAGE sql IMMUTABLE AS 'SELECT strpos(haystack, needle)';

CREATE TABLE activity_log (
    id SERIAL PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    metadata TEXT DEFAULT '{}',
    timestamp TEXT NOT NULL DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    legacy_user TEXT DEFAULT 'user',
    user_id INTEGER);

CREATE TABLE agent_sessions (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE,
    title TEXT,
    messages TEXT DEFAULT '[]',
    metadata TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    updated_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    user_id INTEGER);

CREATE TABLE api_settings (
    id SERIAL PRIMARY KEY,
    settings TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    updated_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS'))
);

CREATE TABLE workspaces (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')),
    user_id INTEGER);

CREATE TABLE collections (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('library', 'chat')),
    session_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE documents (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    mime TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'ready', 'failed')),
    error TEXT,
    progress INTEGER NOT NULL DEFAULT 0,
    pages INTEGER,
    chars INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    embed_model TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (collection_id, content_hash)
);

CREATE TABLE chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    workspace_id INTEGER NOT NULL,
    parent_id INTEGER REFERENCES chunks(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('parent', 'child')),
    position INTEGER NOT NULL,
    text TEXT NOT NULL,
    heading_path TEXT NOT NULL DEFAULT '',
    page_start INTEGER,
    page_end INTEGER,
    char_start INTEGER NOT NULL DEFAULT 0,
    char_end INTEGER NOT NULL DEFAULT 0,
    tokens INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE document_files (
    document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    data BYTEA NOT NULL
);

CREATE TABLE email_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    purpose TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);

CREATE TABLE embedding_cache (
    key TEXT PRIMARY KEY,
    vector BYTEA NOT NULL
);

CREATE TABLE ingestion_jobs (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'retry', 'done', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT,
    progress INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE integrations (
    id SERIAL PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    config TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    user_id INTEGER);

CREATE TABLE llm_providers (
    id SERIAL PRIMARY KEY,
    provider_name TEXT NOT NULL,
    model TEXT NOT NULL,
    api_key TEXT,
    base_url TEXT,
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    updated_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    user_id INTEGER);

CREATE TABLE llm_usage (
    id SERIAL PRIMARY KEY,
    timestamp TEXT NOT NULL,
    provider_id INTEGER,
    provider TEXT,
    model TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated INTEGER NOT NULL DEFAULT 0,
    user_id INTEGER);

CREATE TABLE mcp_servers (
    id SERIAL PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    transport TEXT NOT NULL,
    command TEXT DEFAULT '',
    args TEXT DEFAULT '[]',
    env TEXT DEFAULT '{}',
    url TEXT DEFAULT '',
    headers TEXT DEFAULT '{}',
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    updated_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    tool_policies TEXT DEFAULT '{}', registry_name TEXT DEFAULT '', oauth TEXT DEFAULT '', user_id INTEGER);

CREATE TABLE memories (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual', user_id INTEGER);

CREATE TABLE registry_servers (
    id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, title TEXT, description TEXT NOT NULL DEFAULT '',
    version TEXT, icon_url TEXT, repository_url TEXT, website_url TEXT, install_json TEXT, kind TEXT,
    match_key TEXT, updated_at TEXT, official INTEGER, junk INTEGER
);

CREATE TABLE registry_sync (
    id INTEGER PRIMARY KEY CHECK (id = 1), last_synced_at TEXT, status TEXT, error TEXT, count INTEGER
);

CREATE TABLE retrieval_logs (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL,
    session_id TEXT,
    query TEXT NOT NULL,
    rewritten_query TEXT,
    filters_json TEXT NOT NULL DEFAULT '{}',
    candidates_json TEXT NOT NULL DEFAULT '[]',
    selected_json TEXT NOT NULL DEFAULT '[]',
    latency_ms_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE run_once (
    id SERIAL PRIMARY KEY,
    workflow_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    at TEXT,
    days INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    armed_at TEXT,
    warned_at TEXT,
    reminded_at TEXT,
    ran_at TEXT,
    missed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE workflows (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    steps TEXT DEFAULT '[]',
    enabled INTEGER DEFAULT 1,
    trigger TEXT DEFAULT 'manual',
    last_run TEXT,
    created_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    nodes TEXT NOT NULL DEFAULT '[]', edges TEXT NOT NULL DEFAULT '[]', version INTEGER NOT NULL DEFAULT 1, is_active INTEGER NOT NULL DEFAULT 1, updated_at TEXT, created_by TEXT, schedule TEXT DEFAULT '{}', webhook TEXT DEFAULT '{}', llm_provider_id INTEGER, folder TEXT NOT NULL DEFAULT '', user_id INTEGER);

CREATE TABLE schedules (
    id SERIAL PRIMARY KEY,
    workflow_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    cron_expression TEXT NOT NULL,
    timezone TEXT DEFAULT 'UTC',
    enabled INTEGER DEFAULT 1,
    last_run_at TEXT,
    next_run_at TEXT,
    created_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')), input_data TEXT DEFAULT '{}',
    FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
);

CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    user_agent TEXT NOT NULL DEFAULT ''
);

CREATE TABLE trigger_state (
    workflow_id INTEGER PRIMARY KEY,
    seen TEXT DEFAULT '[]',
    baseline_done INTEGER DEFAULT 0,
    last_checked_at TEXT,
    last_error TEXT, baseline_at TEXT,
    FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
);

CREATE TABLE user_settings (
    id SERIAL PRIMARY KEY,
    settings TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    updated_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    user_id INTEGER);

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    password_hash TEXT,
    email_verified INTEGER NOT NULL DEFAULT 0,
    google_sub TEXT UNIQUE,
    is_admin INTEGER NOT NULL DEFAULT 0,
    disabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE webhook_endpoints (
    id SERIAL PRIMARY KEY,
    workflow_id INTEGER NOT NULL,
    path TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')), input_data TEXT DEFAULT '{}', secret TEXT DEFAULT '',
    FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
);

CREATE TABLE workflow_runs (
    id TEXT PRIMARY KEY,
    workflow_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    input_data TEXT DEFAULT '{}',
    output TEXT DEFAULT '{}',
    error TEXT,
    events TEXT DEFAULT '[]',
    trace TEXT DEFAULT '[]',
    FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
);

CREATE TABLE workflow_run_steps (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    workflow_id INTEGER NOT NULL,
    node_id TEXT NOT NULL,
    node_name TEXT NOT NULL,
    node_type TEXT NOT NULL,
    tool_name TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    input_data TEXT DEFAULT '{}',
    output_data TEXT DEFAULT '{}',
    error TEXT,
    FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE,
    FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
);

CREATE TABLE workflow_versions (
    id SERIAL PRIMARY KEY,
    workflow_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    snapshot TEXT NOT NULL,
    created_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
);

CREATE INDEX idx_activity_log_user ON activity_log(user_id);

CREATE INDEX idx_activity_ts ON activity_log(timestamp);

CREATE INDEX idx_agent_sessions_user ON agent_sessions(user_id);

CREATE INDEX idx_chunks_document ON chunks(document_id, kind, position);

CREATE UNIQUE INDEX idx_collections_chat ON collections(session_id) WHERE kind = 'chat';

CREATE UNIQUE INDEX idx_collections_library_name ON collections(workspace_id, name) WHERE kind = 'library';

CREATE INDEX idx_documents_collection ON documents(collection_id, status);

CREATE INDEX idx_integrations_user ON integrations(user_id);

CREATE INDEX idx_jobs_due ON ingestion_jobs(status, next_attempt_at);

CREATE INDEX idx_llm_providers_user ON llm_providers(user_id);

CREATE INDEX idx_llm_usage_ts ON llm_usage(timestamp);

CREATE INDEX idx_llm_usage_user ON llm_usage(user_id);

CREATE INDEX idx_mcp_servers_user ON mcp_servers(user_id);

CREATE INDEX idx_memories_user ON memories(user_id);

CREATE INDEX idx_runs_workflow ON workflow_runs(workflow_id, started_at);

CREATE INDEX idx_user_settings_user ON user_settings(user_id);

CREATE INDEX idx_workflows_user ON workflows(user_id);

CREATE INDEX idx_workspaces_user ON workspaces(user_id);

CREATE INDEX registry_servers_match ON registry_servers(match_key);

CREATE INDEX registry_servers_title ON registry_servers(title);

-- Full-text search (SQLite: FTS5 tables). rowid is the indexed row's id, as in FTS5.
CREATE TABLE chunk_fts (
    rowid INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    heading_path TEXT NOT NULL DEFAULT '',
    document_name TEXT NOT NULL DEFAULT '',
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', text || ' ' || heading_path || ' ' || document_name)) STORED
);
CREATE INDEX idx_chunk_fts ON chunk_fts USING gin (tsv);

CREATE TABLE registry_fts (
    rowid INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    title TEXT,
    description TEXT,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', name || ' ' || COALESCE(title, '') || ' ' || COALESCE(description, ''))) STORED
);
CREATE INDEX idx_registry_fts ON registry_fts USING gin (tsv);

-- Vectors (SQLite: sqlite-vec when it loads). ponytail: cosine scan in Python; pgvector when collections get large.
CREATE TABLE chunk_vectors (
    chunk_id INTEGER PRIMARY KEY,
    workspace_id INTEGER,
    collection_id INTEGER,
    vector BYTEA NOT NULL
);

INSERT INTO workspaces (id, name) VALUES (1, 'Default');
SELECT setval(pg_get_serial_sequence('workspaces', 'id'), 1);

