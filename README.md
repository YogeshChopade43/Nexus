# Nexus V0

Nexus is a local agent runtime for connecting natural-language requests to application capabilities. The V0 release includes a React and TypeScript client, a FastAPI backend, SQLite-backed app connections, a tool registry, deterministic mock tools, safe execution events, and a basic workflow model.

## Requirements

- Node.js 20 or newer
- Python 3.9 or newer
- PowerShell on Windows

## Backend

From the repository root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

The API is available at `http://localhost:8000`. The default database is `backend/data/nexus.db`; set `DATABASE_PATH` in `.env` to use another SQLite file.

## Frontend

Open a second terminal and run:

```powershell
cd frontend
npm install
npm run dev
```

Open the Vite URL printed by the command. The client calls `http://localhost:8000` by default. Set `VITE_API_URL` in `frontend/.env` to override the API address.

## V0 workflow

1. Open the Apps drawer.
2. Turn on the apps whose capabilities Nexus may use.
3. Ask the agent to perform a task, such as listing GitHub pull requests or checking Grafana logs.
4. Review the high-level execution events shown with the response.
5. Use the Workflows view to create and run a basic saved workflow.

Connection state is persisted in SQLite. The included connectors are real API clients. Tool implementations are registered separately and can be swapped for production integrations.

## API summary

- `GET /health`
- `GET /api/apps`
- `GET /api/apps/{app_id}`
- `POST /api/apps/{app_id}/connection`
- `POST /api/agent/run`
- `GET /api/tools`
- `GET /api/tools/available`
- `GET /api/tools/app/{app_id}`
- `GET /api/workflows`
- `GET /api/workflows/{workflow_id}`
- `POST /api/workflows`
- `PATCH /api/workflows/{workflow_id}`
- `POST /api/workflows/{workflow_id}/run`

## Validation

With the backend running on port 8000:

```powershell
cd backend
python smoke_test.py
```

The smoke test uses the configured database, so use a temporary `DATABASE_PATH` when you want an isolated run:

```powershell
$env:DATABASE_PATH="$env:TEMP\nexus-validation.db"
python smoke_test.py
```

The test covers health, app discovery, connection persistence, capability filtering, GitHub/Slack/Grafana behavior, workflow execution, and tool discovery.
