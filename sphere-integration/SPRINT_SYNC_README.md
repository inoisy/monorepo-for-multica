# Sprint Sync Service

Service for synchronizing sprint tasks between Sphere (Bitrix24) and local database via MCP.

## Features

- **Pull**: Fetch tasks from Sphere by sprint tag and store in local SQLite database
- **Push**: Push local changes (estimates, status, stage) back to Sphere
- **Conflict Detection**: Version tracking to detect conflicts between local and Sphere data
- **Audit Logging**: Complete audit trail of all sync operations
- **HTTP API**: REST endpoints for integration with CI/CD and other services
- **CLI**: Command-line interface for manual operations

## Environment Variables

Required variables in `.env`:

```bash
# Sphere (Bitrix24) webhook configuration
B24_WEBHOOK_URL=https://sphere.loodsen.ru/rest/123/abc123/
BASE_URL=https://sphere.loodsen.ru

# Enable write operations for MCP tools
MCP_WRITE_ENABLED=true

# Optional: Database path (default: ./data/sprint-sync.db)
SPRINT_SYNC_DB_PATH=./data/sprint-sync.db

# Optional: API server port (default: 3000)
SPRINT_SYNC_PORT=3000
```

## Database Schema

### sprint_task
- `task_id`: Sphere task ID
- `title`, `description`: Task details
- `status`, `stage_id`, `priority`: Task state
- `tag`: Sprint tag (e.g., "Спринт 49")
- `time_estimate`, `time_spent`: Time tracking
- `sphere_version`: Version from Sphere for conflict detection
- `local_version`: Local version for conflict detection

### sync_state
- `tag`: Sprint tag
- `last_pull_at`, `last_push_at`: Sync timestamps
- `last_sync_hash`: Hash of all tasks for change detection
- `status`: Current sync state (idle/pulling/pushing/conflict)

### audit_log
- `task_id`: Sphere task ID
- `action`: Action performed (pull/push/conflict/update_estimate/etc.)
- `old_value`, `new_value`: State changes
- `sphere_request_id`: MCP request ID for debugging
- `error_message`: Error details if action failed

## CLI Usage

### Pull tasks from Sphere

```bash
# Pull all tasks for sprint tag
npm run sprint-sync:pull -- --tag "Спринт 49"

# Dry run to see what would be pulled
npm run sprint-sync:pull -- --tag "Спринт 49" --dry-run
```

### Push changes to Sphere

```bash
# Push all local changes for sprint tag
npm run sprint-sync:push -- --tag "Спринт 49"

# Push specific tasks only
npm run sprint-sync:push -- --tag "Спринт 49" --task-ids "123456" "123457"

# Dry run to see what would be pushed
npm run sprint-sync:push -- --tag "Спринт 49" --dry-run
```

### Check sync status

```bash
# Show status for specific sprint
npm run sprint-sync:status -- --tag "Спринт 49"

# Show general status
npm run sprint-sync:status
```

### View audit logs

```bash
# Show recent logs
npm run sprint-sync:logs

# Show logs for specific task
npm run sprint-sync:logs -- --task-id "123456"

# Show only error logs
npm run sprint-sync:logs -- --errors

# Limit number of logs
npm run sprint-sync:logs -- --limit 20
```

### Update task estimate locally

```bash
# Update estimate (in seconds)
npm run sprint-sync:pull -- update-estimate --task-id "123456" --estimate 3600
```

## HTTP API

### Start API server

```bash
# Start development server
npm run sprint-sync:dev

# Start with custom port
SPRINT_SYNC_PORT=8080 npm run sprint-sync:dev
```

### API Endpoints

#### GET /api/sprint/snapshot
Get current local task snapshot.

**Query Parameters:**
- `tag` (optional): Filter by sprint tag

**Response:**
```json
{
  "success": true,
  "data": {
    "tasks": [...],
    "count": 42,
    "tag": "Спринт 49",
    "generated_at": "2026-08-12T12:00:00.000Z"
  }
}
```

#### POST /api/sprint/sync/pull
Pull tasks from Sphere into local database.

**Request Body:**
```json
{
  "tag": "Спринт 49"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "pulled": 15,
    "tag": "Спринт 49",
    "tasks": [...],
    "sync_hash": "abc123...",
    "pulled_at": "2026-08-12T12:00:00.000Z"
  }
}
```

#### POST /api/sprint/sync/push
Push local changes to Sphere.

**Request Body:**
```json
{
  "tag": "Спринт 49",
  "task_ids": ["123456", "123457"] // optional, pushes all if not specified
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "pushed": 5,
    "errors": 0,
    "tag": "Спринт 49",
    "results": [...],
    "pushed_at": "2026-08-12T12:00:00.000Z"
  }
}
```

#### GET /api/sync/state
Get current sync state.

