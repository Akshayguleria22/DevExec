# DevExec Sentinel Backend

Production-ready backend foundation for async developer task execution using FastAPI, PostgreSQL, Redis, and RQ.

## Structure

```text
app/
  main.py
  core/
    config.py
    database.py
    redis.py
  models/
    task.py
    execution.py
  schemas/
    task.py
  api/
    routes/
      tasks.py
  services/
    task_service.py
    execution_engine.py
  tools/
    registry.py
    api_test.py
    log_analysis.py
  workers/
    worker.py
    task_worker.py
requirements.txt
docker-compose.yml
README.md
```

## API

- `POST /tasks`
  - Input body:
    ```json
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
  - Returns:
    ```json
    {
      "task_id": "<uuid>"
    }
    ```

- `GET /tasks/{id}`
  - Returns task status and execution outputs:
    - `status`
    - `result`
    - `warnings`
    - `step_errors`

## Setup Instructions

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run PostgreSQL + Redis

```bash
docker compose up -d postgres redis
```

### 3. Run FastAPI API server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Run worker

Use a separate terminal:

```bash
python -m app.workers.worker
```

## Optional: Run backend service in Docker Compose

```bash
docker compose up backend
```

## Notes

- Queue name: `devexec_tasks`
- Task records are stored in PostgreSQL table `tasks`.
- Worker flow:
  - load task
  - set `running`
  - execute tools via execution engine
  - store `result`, `warnings`, `step_errors`
  - mark `completed` or `failed`
