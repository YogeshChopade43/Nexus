# Practice runs and Undo: design

**Date:** 2026-10-30
**Status:** approved in chat, awaiting spec review

## Why

Nexus's pitch to customers is that it's safe to let it act for you. Approval cards already cover what the agent is
about to do. Two gaps remain:

- **Before automating:** you can't test a workflow without it really sending emails or changing records.
- **After approving:** once an approved action has run, the only fix is doing it by hand in the app.

Success: a user can run any workflow and see exactly which changes it *would* make, without any being made; and a
user can reverse an action they approved in chat from the Activity page, seeing the exact reverse call first.

Decided with the user:
- Undo covers **chat approvals only** (chat in the app, Telegram, Slack, Discord). Workflow runs are out of scope.
- The reverse call is **proposed by the AI and approved by the user**, worked out when Undo is clicked.

## 1. Practice runs for workflows

### Behaviour

- `WorkflowRunRequest` gets `practice: bool = False`. The Workflows editor gets a **Practice run** button next to Run;
  it sends the same request (inputs included) with `practice: true`.
- `practice` lives on `RunState`, so it reaches nested graphs (loop, parallel, sub-workflow) unchanged.
- In `run_node`, before running the step, a step is **skipped** when:
  - it's an `action` whose tool's `policy` is `ask` (the same per-tool setting chat approvals use), or
  - it's an `http` step whose method isn't `GET`, or
  - its tool is `nexus__notify`.
- `nexus__ask_agent` needs nothing: it's already read-only.
- A skipped step returns
  `{"skipped": True, "would_call": <tool or "HTTP <METHOD> <url>">, "input": <rendered parameters>,
  "output": {"text": "[practice run: <tool> skipped]", "data": {}}}`.
  Parameters are rendered first, so the user sees the real values the step would have sent.
- Later steps keep running against the placeholder, so the whole workflow is exercised. A `condition` whose `field`
  points into a skipped step's output records `"uncertain": True` in its step result.
- Practice runs are stored like other runs, with `practice: true` in the run's input data so history can label them.
  They never send failure alerts (`_alert_failure`).
- Only manual runs from the API can be practice runs. Scheduled, webhook and poll triggers never set it.

### UI

- Run history and the run view show a **Practice** badge.
- The run view opens with a summary: "Would have made N changes", listing each skipped step's name, tool and
  parameters (collapsed JSON).

### Tests (engine, with a fake tool registry)

- An `ask` tool isn't executed in a practice run and is listed; an `allow` tool is executed.
- An HTTP POST is skipped and a GET runs.
- The next step receives the placeholder text.
- A normal run (practice off) executes the `ask` tool.

## 2. Undo for chat approvals

### Recording

In `BaseAgent`, where an approved call runs (the `needs_ok` branch in `abstract.py`), when the call succeeds
(`tool_executed`), log an activity entry:

- `type`: `action_approved`
- `title`: the tool's summary
- `metadata`: `{"tool": name, "arguments": args, "result": <data trimmed to 4 000 chars of JSON>, "app_id": ...}`
  (the agent doesn't know its chat's id, and Undo doesn't need it)

This covers the chat channels too, since they go through the same agent.

### Undoing

Two endpoints on the activity router, both scoped to the signed-in user (another user's entry is a 404):

- `POST /api/activity/{id}/undo/plan` → `{"tool", "arguments", "explanation"}` or 400 with a reason.
  The AI gets the original call, its trimmed result and the tool list of that app (`app_id`). It replies with JSON
  for the reverse call, or `{"impossible": "<why>"}` for things that can't be taken back (a sent message, a payment).
  The proposed tool must belong to the same app and exist in the registry, or the plan is refused.
- `POST /api/activity/{id}/undo/run` with the plan's `{tool, arguments}` → runs it the way workflows run actions
  (ownership and connection checks), then stores `undone_at` and `undo` (`{tool, arguments}`) in the entry's
  metadata, and logs an `action_undone` entry. A second run on the same entry is a 409.

The run step takes the plan from the client as confirmed by the user, but checks again that the tool belongs to the
original action's app.

### UI

On the Activity page, `action_approved` entries get an **Undo** button. Clicking it fetches the plan and shows a
confirmation dialog: the explanation, then tool and arguments. **Undo it** runs it; the entry then shows **Undone**.
Errors (no AI, app disconnected, impossible, reverse call failed) show in the dialog, and the entry stays undoable.

### Tests

- An approved call logs `action_approved`; an `allow` call that needed no approval doesn't.
- Plan with a fake AI returns the reverse call; a tool from another app is refused.
- Run executes the reverse tool and marks the entry undone; a second run is 409.
- Another user's entry is 404.

## Out of scope

- Undo for workflow-run actions and "undo this whole run".
- Undo without confirmation, and time limits on Undo.
- Simulating what read-only steps would return differently after skipped changes.