**Query Parameters:**
- `tag` (optional): Filter by sprint tag

**Response:**
```json
{
  "success": true,
  "data": {
    "state": {
      "tag": "Спринт 49",
      "status": "idle",
      "last_pull_at": "2026-08-12T10:00:00.000Z",
      "last_push_at": "2026-08-12T11:00:00.000Z",
      "last_sync_hash": "abc123..."
    }
  }
}
```

#### GET /api/audit/logs
Get audit logs.

**Query Parameters:**
- `task_id` (optional): Filter by task ID
- `limit` (optional, default 100): Number of logs to return

**Response:**
```json
{
  "success": true,
  "data": {
    "logs": [...],
    "count": 50,
    "task_filter": "all"
  }
}
```

#### GET /health
Health check endpoint.

**Response:**
```json
{
  "status": "ok",
  "service": "sprint-sync",
  "timestamp": "2026-08-12T12:00:00.000Z"
}
```

## Integration with CI/CD

### Example: Pull tasks before sprint planning

```bash
#!/bin/bash
# pull-sprint-tasks.sh

SPRINT_TAG="Спринт 49"

# Pull latest tasks from Sphere
npm run sprint-sync:pull -- --tag "$SPRINT_TAG"

# Check sync status
npm run sprint-sync:status -- --tag "$SPRINT_TAG"

echo "Sprint tasks pulled successfully"
```

### Example: Push estimates after planning

```bash
#!/bin/bash
# push-estimates.sh

SPRINT_TAG="Спринт 49"

# Push local changes to Sphere
npm run sprint-sync:push -- --tag "$SPRINT_TAG"

# Check for errors
npm run sprint-sync:logs -- --errors

echo "Estimates pushed successfully"
```

## Conflict Resolution

The service uses version tracking to detect conflicts:

1. **sphere_version**: Derived from Sphere task's changed_date, status, and stage_id
2. **local_version**: Incremented with each local modification

When both versions change independently, a conflict is logged in `audit_log` with action `conflict`.

**Conflict Detection Flow:**
- Pull: Compares incoming sphere_version with local sphere_version
- Push: Checks if local_version > 1 (indicates local changes)
- Update: Logs conflict if both local and sphere versions have changed

**Manual Conflict Resolution:**
1. Check audit logs: `npm run sprint-sync:logs -- --errors`
2. Compare local and Sphere versions
3. Decide which version to keep
4. Force re-sync by incrementing versions or manual intervention

## Error Handling

All MCP errors are logged with `request_id` for debugging:

```bash
# View error logs
npm run sprint-sync:logs -- --errors

# View logs for specific task
npm run sprint-sync:logs -- --task-id "123456"
```

Error responses include:
- `error_message`: Human-readable error description
- `sphere_request_id`: Unique identifier for debugging in Sphere logs

## Development

### Running locally

```bash
# Install dependencies
npm install

# Run type checking
npm run typecheck

# Run linting
npm run lint

# Start development server
npm run sprint-sync:dev
```

### Testing with specific sprint tag

```bash
# Pull tasks for "Спринт 49"
npm run sprint-sync:pull -- --tag "Спринт 49"

# Check what was pulled
npm run sprint-sync:status -- --tag "Спринт 49"

# View audit logs
npm run sprint-sync:logs
```

## Architecture

```
┌─────────────┐     Pull      ┌──────────────┐     MCP     ┌─────────────┐
│  HTTP API   │ ─────────────▶│ Local SQLite │ ───────────▶│  Sphere API │
│   / CLI     │               │   Database   │             │  (Bitrix24) │
└─────────────┘     Push      └──────────────┘     MCP     └─────────────┘
                            │
                            ▼
                      ┌──────────────┐
                      │ Audit Logs   │
                      │ Conflict     │
                      │ Detection    │
                      └──────────────┘
```

**Key Components:**
- **db-schema.ts**: Database schema and initialization
- **db-operations.ts**: Repository pattern for database operations
- **api-server.ts**: Express HTTP server with REST endpoints
- **sync-cli.ts**: CLI commands for manual operations
- **b24-client.ts**: Sphere API client with estimate/status update methods

## Troubleshooting

### Database locked error
```bash
# Ensure only one process is accessing the database
# Check running processes
lsof | grep sprint-sync.db
```

### MCP write operations disabled
```bash
# Enable write operations in .env
echo "MCP_WRITE_ENABLED=true" >> .env
```

### Tasks not pulling
```bash
# Check network connectivity
npm run fetch-my-tasks-api

# Verify tag spelling
npm run sprint-sync:pull -- --tag "Спринт 49" --dry-run
```

### Sync state stuck
```bash
# Reset sync state
# (Requires manual database intervention or API endpoint)
```

## License

Part of sphere-integration project. See main project LICENSE for details.