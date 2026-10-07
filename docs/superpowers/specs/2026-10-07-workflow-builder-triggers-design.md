# Workflow builder and triggers: design

Date: 2026-10-07
Status: approved in conversation; awaiting written-spec review
Sub-project 1 of the "Power Automate + n8n" workflow initiative.

## Goal

Let a user automate a multi-step chore and then run it with one click or on a schedule. A workflow starts with a trigger, then runs actions one after another; actions come from connected apps (MCP servers), the LLM, and built-in steps.

Success looks like this: a user builds "every weekday at 09:00, list open GitHub issues; if there are any, have the AI summarize them and post the summary to Slack" entirely in the UI, without writing cron or template syntax by hand, and it runs on schedule and on demand.

## Decisions taken

| Question | Decision |
|---|---|
| Builder layout | Vertical flow, Power Automate style. A canvas may come later. |
| Storage | Keep the existing node/edge graph; the builder converts tree to graph and back. |
| App triggers | Polling: Nexus calls an MCP tool on an interval and starts one run per new item. |
| Scope | Triggers, builder, and one-click runs. Loops, parallel branches, the HTTP node, the code node, and templates are out of scope. |

## 1. Triggers

Every workflow has exactly one trigger node (`type: "trigger"`), shown as the first card. Its `config.trigger_type` is one of the values below. The stored `workflows.trigger` column is derived from it on save, as today.

### 1.1 Manual

```json
{"trigger_type": "manual", "inputs": [{"name": "repo", "type": "text", "required": true, "default": ""}]}
```

- Input types: `text`, `number`, `boolean`.
- Input names must match `^[a-zA-Z_][a-zA-Z0-9_]{0,39}$` and must be unique; at most 20 inputs.
- Run requests send `input_data`. The backend validates them against the declared inputs: required inputs must be present, `default` fills missing values, and `number` and `boolean` values are coerced. Validation failures return 400 and no run is created.
- Steps read the values as `{{ trigger.inputs.<name> }}`.
- Manual-trigger runs keep `trigger = {"type": "manual", "inputs": {...}}`.

### 1.2 Recurrence

```json
{"trigger_type": "recurrence", "frequency": "week", "interval": 1,
 "at": "09:00", "weekdays": ["mon", "tue", "wed", "thu", "fri"], "month_day": null,
 "timezone": "Asia/Kolkata"}
```

`frequency` is one of `minute | hour | day | week | month`, and `interval` is 1–1000 (minute requires at least 5). Each frequency maps to an APScheduler trigger:

| frequency | Trigger | Uses |
|---|---|---|
| minute | `IntervalTrigger(minutes=interval)` | — |
| hour | `IntervalTrigger(hours=interval)` | — |
| day | `CronTrigger(hour, minute)` when `interval == 1`, otherwise `IntervalTrigger(days=interval, start_date=next occurrence of at)` | `at` |
| week | `CronTrigger(day_of_week=weekdays, hour, minute)`; `interval > 1` is rejected in v1 | `at`, `weekdays` (at least 1) |
| month | `CronTrigger(day=month_day, hour, minute)`; `interval > 1` is rejected | `at`, `month_day` 1–31 (months without that day skip it) |

- `at` defaults to `00:00`, and `timezone` must be a valid IANA name.
- The existing `schedule` trigger type (a raw cron string) stays and is shown under "Advanced: cron expression".
- `POST /api/workflows/recurrence/preview`, with the recurrence config as its body, returns `{"next_runs": [iso, iso, iso]}` or a 400 explaining what is invalid. The builder shows these next three runs.
- Scheduled runs keep `trigger = {"type": "recurrence", "fired_at": iso}`.

### 1.3 Polling ("When something new appears in an app")

```json
{"trigger_type": "poll", "tool": "github__list_issues", "parameters": {"state": "open"},
 "interval_minutes": 5, "items_path": "", "id_field": ""}
```

