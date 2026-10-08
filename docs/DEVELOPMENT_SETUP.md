# Local Development Setup (Docker Compose)

This guide documents how to set up, run, and manage the Atlas AI local development environment using Docker Compose.

---

## 1. Prerequisites

Before starting, ensure the following software is installed on your host system:

- **Docker Desktop**: Version 20.10+ (Docker Engine with Docker Compose v2+). Ensure the Docker daemon is running.
- **Python**: 3.14.x (Constraint: `>=3.14,<3.15`) for local Python operations.
- **uv**: Fast Python package and project manager.
  - Install following the official Astral documentation (e.g., using the standalone installer: https://docs.astral.sh/uv/getting-started/installation/).

---

## 2. Environment Configuration

Atlas AI uses environment variables for service configuration. A template file [`.env.example`](file:///d:/Atlas%20AI/.env.example) is committed to the repository.

### Creating your `.env` file

Copy [`.env.example`](file:///d:/Atlas%20AI/.env.example) to `.env` in the root workspace directory:

**Linux / macOS / PowerShell:**
```bash
cp .env.example .env
```

**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

**Windows (Command Prompt):**
```cmd
copy .env.example .env
```

### Environment Variables

| Variable | Description | Default (Local Dev) |
|---|---|---|
| `NEO4J_URI` | Bolt connection URI used by backend | `bolt://neo4j:7687` |
| `NEO4J_USERNAME` | Neo4j database user | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j database password | `password` |

> [!IMPORTANT]
> The `.env` file contains local secrets and is explicitly ignored by Git. Never commit `.env` or hard-code real credentials into tracked repository files.

---

## 3. Starting the Environment

To build and start all development services, run:

```bash
docker compose up --build
```

To run the services in the background (detached mode):

```bash
docker compose up --build -d
```

### What Docker Compose Does:
1. Builds the **`backend`** service container using the `python:3.14-slim` base image, syncing dependencies using `uv` from [`backend/uv.lock`](file:///d:/Atlas%20AI/backend/uv.lock).
2. Pulls and launches the **`neo4j`** service using image `neo4j:2026.09.0`.
3. Attaches the persistent named volume `neo4j_data` to `/data`.
4. Executes the Neo4j healthcheck (`http://localhost:7474`).
5. Once Neo4j reports healthy, the backend service starts and verifies Bolt connectivity to `bolt://neo4j:7687`.

---

## 4. Stopping the Environment

To stop running containers while **preserving** your database data:

```bash
docker compose down
```

This stops and removes the containers and the default network, leaving the named volume `neo4j_data` intact.

---

## 5. Neo4j Data Persistence

Data stored in Neo4j is persisted using a named Docker volume:

- **Named Volume**: `neo4j_data`
- **Container Mount Path**: `/data`

When you restart services using `docker compose down` followed by `docker compose up`, all stored graphs, nodes, and relationships remain preserved.

---

## 6. Completely Resetting Local Neo4j Data

If you need a clean slate and wish to completely delete all local Neo4j database records and schemas, run:

```bash
docker compose down -v
```

> [!WARNING]
> The `-v` (`--volumes`) flag deletes all attached named volumes (including `neo4j_data`). On next startup, Neo4j will initialize an empty database with default credentials.

### Distinction: `down` vs `down -v`

- `docker compose down`: Preserves stored Neo4j data volumes across development sessions.
- `docker compose down -v`: Destroys all stored database volumes for a full factory reset.

---

## 7. Accessing Neo4j Browser

The Neo4j Browser web interface is exposed to your host machine:

- **URL**: [http://localhost:7474](http://localhost:7474)
- **Connect URL / Bolt URL**: `bolt://localhost:7687` (or `neo4j://localhost:7687`)
- **Username**: Value of `NEO4J_USERNAME` in `.env` (default: `neo4j`)
- **Password**: Value of `NEO4J_PASSWORD` in `.env` (default: `password`)

---

## 8. Backend-to-Neo4j Connection & Verification

Inside the Docker network:
- The backend communicates with Neo4j using the service hostname **`neo4j`** on Bolt port **`7687`**:
  ```text
  bolt://neo4j:7687
  ```
- Container-to-container communication must **not** use `localhost:7687`.
- On startup, the backend lifespan handler calls `driver.verify_connectivity()` and runs a Cypher ping (`RETURN 1 AS ping`).
- To manually run a deterministic verification check from inside the backend container:
  ```bash
  docker compose exec backend python -m app.verify_neo4j
  ```

---

## 9. Troubleshooting & FAQ

### Docker Daemon Not Running
If you receive `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`:
- Ensure Docker Desktop is launched and running.
- In PowerShell, verify with: `docker info`.

### Port Already in Use
If ports `7474`, `7687`, or `8000` are already bound by another local process:
- Check running processes using `Get-NetTCPConnection -LocalPort 7474` (Windows) or `lsof -i :7474` (Linux/macOS).
- Stop conflicting local database or server instances.

### Authentication Failures
If you changed `NEO4J_PASSWORD` in `.env` after Neo4j had already initialized:
- Neo4j persists its initial authentication credentials in the volume.
- To apply new credentials, wipe the volume with `docker compose down -v` and restart.
