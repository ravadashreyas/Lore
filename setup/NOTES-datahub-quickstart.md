# DataHub OSS Quickstart: Local Setup Notes (Windows)

Recorded 2026-07-29. Factual notes only: versions, ports, auth, commands that worked.

## Versions

- **DataHub server**: `v1.5.0.6` (confirmed via `GET http://localhost:8080/config` -> `versions.acryldata/datahub.version`)
- **DataHub CLI (`acryl-datahub`)**: `1.6.0.16` (confirmed via `datahub version`)
- **uv**: `0.11.32`
- Note: CLI version (1.6.0.16) and server version (v1.5.0.6) differ. This is expected/normal; the CLI's `docker quickstart` command pins its own known-good compose/server tag independent of the CLI's own package version. Do not assume they need to match.

## Install commands that worked

```
# uv was installed via winget but not on PATH in this shell session; used full path:
UV=/c/Users/Shreyas/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe/uv.exe
"$UV" tool install acryl-datahub
# -> installs `datahub` to C:\Users\Shreyas\.local\bin\datahub.exe

export PATH="/c/Users/Shreyas/.local/bin:$PATH"
datahub version
datahub docker quickstart
```

Total quickstart time from a cold start (no cached images): ~7 minutes (image pulls ~5 min, container startup/health ~2 min) on Docker Desktop 29.5.3 / 64GB RAM.

## Containers running (docker compose project `datahub`)

| Container | Image | Status | Ports |
|---|---|---|---|
| `datahub-datahub-gms-quickstart-1` | `acryldata/datahub-gms:v1.5.0.6` | healthy | `8080:8080` |
| `datahub-frontend-quickstart-1` | `acryldata/datahub-frontend-react:v1.5.0.6` | healthy | `9002:9002` |
| `datahub-datahub-actions-quickstart-1` | `acryldata/datahub-actions:v1.5.0.6-slim` | up (no health probe defined) | — |
| `datahub-system-update-quickstart-1` | `acryldata/datahub-upgrade:v1.5.0.6` | **exited (0)** | — |
| `datahub-kafka-broker-1` | `confluentinc/cp-kafka:8.0.0` | healthy | `9092:9092` |
| `datahub-mysql-1` | `mysql:8.2` | healthy | `3306:3306` |
| `datahub-opensearch-1` | `opensearchproject/opensearch:2.19.3` | healthy | `9200:9200` |

`datahub-system-update-quickstart-1` exiting with code 0 is correct: it's a one-shot DB/index migration job that runs to completion, not a long-lived service.

