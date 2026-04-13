# DevExec Sentinel Backend

Production-ready backend for async developer task execution using FastAPI, PostgreSQL, Redis, and RQ.

## Architecture

```text
app/
  main.py                         # FastAPI application factory
  core/
    config.py                     # Pydantic settings
    database.py                   # SQLAlchemy engine + session
    redis.py                      # Redis connection + RQ queue
  models/
    task.py                       # Task ORM model (with execution_trace, metrics, retry_count)
    execution.py                  # ExecutionResult + StepResult dataclasses
    deployment_event.py           # Deployment webhook event linkage table
    execution_event.py            # Ordered execution event stream table (seq)
    processed_webhook.py          # Idempotency table for delivery IDs
  schemas/
    task.py                       # Pydantic schemas (TaskCreate, TaskRead, ClosedLoop*)
    webhook.py                    # Webhook request/response contracts
  api/
    routes/
      tasks.py                    # REST endpoints
      webhook.py                  # Secure deployment webhook endpoint
      events.py                   # Event replay + websocket streaming
  services/
    task_service.py               # Task CRUD + lifecycle
    execution_engine.py           # Hardened step runner (retry, validation, timing)
    planner.py                    # Rule-based task planning
    closed_loop.py                # Closed-loop diagnostic execution
    metrics_collector.py          # Performance tracking + regression detection (placeholder)
    event_stream.py               # Persistent + pub/sub event emitter
    webhook_security.py           # GitHub HMAC signature validation
    webhook_idempotency.py        # Delivery registration and dedupe
    webhook_service.py            # Webhook task generation and deployment linking
    report_service.py             # Task summary + JSON/Markdown report builders
    notification_service.py       # Outbound webhook and optional GitHub PR notifications
  tools/
    registry.py                   # Tool registry with metadata
    api_test.py                   # Dynamic API test suite generator
    log_analysis.py               # Error classifier with confidence scoring
  workers/
    worker.py                     # RQ worker runner
    task_worker.py                # Task processing with trace persistence
```

## API Endpoints

### Core

- `POST /tasks` — Create and enqueue a task
- `GET /tasks/{id}` — Get task status, result, execution trace, and metrics
- `GET /tasks/{id}/summary` — Compact execution summary for dashboards/alerts
- `GET /tasks/{id}/report` — Full JSON report (failures, regression, fixes, metrics)
- `GET /tasks/{id}/report?format=markdown` — Markdown report (for PR comments/chat tools)

### Closed-Loop Execution

- `POST /tasks/closed-loop` — Run full diagnostic cycle:
  1. Run API tests (before)
  2. Analyze failures with log analysis
  3. Simulate fix based on error type
  4. Re-run API tests (after)
  5. Compare results (success rate delta, latency delta)

### Meta

- `GET /tasks/meta/tools` — List registered tools with metadata
- `GET /tasks/meta/metrics` — Metrics snapshot for monitoring/CI

### Webhook + Events

- `POST /webhook/deploy` — Secure webhook intake (GitHub-style signature + idempotency)
  - Accepts native GitHub push/pull_request payloads and extracts `repo`, `branch`, and `commit`
- `GET /tasks/{id}/events` — Ordered persisted execution events (`seq`)
- `WS /ws/tasks/{id}` — Replay + realtime event stream

### Health

- `GET /health` — Health check

## Example Payloads

### Create Task

```json
POST /tasks
{
  "input": {
    "url": "https://httpbin.org/post",
    "method": "POST",
    "headers": {"Content-Type": "application/json"},
    "body": {"name": "devexec"},
    "logs": "Timeout while connecting to upstream"
  }
}
```

### Closed-Loop Execution

```json
POST /tasks/closed-loop
{
  "url": "https://httpbin.org/post",
  "method": "POST",
  "headers": {"Content-Type": "application/json"},
  "body": {"name": "devexec"},
  "logs": "Timeout while connecting to upstream"
}
```

### Example Response (Closed-Loop)

```json
{
  "before": {
    "target": {"url": "https://httpbin.org/post", "method": "POST"},
    "test_cases": [...],
    "summary": {"total": 6, "passed": 4, "failed": 2, "latency_ms": 450.5},
    "failures": [...]
  },
  "after": {
    "target": {"url": "https://httpbin.org/post", "method": "POST"},
    "test_cases": [...],
    "summary": {"total": 6, "passed": 5, "failed": 1, "latency_ms": 380.2},
    "failures": [...]
  },
  "improvement": {
    "success_rate_before": 66.67,
    "success_rate_after": 83.33,
    "success_delta": 16.67,
    "latency_before_ms": 450.5,
    "latency_after_ms": 380.2,
    "latency_delta_ms": -70.3
  },
  "analysis": {
    "error_type": "timeout",
    "confidence": 71,
    "root_cause": "Service call exceeded expected response time.",
    "suggestion": "Check downstream availability, network latency, and timeout configuration."
  },
  "execution_trace": {
    "steps": [...],
    "start_time": "2026-04-13T18:30:00+00:00",
    "end_time": "2026-04-13T18:30:02+00:00",
    "duration_ms": 2150
  }
}
```

## Setup Instructions

### 1. Configure environment

The project now includes [.env](.env) with all required variables:

- PostgreSQL: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT`
- Redis: `REDIS_PORT`, `REDIS_URL`
- App/runtime: `DATABASE_URL`, `RQ_QUEUE_NAME`, `WEBHOOK_SECRET`
- Notifications: `NOTIFICATION_WEBHOOK_URL`, `NOTIFICATION_TIMEOUT_SECONDS`
- GitHub integration: `GITHUB_TOKEN`, `GITHUB_API_BASE_URL`, `ENABLE_GITHUB_PR_COMMENT`
- Groq: `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_BASE_URL`

Set your real secrets before production use.

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run PostgreSQL + Redis

```bash
docker compose up -d postgres redis
```

### 4. Run FastAPI API server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Run worker

Use a separate terminal:

```bash
python -m app.workers.worker
```

## Execution Engine Features

- **Strict step contract**: Each step returns `{success, data, error}`
- **Retry logic**: Max 2 attempts per step (retries on exception or invalid output)
- **Output validation**: Per-tool required key enforcement
- **Fallback output**: Safe defaults when a tool fails completely
- **Structured warnings**: Partial failures collected and persisted
- **Full timing**: Per-step and overall `start_time`, `end_time`, `duration_ms`
- **Ordered events**: Every event gets deterministic `seq` ordering
- **Replay reliability**: websocket clients receive `replay_start` then historical events in sequence

## Webhook Security + Reliability

- **Signature verification**: Validates `X-Hub-Signature-256` using HMAC SHA256 and shared secret
- **Idempotency**: Deduplicates repeated deliveries using `X-GitHub-Delivery`
- **Optional task dedupe**: Reuses task for same `repo_name + commit_sha + api_base_url`
- **GitHub context capture**: Persists event/repo/branch/commit/PR metadata into task input for downstream reporting

## Notifications + Reports

- **Webhook notifications**: emits `task_completed`, `failure_detected`, and `regression_detected`
- **GitHub PR comments (optional)**: posts markdown report when `ENABLE_GITHUB_PR_COMMENT=true`
- **Report artifact endpoints**: machine JSON and human-readable markdown for each task

## Notes

- Queue name: `devexec_tasks`
- Task records stored in PostgreSQL table `tasks`
- Worker flow: load task → set `running` → execute → persist trace + metrics → mark `completed`/`failed`
