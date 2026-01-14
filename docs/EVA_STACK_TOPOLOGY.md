# EVA Stack Topology

## Overview
Two independent Docker Compose stacks running the EVA platform:
- **eva-finance**: Core ingestion and signal processing
- **eva-security**: API gateway and security monitoring

Each stack runs on its own isolated Docker network with no shared internal DNS.

## EVA-Finance Stack
**Location**: `~/projects/eva-finance/docker-compose.yml` | **Network**: `eva_net`

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| eva-api | eva_api | 9080 | FastAPI ingestion endpoint (`/intake/message`) |
| eva-worker | eva_worker | - | Background signal processing |
| db | eva_db | 5432 | PostgreSQL (internal) |
| metabase | eva_metabase | 3000 | Analytics dashboard |
| ntfy | eva_ntfy | 8085 | Notifications |

## EVA-Security Stack
**Location**: `~/eva-platform/eva-security/docker-compose.yml` | **Network**: `eva_security_net`

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| api-gateway | eva-api-gateway | 8300 | Auth/rate limiting proxy |
| sentinel | eva-sentinel | 8200, 8501 | Security monitoring |
| apex-postgres | eva-apex-postgres | 5432 | Security DB (localhost) |
| apex-chromadb | eva-apex-chromadb | 8100 | Vector store (localhost) |
| apex-ollama | eva-apex-ollama | 11434 | LLM service (localhost) |

## Network Isolation

**Critical**: Stacks use **separate Docker networks** with **no shared internal DNS**.
External services (like n8n) must use **host IP** to communicate across stacks.

## Port Map

| Port | Service | Stack | Access | Notes |
|------|---------|-------|--------|-------|
| 9080 | eva_api | Finance | 0.0.0.0 | **n8n ingestion endpoint** |
| 8300 | eva-api-gateway | Security | 127.0.0.1 | Authenticated API access |
| 5432 | eva-apex-postgres | Security | 127.0.0.1 | Security DB |
| 5678 | n8n | External | 0.0.0.0 | Workflow UI |
| 3000 | eva_metabase | Finance | 0.0.0.0 | Analytics dashboard |
| 8085 | eva_ntfy | Finance | 0.0.0.0 | Notifications |
| 8200 | eva-sentinel | Security | 127.0.0.1 | Sentinel API |
| 8501 | eva-sentinel | Security | 127.0.0.1 | Streamlit dashboard |

## Dependency Chain

```
n8n (external)
  ↓ HTTP POST to 10.10.0.210:9080/intake/message
eva_api (finance stack)
  ↓ SQL INSERT
eva_db (finance stack)
  ↑ SQL SELECT (polling)
eva_worker (finance stack)
  → ntfy notifications
```

## N8N Integration

**Endpoint**: `http://10.10.0.210:9080/intake/message`

n8n uses the **host IP address** (10.10.0.210) because:
1. n8n runs in a separate Docker network
2. Cannot use internal service name `eva_api` (different network)
3. Port 9080 is exposed to all interfaces (`0.0.0.0:9080`)

**Common Mistake**: Pointing n8n at eva-api-gateway (port 8300) instead of eva_api (port 9080). These are different services in different stacks.

## Health Checks

Run: `~/bin/eva-status` to show all containers, ports, and critical endpoint status.

## Restart Behavior

All services: `restart: unless-stopped` (auto-restart on failure, survives reboots)

## Troubleshooting

**n8n ECONNREFUSED on port 9080**:
1. Check if eva_api is running: `docker ps | grep eva_api`
2. If not running: `cd ~/projects/eva-finance && docker compose up -d eva-api`
3. Verify endpoint: `curl http://10.10.0.210:9080/health`

**Wrong service responding**:
- Port 9080 = eva_api (FastAPI with `/intake/message`)
- Port 8300 = eva-api-gateway (different service, no `/intake/message` route)
