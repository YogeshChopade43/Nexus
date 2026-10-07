# Workflows: Exceed Power Automate

## Current State
- CRUD workflows with node/edge graph editor
- Sequential step execution (topological sort of nodes)
- App connection checking
- Run persistence + trace endpoint
- Frontend editor with node creation, edges, app connections
- Manual trigger only

## Gaps vs Power Automate

### Triggers
| Feature | Power Automate | Nexus Current | Nexus Target |
|---------|---------------|---------------|--------------|
| Manual | Yes | Yes | Yes |
| Scheduled (cron) | Yes | No | **Implement** |
| Webhook (incoming HTTP) | Yes | No | **Implement** |
| Polling | Yes | No | **Implement** |

### Control Flow
| Feature | Power Automate | Nexus Current | Nexus Target |
|---------|---------------|---------------|--------------|
| Condition (if/else) | Yes | No | **Implement** |
| Parallel branches | Yes | No | **Implement** |
| Loop (for each) | Yes | No | **Implement** |
| Do until | Yes | No | Post-MVP |

### Data Operations
| Feature | Power Automate | Nexus Current | Nexus Target |
|---------|---------------|---------------|--------------|
| Variables | Yes | No | **Implement** |
| Compose/transform | Yes | No | **Implement** |
| Reference previous step output | Yes | No | **Implement** |
| Inline expressions | Yes | No | **Implement (Jinja2)** |

### Error Handling
| Feature | Power Automate | Nexus Current | Nexus Target |
|---------|---------------|---------------|--------------|
| Continue on error | Yes | No | **Implement** |
| Retry policies | Yes | No | **Implement** |
| Configure run-after | Yes | No | **Implement** |

## Implementation Plan

### Phase 1: Core Engine Enhancements (Week 1)
1. **Condition nodes** - Add `condition` node type with expression evaluation, branching via edges
2. **Parallel branches** - Use asyncio.gather() to run independent nodes concurrently, merge results
3. **Loop (foreach)** - Iterate over arrays from previous step outputs
4. **Variables** - Add variable scope during execution, set/get variable nodes
5. **Error handling** - Continue-on-error flag per node, retry with backoff

### Phase 2: Trigger Types (Week 2)
1. **Scheduled triggers** - Add `schedules` table, background task runner (APScheduler or Celery)
2. **Webhook triggers** - Add `webhook_endpoints` table, public endpoint receiver
3. **Polling triggers** - Built on scheduled triggers + tool calls

### Phase 3: Data Operations (Week 3)
1. **Compose/transform nodes** - Transform data between steps
2. **Step output references** - `{{steps.node1.outputs.field}}` syntax
3. **Jinja2 expression engine** - Inline expressions in node parameters
4. **Variable nodes** - Set/get/initialize variables

### Phase 4: Monitoring & UX (Week 4)
1. **Real-time streaming** - SSE endpoint for live execution updates
2. **Execution timeline** - Gantt-style view of parallel steps
3. **Run details page** - Full trace with step inputs/outputs
4. **Retry failed runs** - Re-execute from failed step

## Backend Architecture Changes

### New Database Tables
- `schedules` - cron expressions, workflow_id, next_run_at
- `webhook_endpoints` - unique paths, workflow_id, event_type
- `workflow_run_steps` - individual step results with timing

### New Node Types
- `condition` - evaluates expression, routes to branches
- `parallel` - splits into concurrent branches
- `foreach` - iterates over array
- `variable` - set/get variables
- `compose` - data transformation
- `http_request` - makes HTTP calls
- `delay` - wait for duration
- `terminate` - end workflow with status

### Engine Refactoring
- Replace linear step execution with graph traversal
- Support branching (multiple paths from condition)
- Support merging (wait for all branches at join node)
- Track variable scope across steps
- Capture step outputs for reference