- `interval_minutes` is 1–1440 and defaults to 5.
- **Finding items.** The tool result is converted with the MCP result-to-dict function, giving `{text, data}`. With `items_path` set, it is a dotted path into `data`. Otherwise `data` itself is used when it is a list; if not, the first list-valued key of `data` (in insertion order); if there is none, the poll fails with "Could not find a list of items in the result; set the items path".
- **Item identity.** With `id_field` set, that field is the identity. Otherwise Nexus uses the first of `id`, `number`, `key`, `uid`, `url` present on the first item. If none is present, the identity is the SHA-1 of the item's JSON (sorted keys).
- **State.** A new table `trigger_state(workflow_id PRIMARY KEY, seen TEXT json list, baseline_done INTEGER, last_checked_at TEXT, last_error TEXT)`. `seen` keeps the most recent 1000 identities in order.
- **Baseline.** On the first successful check, all current identities are recorded and no runs start.
- **New items.** On later checks, each item whose identity is not in `seen` starts one run with `trigger = {"type": "poll", "item": <item>, "tool": ...}`. Runs start in result order, sequentially, with at most 25 per check; the remaining items are recorded as seen, and a warning is logged and stored in `last_error`.
- **Failures.** An exception or an `is_error` result records `last_error` and `last_checked_at`, starts no runs, and leaves `seen` unchanged. An unconnected MCP server counts as a failure ("<server> is not connected").
- **Config changes.** Changing the tool, parameters, `items_path`, or `id_field` resets the state, so the next check is a new baseline.
- **Status.** The workflow response gains `trigger_status: {last_checked_at, last_error}` for poll triggers.

### 1.4 Webhook and app event

Both are unchanged.

## 2. Builder (frontend)

### 2.1 Tree ↔ graph conversion

A pure module `frontend/src/components/workflow/flowTree.ts`:

```ts
type FlowStep =
  | { kind: 'step'; node: WorkflowNode }
  | { kind: 'condition'; node: WorkflowNode; yes: FlowStep[]; no: FlowStep[] };
interface FlowTree { trigger: WorkflowNode | null; steps: FlowStep[] }
function graphToTree(nodes, edges): FlowTree | null   // null = graph is not tree-shaped
function treeToGraph(tree): { nodes; edges }
```

`treeToGraph` rules:

- **Steps.** Consecutive steps are joined by plain edges, and the trigger connects to the first step.
- **Conditions.** A condition connects to the first step of `yes` with `sourceHandle: "true"` and to the first step of `no` with `"false"`.
- **After a condition.** The step that follows a condition receives one edge from the last node of each branch. If a branch is empty, the edge comes from the condition itself with that branch's handle. If both branches are empty, it gets both handled edges from the condition.
- **Node ids** are kept, and new ids use the existing `<type>_<n>` scheme.

`graphToTree` reverses these rules and returns `null` for anything they cannot produce, such as a node with multiple plain outgoing edges, cycles, or a join of unrelated branches. In that case the builder shows "This workflow was created with a structure the step builder can't display" with only Run and Delete available.

The conversion must round-trip: `graphToTree(treeToGraph(t))` equals `t` for any tree. A self-check `flowTree.check.ts`, run with `npx tsx`, asserts round trips for these cases: linear, condition with both branches, condition with an empty branch, nested condition, and steps after a condition.

### 2.2 Layout

- **The builder** (`WorkflowBuilder.tsx`) replaces the current `WorkflowEditor` content inside the existing modal. Name, description, and Active stay at the top.
- **Trigger card.** It always comes first and opens a type picker with Manual, Recurrence, "When something new appears in an app", and Webhook; App event is shown under "More". It renders the form for the chosen type.
- **Recurrence form.** Frequency select, interval, time, a weekday toggle row, month day, and a timezone input defaulting to the browser timezone (`Intl.DateTimeFormat().resolvedOptions().timeZone`). It shows the "Next runs" list, refreshed with a 400 ms debounce through the preview endpoint.
- **Polling form.** The same tool picker and parameter form as actions; interval; and an "Advanced" section with the items path and ID field.
- **Manual form.** An editable list of inputs (name, type, required, default).
- **Step cards.** Collapsed, a card shows its icon, name, and a one-line summary ("GitHub · list_issues"). Expanded, it shows the config form. Every card has a `⋯` menu with Rename, Retry policy (0–5), "Continue if this step fails", Move up, Move down, and Delete. Moving stays within the same branch.
- **"+" between cards and at the end of each branch** opens the action picker:
  - A search box.
  - "Built-in": AI prompt, Condition, Compose, Delay.
  - One group per connected MCP server, listing its tools by remote name with descriptions. Servers that are not connected are shown greyed out with a link to the MCP Servers page.
