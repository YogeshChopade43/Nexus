# Nexus

Nexus is a local agent runtime that connects natural-language requests and automated workflows to the tools of your apps. Apps are connected through **MCP servers** (Model Context Protocol): add any server and its tools become available to the chat agent and to workflows. Nexus has no per-app code.

## Quick start

```powershell
python start.py          # first run sets up backend/.venv and node_modules, then starts both
```

Open http://localhost:5173. Or with Docker (one container, port 8000):

```powershell
docker compose up --build    # then open http://localhost:8000
```

## Requirements

- Python 3.10 or newer (3.11 recommended; the MCP SDK requires 3.10+)
- Node.js 20 or newer (for the frontend)

## Backend

From the repository root:

```powershell
cd backend
py -3.11 -m venv .venv311
.\.venv311\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

If `NEXUS_SECRET_KEY` is not set, a development key is generated in `data/.nexus_secret_key`; set your own in `.env` for anything long-lived. Keep it stable: it encrypts MCP server secrets and LLM API keys. The API listens on `http://localhost:8000`. The default database is `backend/data/nexus.db`; set `DATABASE_PATH` to change it.

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

The client calls `http://localhost:8000` by default; set `VITE_API_URL` in `frontend/.env` to override it.

## Connecting apps: the Marketplace (MCP servers)

