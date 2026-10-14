# Production package and local rehearsal

`deploy/compose.yaml` is a separate stack from the developer Compose file. It runs a built Python image for the API and workers, and a built React/Caddy image for the web gateway. Kafka, PostgreSQL, Prometheus and Grafana run inside the Docker network. Only the gateway publishes host ports. The application and gateway run as UID 10001 with read-only root filesystems; named volumes retain the state that must survive container replacement.

This increment prepares and tests the package locally. No VM or public domain has been configured. Image publication, approved deployment and rollback automation are the next increment.

## Rehearse with one command

Start Docker Desktop with Linux containers, then from the repository root run:

```powershell
python scripts/rehearse_deployment.py
```

The script needs Python 3.12 or later and Docker Compose v2. It creates a unique Compose project, temporary credentials, an internal certificate authority and random loopback ports. It builds both images, initializes the Kafka topics and applies migrations before starting the API and processor. Upstream workers are excluded so it never waits for a real earthquake.

The checks verify:

- Healthy startup, an unprivileged application/gateway, and host ports published only by the gateway.
- HTTPS hostname/certificate verification using the exported rehearsal CA, HTTP-to-HTTPS redirection, the built React shell, and the API readiness route.
- Private API metrics and documentation paths; missing or incorrect Grafana gateway credentials rejected with 401; a separate Grafana login still required after the gateway accepts credentials.
- Captured events published into Kafka and read through the HTTPS API; a committed revision delivered through the HTTPS SSE connection.
- Container removal and recreation with volumes preserved: two events remain, the change cursor remains 3, the original TLS CA still works, and a replay adds no duplicate or change cursor.
- A binary `pg_dump` archive restored into a new database, with matching event IDs, magnitudes, change cursors and migration version.
- Prometheus scrapes the API over the Docker network.

The script removes only its own unique project's containers and volumes and its verified temporary directory. A successful report remains in the ignored `deploy/.rehearsal/last-report.json`. It leaves developer data untouched. CI runs the same script in the `containers` check.

The web rehearsal checks the generated React shell and assets rather than running a browser. The separate existing Playwright check exercises event selection and live notices. Neither check validates Mapbox tiles or a real upstream notification.

## Configuration for a VM

The systemd templates assume a Linux VM with Docker Engine, Compose v2, Python 3.12+, and the repository/configuration in `/opt/seismic`. Resolve the real OS, architecture, storage, domain and resource budget before deployment. This is a single-host setup: replication factor 1 does not protect against loss of the VM or its disk.

Copy `deploy/.env.example` to `deploy/.env`. For a public deployment, set:

```dotenv
APP_DOMAIN=seismic.example.com
GRAFANA_DOMAIN=grafana.example.com
TLS_ISSUER=your-acme-contact@example.com
BIND_ADDRESS=0.0.0.0
HTTP_PORT=80
HTTPS_PORT=443
```

Point both DNS names to the VM. Permit inbound TCP 80/443 and restrict SSH to the intended administrators. Caddy listens on unprivileged ports 8080/8443 inside its container and obtains/renews public certificates when configured with an ACME email. The rehearsal instead uses `TLS_ISSUER=internal`; that CA is trusted only by the test and is never installed in the host's trust store. See [Caddy TLS configuration](https://caddyserver.com/docs/caddyfile/directives/tls) and [internal port mapping](https://caddyserver.com/docs/caddyfile/options#http_port).

Use a URL-restricted **public** Mapbox token for `VITE_MAPBOX_ACCESS_TOKEN`. It is compiled into the frontend image and visible to visitors. Changing it requires rebuilding that image. Database and Grafana passwords never belong in this build argument or the image.

Create the five secret files listed in `deploy/.env.example`:

- `postgres_password`: a strong randomly generated password for the `seismic` application role.
- `postgres_admin_password`: a different random password for the `seismic_admin` bootstrap administrator, mounted only into PostgreSQL.
- `grafana_admin_password`: a different strong password for Grafana's `admin` account.
- `grafana_secret_key`: a stable random key for Grafana's stored secrets.
- `grafana_gateway_auth`: a Caddy `basic_auth` block containing a username and bcrypt password hash.

To generate the gateway hash interactively after building the web image:

```sh
docker run --rm -it --entrypoint caddy seismic-web:local hash-password --algorithm bcrypt
```

Save the returned hash in `deploy/secrets/grafana_gateway_auth`:

```caddyfile
basic_auth {
    observer REPLACE_WITH_THE_GENERATED_HASH
}
```

Keep the host secret directory private to its owner (`chmod 700 deploy/secrets` on Linux). The mounted files must be readable by the corresponding container users: the rehearsal uses mode 644 files inside that private directory. With file-backed Compose secrets, host file permissions apply; changing a Compose `uid` field does not change a bind-mounted file's ownership. Keep the directory, environment file, dumps and Caddy private keys out of Git. See [Docker Compose secret mounting](https://docs.docker.com/compose/how-tos/use-secrets/).