- **Condition cards** render "If yes" and "If no" columns side by side, stacked on narrow screens. Each column has its own "+".

### 2.3 Dynamic content

Every text parameter field has a "⚡" button that opens a popover listing:

- Trigger values, by trigger type:
  - manual: `trigger.inputs.<name>` for each input
  - poll: `trigger.item` and the fields of the last seen item, when known
  - webhook: `trigger.payload`
  - recurrence: `trigger.fired_at`
- Each earlier step on the path to this card: `.text` and `.data`. When a run has executed that step before, it also lists the top-level keys of `.data`, from the latest run's trace event output (one level deep, maximum 30 keys).

Choosing an entry inserts `{{ <path> }}` at the cursor. The latest-run outputs come from `GET /api/workflows/{id}/runs?limit=1`, which already exists.

## 3. One-click runs

- **Workflow list.** Each row in `WorkflowList` gets a "Run" button. If the trigger is manual with inputs, a modal form generated from the declared inputs opens first; otherwise the run starts immediately. The latest status shows on the row.
- **Workflow page.** The "Run" button follows the same rule. "Run with input" stays for advanced JSON.
- **Run history** shows the trigger type of each run.

## 4. Backend changes

| File | Change |
|---|---|
| `app/triggers/models.py` | `TriggerConfig` adds `recurrence` fields, `inputs`, and the poll fields; `type` gains `recurrence` and `poll`. |
| `app/workflows/recurrence.py` (new) | Validate recurrence config, convert it to an APScheduler trigger, compute the next N runs. |
| `app/workflows/polling.py` (new) | Find items and their identities, `trigger_state` persistence, the `poll_once(workflow_id)` function. |
| `app/workflows/scheduler.py` | `sync_workflow_schedule` handles `recurrence` (via `recurrence.py`) and `poll` (an interval job calling `poll_once`, `max_instances=1`). |
| `app/api/routes/workflows.py` | Save path: trigger node → config (inputs, recurrence, poll); validation errors return 400; poll state resets on change. Run endpoint: validate and coerce manual inputs. New `POST /recurrence/preview`. Response adds `trigger_status`. |
| `app/workflows/engine.py` | `run_workflow` accepts manual inputs as `trigger.inputs` (manual runs pass `trigger={"type": "manual", "inputs": ...}`). No graph changes. |
| `app/core/database.py` | Create the `trigger_state` table. |

## 5. Error handling

- Invalid recurrence, poll, or input definitions return 400 on save, with a message naming the field.
- An invalid manual input value returns 400 on run.
- Poll failures are recorded in `trigger_state.last_error` and shown on the workflow page; they never create failed runs.
- The 25-runs-per-check cap stops a misconfigured poll, such as one with an ID field that changes on every call, from flooding the system.
- If an MCP server is not connected at run time, the action fails as it does today, with "App '<server>' is not connected".

## 6. Testing

- `tests/test_recurrence.py`: each frequency maps to the expected trigger and next runs, including timezone handling; invalid configs are rejected.
- `tests/test_polling.py`, against the fixture MCP server. The fixture gains a `list_feed` tool that returns `{"items": [...]}`, read from the JSON file named by the server's `FEED_FILE` env var, so a test changes the items by rewriting that file between polls. The tests cover:
  - the baseline starts no runs
  - a new item starts exactly one run carrying `trigger.item`
  - a repeated poll does not create a duplicate run
  - a tool error records `last_error`
  - the cap of 25 is enforced
  - a config change resets the state
- `tests/test_nexus.py` additions: manual inputs are validated, coerced, and exposed as `trigger.inputs`; the preview endpoint works.
- `flowTree.check.ts`: round-trip assertions.
- Browser check: build the example flow from the Goal section with the fixture server, run it from the list with inputs, and confirm the recurrence preview shows three next runs.

## Out of scope (later sub-projects)

Loops and for-each, parallel branches, merge nodes, sub-workflows, the HTTP request node, the code node, a free-form canvas, run-single-node testing, re-run from a failed step, templates, import/export, version history, and AI-drafted workflows.