Pre-existing, unrelated containers on this machine (left untouched, not part of DataHub): `dhmem-demo-postgres` (port 5434, this project's Postgres demo warehouse from a parallel session), `specforge-dev-postgres` (5433), `specforge-sandbox-docker-task`.

## Health verification

- `GET http://localhost:9002` -> **HTTP 200** (UI up)
- `GET http://localhost:8080/health` -> **HTTP 200**
- `GET http://localhost:8080/config` -> **HTTP 200**, confirms server version `v1.5.0.6`, `serverType: quickstart`
- `POST http://localhost:8080/api/graphql` with `{ me { corpUser { username } } }` (no auth header) -> **HTTP 200**, `{"data":{"me":{"corpUser":{"username":"__datahub_system"}}}}`
- `POST http://localhost:8080/api/graphql` with a `search` query (no auth header) -> **HTTP 200**, `{"total":0}` (expected: nothing ingested yet, fresh quickstart)

## Auth status

- **Direct GMS API (port 8080) has no authentication enforced by default in this quickstart.** Unauthenticated GraphQL queries and searches against `http://localhost:8080/api/graphql` succeed and are attributed to the system actor `__datahub_system`. This means the DataHub SDK / MCP server can talk to GMS at `localhost:8080` with **no token required** for local dev.
- **Frontend proxy (port 9002) requires a session.** `POST http://localhost:9002/api/graphql` without a session cookie returns **HTTP 401**. `POST http://localhost:9002/entities?action=search`-style direct GMS calls without an `Authorization` header return 400 (missing required params), not 401. GMS itself just doesn't gate on auth.
- **Default UI login**: `datahub` / `datahub` (unchanged from quickstart defaults). Verified via `POST http://localhost:9002/logIn` with `{"username":"datahub","password":"datahub"}` -> HTTP 200, sets `PLAY_SESSION` + `actor` cookies.
- **Personal Access Token (PAT) generation works non-interactively** once logged in: with the session cookie, `POST http://localhost:9002/api/graphql` with mutation
  ```graphql
  mutation { createAccessToken(input: {type: PERSONAL, actorUrn: "urn:li:corpuser:datahub", duration: ONE_MONTH, name: "some-name"}) { accessToken } }
  ```
  returns a JWT `accessToken`. **Gotcha**: immediately after `docker quickstart` finishes, this mutation returned `403 UNAUTHORIZED` ("Unauthorized to perform this action"). The default access-control policies (seeded by the `system-update` container) hadn't finished propagating to the authorizer's policy cache yet. Retrying ~1 minute later succeeded. If a PAT is needed for MCP-server or SDK config, wait a minute after quickstart reports containers healthy before generating one, or retry on 403.
- No token was persisted to any file in this repo (tokens are secrets; regenerate as needed via the mutation above).

## Windows-specific quirks hit and fixes

1. **`uv` not on PATH right after winget install.** Fixed by calling the full path: `C:\Users\Shreyas\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe`. `uv tool install` places the `datahub` shim at `C:\Users\Shreyas\.local\bin\datahub.exe`; add that to PATH for future sessions rather than the WinGet package dir.
2. **`datahub docker quickstart` exits with code 1 / prints a Python traceback on Windows even on full success.** Root cause: the CLI's final success banner does `click.secho("\u2714 DataHub is now running", fg="green")`, and the Windows console's default codepage (`cp1252`) can't encode the `✔` (U+2714) character, raising `UnicodeEncodeError` in `click`'s echo. This happens *after* all containers are already confirmed healthy in the compose output. It is a cosmetic failure in the final print statement, not an infrastructure failure. **Verify success by checking `docker ps` / hitting the health endpoints, not by trusting the CLI's own exit code on Windows.** Workaround for a clean exit: run with `PYTHONIOENCODING=utf-8` set, or `chcp 65001` in the shell before invoking `datahub`, to let the console accept UTF-8 output.

## Commands to bring it back up / tear down (not run as part of this task)

```
datahub docker quickstart          # idempotent, reuses existing containers/volumes if present
datahub docker quickstart --stop   # stop without deleting data
datahub docker nuke                # full teardown incl. volumes (destructive, not used here)
```

## Ingestion

Recorded 2026-07-29.

- **Recipe**: `setup/ingest_postgres.yml`, a postgres source (`localhost:5434`, db `demo_warehouse`, schema_pattern allow `ecommerce`, table-level metadata + schemas), `datahub-rest` sink to `http://localhost:8080`. Profiling left off: a one-line flag exists (`profiling.enabled: true`) but it runs per-table/per-column stats queries for no payoff in this project (nothing reads profiling stats), so skipped rather than adding runtime for nothing.
- **Command that worked**:
  ```
  PYTHONIOENCODING=utf-8 uvx --from "acryl-datahub[postgres]==1.6.0.16" datahub ingest -c setup/ingest_postgres.yml
  ```
  (`uvx` not on PATH in this shell; used full path `$LOCALAPPDATA\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uvx.exe`.)
- **Fix applied during setup**: initial recipe included `include_table_lineage: false` under the postgres source config, rejected by pydantic validation (`Extra inputs are not permitted`; that field isn't part of `PostgresConfig`). Removed it; ingestion then ran clean with `tables_scanned: 3`, 0 failures, 25 events written (containers: 1 Database + 1 Schema; datasets: 3 Tables, each with `schemaMetadata`, `datasetProperties`, `container`, `status`, `subTypes`, `browsePathsV2`).
- **Verified via GraphQL** against `http://localhost:8080/api/graphql` (unauthenticated), both `search(type: DATASET, query: "fct_orders")` and `search(type: DATASET, query: "demo_warehouse")` (total 3), plus a `dataset(urn: ...) { schemaMetadata { fields { ... } } }` lookup per dataset.
- **Exact urns** (match the expected form exactly: no case or db-name deviations):
  - `urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.fct_orders,PROD)`: 6 fields: `order_id` (INTEGER), `customer_key` (INTEGER), `product_id` (INTEGER), `amount` (BIGINT), `status` (TEXT), `order_date` (DATE)
  - `urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.dim_customers,PROD)`: 5 fields: `customer_key` (INTEGER), `customer_id` (INTEGER), `name` (TEXT), `segment` (TEXT), `region` (TEXT)
  - `urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.dim_products,PROD)`: 4 fields: `product_id` (INTEGER), `product_name` (TEXT), `product_line` (TEXT), `unit_cost_cents` (BIGINT)