Nexus connects to **hosted** MCP servers only: it never launches programs on your computer. Open **Marketplace** to browse hosted servers from verified publishers (who proved to the [MCP Registry](https://registry.modelcontextprotocol.io) that they own their domain), plus a hand-picked **Featured** shelf. Nexus keeps a local copy of the listings (synced in the background at startup when older than a day, then daily, or with **Refresh**), so search is instant, matches descriptions too, and works offline. Open a listing, fill in the settings it asks for (API keys are masked and stored encrypted) and click **Install**; servers that use sign-in then show **Sign in to …**. Installed servers are managed from the same panel (filter **Installed**). `NEXUS_REGISTRY_URL` points at another registry; `NEXUS_REGISTRY_SYNC=off` turns off automatic syncs.

For a hosted server that isn't listed, click **Add custom server** and give its URL (and headers, such as `Authorization: Bearer ...`, if it uses an API key instead of sign-in).

Headers are stored encrypted and never returned by the API. Tools are named `<server>__<tool>`; tool results are available in workflows as `{{ steps.<id>.text }}` and, when the result is JSON, `{{ steps.<id>.data }}`. Nexus reconnects automatically if a server exits or the connection drops.

- **Import config** reads an existing config from Claude Desktop, Claude Code (`.mcp.json`, `~/.claude.json`), Cursor or VS Code; local (command) servers in it are skipped.
- **Sign-in (OAuth)**: hosted servers that require it (Notion, Linear, Sentry, …) show **Sign in**; tokens are stored encrypted and refreshed automatically. The sign-in page returns to `NEXUS_PUBLIC_URL/api/mcp/servers/oauth/callback` (default `http://localhost:8000`); set `NEXUS_PUBLIC_URL` if the browser reaches the backend at another address.
- **Tool policies**: per tool, Allow (runs), Ask (the chat agent asks you first) or Block (hidden). Tools that change things default to Ask.
- **Logs**: each server shows connection events and call counts. Tool lists refresh automatically when a server announces a change.

Security: Nexus refuses to create or start local (command) MCP servers. The code that runs them is kept only for the test suite's fixture servers, behind `NEXUS_ALLOW_LOCAL_SERVERS=true`; don't set it in a real install.

## Chat

- Replies are Markdown (tables with Copy / CSV, code blocks with Copy) and stream as they are written. **Stop** cuts a reply short and keeps what was said; **Retry** asks again; **Edit** changes your last question and asks again. Each reply shows its tokens, and its cost once prices are entered on the Dashboard.
- **Tool choice**: each message is offered Nexus's own tools plus the app tools whose names or descriptions share a word with it (up to 24), and a `nexus_find_tools` tool to fetch others; small talk sends no app tools. The agent takes up to 10 rounds of tool calls per message. Large tool results aren't cut off: the agent reads the rest with `nexus_read_result`.
- **Long chats** keep the last 20 messages verbatim and a running summary of earlier ones.
- **Chat settings** (sliders icon): which MCP servers this chat may use, standing instructions, and temperature. Saved with the conversation.
- **Conversations** (clock icon): search past chats by title or message text.
- Tools whose description starts with a read verb ("Search…", "List…", "Get…") default to *Allow* even if the server marks them destructive.

## Knowledge: document search (RAG) and memory

Design: `docs/superpowers/specs/2026-10-08-production-rag-design.md`. Code: `backend/app/rag/`.

- **Libraries** (Knowledge page): group documents by topic. Accepted: PDF with selectable text, Word (.docx), Excel (.xlsx), Markdown, HTML, CSV, JSON and other text files, up to 25 MB and 5 million characters each, 500 documents per library. The same file twice is ignored; a changed file with the same name becomes a new version and replaces the old one.
- **Processing** runs in the background: files are split along their headings into sections (~1,200 tokens) and overlapping passages (~350 tokens) with page numbers, embedded with a local model and indexed. Status shows queued / processing N% / ready / failed (with the reason and a Retry button). Jobs survive restarts and retry 3 times (30 s, 2 min, 10 min).
- **Search** is hybrid: keyword search (BM25 with English stemming) and vector search run together, are merged with Reciprocal Rank Fusion, re-scored by a local reranker (switch on the Knowledge page), limited to 3 passages per section, and expanded to whole sections within a 3,000-token budget. When the reranker isn't confident, the model is told the passages may not answer the question.
- **In chat** the agent searches with `nexus__search_documents` (offered when the chat can read ready documents) and cites passages like `[1]`; answers show **Sources** chips that open the passage in context. Chat settings > **Answer from library** searches a chosen library for every message. Files attached in a chat that are PDFs or longer than 20,000 characters go into that chat's private collection (deleted with the chat); smaller text files are inlined.
- **Local models, no API cost**: `BAAI/bge-small-en-v1.5` (embeddings) and `Xenova/ms-marco-MiniLM-L-6-v2` (reranking) via fastembed, downloaded once (~220 MB) into `backend/data/models` (or `NEXUS_MODELS_DIR`). Nothing leaves the machine. Vectors live in SQLite via `sqlite-vec` (with a pure-Python fallback).
- **Quality**: `python -m app.rag.eval --real` scores keyword, vector, hybrid and hybrid+rerank retrieval on a golden set (`backend/tests/rag_golden/`); CI runs it with deterministic stand-in models and fails on a regression.
- Documents from the earlier keyword-only knowledge base are imported into a library named "Imported" on first start.
- **Memory**: facts the agent keeps in mind in every chat. Say "remember …" in chat (`nexus__remember`), or add them on the page. `nexus__forget` removes one.

## Security

- Nexus has no login yet: keep it on your own machine. The backend binds to `127.0.0.1` by default.
- **Machine-level actions** (command-launched MCP servers, backups) are allowed only from this machine. `NEXUS_TRUSTED_NETWORKS` (comma-separated, e.g. `172.16.0.0/12`) counts other networks as this machine; the Docker setup uses it.
- **OS keychain**: `NEXUS_KEYCHAIN=true` keeps the generated `NEXUS_SECRET_KEY` in Windows Credential Manager / macOS Keychain / Secret Service instead of `data/.nexus_secret_key` (an existing key file is moved there).

## Dashboard and AI costs

- **Dashboard** shows runs per day, failure rate, the workflows that fail most, the slowest steps, and AI tokens per day and per model. Enter your provider's prices per million tokens there to see estimated cost.
- **Daily AI limit** (Settings > General): once today's (UTC) tokens reach it, chat and workflows stop calling the AI until midnight UTC. Streamed chat replies are estimated at ~4 characters per token.
- Poll triggers show how many checks a day an interval means.
- Workflows can be viewed as a **canvas** diagram (Steps / Canvas switch on the workflow page).

## Reliability

- Runs interrupted by a restart resume automatically (within 24 hours), reusing the outputs of steps that had finished; the step in progress runs again. Set `NEXUS_RESUME_RUNS=false` to leave them failed instead.
- The bell in the header lists failed runs, disconnected servers and resumed runs.
- Runs and activity older than the retention period (Settings > General, default 30 days, 0 = forever) are deleted daily.
- **Settings > Backup** downloads a zip with a copy of the database and the secret key, plus restore steps. It works only from the machine running Nexus.
- Schema changes are numbered migrations in `app/core/database.py` (`MIGRATIONS`), tracked with SQLite's `user_version`.

## API summary

- `GET /health`
- `GET|POST /api/mcp/servers`, `GET|PATCH|DELETE /api/mcp/servers/{id}`, `POST /api/mcp/servers/{id}/restart`, `GET /api/mcp/servers/{id}/logs`, `POST /api/mcp/servers/{id}/sign-out`, `GET /api/mcp/servers/oauth/callback`
- `POST /api/agent/run/stream`, `POST /api/agent/sessions/{id}/approval/stream`, `POST /api/agent/sessions/{id}/rewind`, `PUT /api/agent/sessions/{id}/settings`, `GET /api/agent/sessions?q=`
- `GET|POST /api/rag/collections`, `PATCH|DELETE /api/rag/collections/{id}`, `GET|POST /api/rag/collections/{id}/documents` (multipart `file`), `POST /api/rag/chats/{session_id}/documents`, `GET|DELETE /api/rag/documents/{id}`, `POST /api/rag/documents/{id}/retry`, `POST /api/rag/documents/{id}/move`, `GET /api/rag/documents/{id}/chunks/{chunk_id}`, `POST /api/rag/search`, `GET /api/rag/status`
- `GET|POST /api/knowledge/memories`, `DELETE /api/knowledge/memories/{id}`
- `GET /api/activity/notifications`, `POST /api/activity/notifications/read`, `GET /api/settings/backup`
- `POST /api/agent/run`
- `GET /api/tools`
- `GET /api/tools/available`
- `GET /api/tools/app/{server_slug}`
- `GET /api/workflows`
- `GET /api/workflows/{workflow_id}`
- `POST /api/workflows`
- `PATCH /api/workflows/{workflow_id}`
- `POST /api/workflows/{workflow_id}/run`

## Workflows

Build workflows the Power Automate way: a **trigger**, then **steps** added with "+". Steps are tools from your connected MCP servers or built-ins: AI prompt, Condition (with "If yes" and "If no" branches), Compose, and Delay. Each field's ⚡ button inserts data from the trigger or earlier steps, such as `{{ trigger.inputs.repo }}`, `{{ steps.action_1.text }}`, or `{{ steps.action_1.data.items | length }}`. Actions can retry and can be set to continue if they fail.

Triggers:

- **Manually**: run with the **Run** button on the workflow list. Optional inputs (text, number, yes/no) are asked for before each run and are available as `{{ trigger.inputs.<name> }}`.
- **Recurrence**: every N minutes (at least 5) or hours, daily, weekly on chosen weekdays, or monthly on a day, at a time in your timezone. The builder shows the next three runs. A raw cron expression is available under "More".
- **When something new appears in an app**: Nexus calls an MCP tool on an interval (1–1440 minutes) and starts one run per new item, available as `{{ trigger.item }}`. The first check only records existing items. Each check starts at most 25 runs, and the last check's time and any error are shown on the workflow.
- **Webhook**: a secret URL, shown on the workflow page after saving, runs the workflow when called.
- **App event** (under "More"): receives events at `POST /api/webhooks/apps/{app_id}`. Set `NEXUS_WEBHOOK_TOKEN` (pass it as `?token=`) or, for GitHub, `NEXUS_GITHUB_WEBHOOK_SECRET` (signature checked). Without either, app webhooks are refused.

Schedules and app checks only run while the workflow is **Active**.

## Configuration notes

- If `NEXUS_SECRET_KEY` is unset outside production, a key is generated in `data/.nexus_secret_key`. Back it up; losing it makes stored credentials unreadable.
- `RATE_LIMIT` (default `300/minute`) sets the per-client API rate limit.
- `NEXUS_KEYCHAIN`, `NEXUS_TRUSTED_NETWORKS`, `NEXUS_PUBLIC_URL`, `NEXUS_RESUME_RUNS`: see the sections above.
- `NEXUS_STATIC_DIR`: serve a built frontend from the backend (the Docker image sets it; build with `VITE_API_URL=same-origin`).

## Tests

```powershell
cd backend
.\.venv311\Scripts\python -m pytest tests
.\.venv311\Scripts\python smoke_test.py
```

The tests launch a small fixture MCP server (`tests/fixtures/echo_mcp_server.py`) over both stdio and HTTP. Test dependencies: `pip install -r requirements-dev.txt`.

Frontend:

```powershell
cd frontend
npm test          # component tests (Vitest + Testing Library)
npm run e2e       # browser tests (Playwright): starts its own backend on a temporary database
npm run lint
npm run build
```

`npm run e2e` uses your installed Chrome locally; set `NEXUS_PYTHON` if the backend's Python isn't `backend/.venv311`. GitHub Actions (`.github/workflows/ci.yml`) runs the backend tests, lint, component tests, build and browser tests on every push and pull request.
