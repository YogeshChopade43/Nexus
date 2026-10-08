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
- Node.js 20 or newer (for the frontend, and for `npx`-launched MCP servers)
- `uv`/`uvx` if you use Python-based MCP servers

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

## Connecting apps with MCP servers

Open **MCP Servers** and click **Add server**:

- **Local command (stdio)**: Nexus launches the server as a subprocess. Example: command `npx`, arguments `-y @notionhq/notion-mcp-server`, environment `NOTION_TOKEN=...`.
- **Remote URL (streamable HTTP)**: Nexus connects to a hosted server. Example: URL `https://api.githubcopilot.com/mcp/`, header `Authorization: Bearer ghp_...`.

Environment values and headers are stored encrypted and never returned by the API. Tools are named `<server>__<tool>`; tool results are available in workflows as `{{ steps.<id>.text }}` and, when the result is JSON, `{{ steps.<id>.data }}`. Nexus reconnects automatically if a server exits or the connection drops.

- **Catalog** prefills the form for popular servers. **Import** reads an existing config from Claude Desktop, Claude Code (`.mcp.json`, `~/.claude.json`), Cursor or VS Code.
- **Sign-in (OAuth)**: hosted servers that require it (Notion, Linear, Sentry, …) show **Sign in**; tokens are stored encrypted and refreshed automatically. The sign-in page returns to `NEXUS_PUBLIC_URL/api/mcp/servers/oauth/callback` (default `http://localhost:8000`); set `NEXUS_PUBLIC_URL` if the browser reaches the backend at another address.
- **Tool policies**: per tool, Allow (runs), Ask (the chat agent asks you first) or Block (hidden). Tools that change things default to Ask.
- **Logs**: each server shows connection events, call counts, and for local servers their own error output (saved under `data/mcp-logs/`). Tool lists refresh automatically when a server announces a change.

Security: launching commands is code execution. The backend binds to `127.0.0.1` by default and accepts command-launched servers only from localhost requests. `NEXUS_ALLOW_REMOTE_STDIO=true` disables that check; only set it behind your own authentication.

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
