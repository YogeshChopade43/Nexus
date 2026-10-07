# Nexus

Nexus is a local agent runtime that connects natural-language requests and automated workflows to the tools of your apps. Apps are connected through **MCP servers** (Model Context Protocol): add any server and its tools become available to the chat agent and to workflows. Nexus has no per-app code.

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

Security: launching commands is code execution. The backend binds to `127.0.0.1` by default and accepts command-launched servers only from localhost requests. `NEXUS_ALLOW_REMOTE_STDIO=true` disables that check; only set it behind your own authentication.

## API summary

- `GET /health`
- `GET|POST /api/mcp/servers`, `GET|PATCH|DELETE /api/mcp/servers/{id}`, `POST /api/mcp/servers/{id}/restart`
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

## Tests

```powershell
cd backend
.\.venv311\Scripts\python -m pytest tests
.\.venv311\Scripts\python smoke_test.py
```

The tests launch a small fixture MCP server (`tests/fixtures/echo_mcp_server.py`) over both stdio and HTTP.