Grafana asks for the gateway credentials first and its own login afterward. Caddy strips the gateway `Authorization` header before proxying to Grafana. Anonymous access and self-registration are disabled. The gateway password is independent of the Grafana admin password.

On a fresh PostgreSQL volume, the initialization script creates `seismic` as a database owner with no superuser, database creation or role creation privileges. Application containers receive only that role's password. Migrations, API and workers currently share this application role; separate read-only/API and migration roles can further narrow permissions later. Host backup/restore tools use the administrator through PostgreSQL's local container socket.

For a first manual build and startup:

```sh
docker compose --env-file deploy/.env -p seismic-production -f deploy/compose.yaml build api web
docker compose --env-file deploy/.env -p seismic-production -f deploy/compose.yaml --profile live up -d --wait
```

The `live` profile enables both EMSC workers. Their container health checks use process liveness; Prometheus readiness and feed metrics show source/dependency availability separately. Core API/processor health checks use readiness. Container health does not itself restart an unhealthy process; `restart: unless-stopped` restarts an exited process. Source workers have application retry loops, and the processor exits on a dependency/write failure so Docker can restart it without advancing an unsuccessful record's offset. On SIGTERM the processor finishes its current record and closes its consumer.

After building/pulling the expected images, install the templates from `deploy/systemd/` in `/etc/systemd/system/`, run `systemctl daemon-reload`, and enable `seismic-platform.service`. That unit uses `--no-build` so VM startup uses the selected image. The eventual release workflow will set `BACKEND_IMAGE` and `WEB_IMAGE` to tested immutable image digests.

The internal network uses plaintext Kafka/PostgreSQL connections and must remain inside the trusted host. Prometheus, worker metrics, the database and Kafka have no host port mappings. To debug, use `docker compose exec` or an SSH session. Do not add public mappings for them.

## Persistence and backups

Named volumes retain Kafka data and offsets, PostgreSQL rows/checkpoints, Prometheus samples, Grafana state, and Caddy's certificates/configuration. `docker compose down` preserves these volumes. `down --volumes` deletes them and must never be used for a routine production update.

Kafka retains events for up to seven days, also bounded by 1 GiB per partition; a consumer stopped beyond retention can lose unprocessed records. Prometheus retains metrics for up to 15 days or 1 GiB. These bounds are starting configuration values to review against observed traffic and disk usage. Resource limits and rotating Docker logs also bound the stack; the rehearsal is not a load/capacity test.

Create a database backup from the repository root:

```sh
python3 scripts/database_backup.py --env-file deploy/.env --project seismic-production backup --directory /var/backups/seismic
```

The tool uses a binary stream to preserve the custom-format archive on Windows and Linux, creates each output exclusively, and refuses to overwrite existing dumps. A failed dump removes its incomplete output. PostgreSQL's logical dump is a consistent database snapshot; it does not back up Kafka offsets, broker logs, Grafana, certificates or host configuration. See [PostgreSQL SQL dumps](https://www.postgresql.org/docs/18/backup-dump.html).

Install and enable `seismic-backup.timer` for a daily backup at 02:15 UTC, with a short randomized delay and catch-up after downtime. Inspect `systemctl list-timers` and the backup service journal. Dumps are private files and are ignored by Git. The timer creates local snapshots; copying them to encrypted storage outside the VM and setting a retention policy must be configured before a real deployment. A disk failure can destroy local volumes and local backups together. No external backup destination or failure notification receiver exists yet.

Practice restoration into a **new** database:

```sh
python3 scripts/database_backup.py --env-file deploy/.env --project seismic-production restore /var/backups/seismic/ARCHIVE.dump --database seismic_restore_check
docker compose --env-file deploy/.env -p seismic-production -f deploy/compose.yaml exec -T postgres psql -U seismic_admin -d seismic_restore_check -c 'SELECT count(*) FROM earthquake_events'
```

The tool refuses the running `seismic` database and existing targets, and never drops databases. If restore fails, inspect the partially restored new database before deciding what to remove. A validated restoration is the evidence of a usable backup; the local rehearsal compares the restored rows/cursor/schema to the source. Real disaster recovery needs a controlled maintenance window, an image compatible with the restored schema, and a Kafka offset/replay decision. Do not simply point a running processor at an older snapshot: its newer committed offsets can skip events missing from that snapshot.

The restored test database uses administrator ownership and omits original grants. Before a real cutover, recreate the intended role ownership/permissions and verify application reads and writes against the restored database. The automated comparison verifies the archive's contents rather than switching running services to that database.

Database passwords and Grafana bootstrap admin credentials initialize fresh volumes. Editing their secret files does not rotate credentials already stored in an existing database. Plan and execute credential rotation inside the service before replacing the corresponding file. Keep Grafana's encryption key stable and retain the production Caddy data volume.

## Remaining deployment work

The local package and recovery rehearsal precede selecting a VM, configuring public DNS/ACME, external backups and alert delivery, and approved GitHub deployment/rollback. Schema migrations run before the API in this package; reverting an image does not reverse a migration. Future changes must preserve compatibility or provide an explicit recovery procedure. Keep image rollback and data restoration as separate operations.
