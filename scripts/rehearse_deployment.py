"""Build an isolated HTTPS stack, verify recovery, then remove its test volumes."""

import base64
import http.client
import json
import secrets
import shutil
import socket
import ssl
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from database_backup import backup, restore
from deployment_support import ROOT, Compose

APP = "seismic.localhost"
GRAFANA = "grafana.localhost"


class LocalHTTPS(http.client.HTTPSConnection):
    """Connect to loopback while verifying the actual site's TLS hostname."""

    def __init__(
        self, host: str, port: int, *, context: ssl.SSLContext, timeout: int
    ) -> None:
        super().__init__(host, port, context=context, timeout=timeout)
        self.ssl_context = context

    def connect(self) -> None:
        transport = socket.create_connection(("127.0.0.1", self.port), self.timeout)
        self.sock = self.ssl_context.wrap_socket(transport, server_hostname=self.host)


def wait_for(check: Callable[[], bool], message: str, timeout: int = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return
        time.sleep(1)
    raise RuntimeError(message)


def main() -> None:
    rehearsal_root = ROOT / "deploy" / ".rehearsal"
    rehearsal_root.mkdir(exist_ok=True, mode=0o700)
    work = rehearsal_root / f"run-{secrets.token_hex(6)}"
    work.mkdir(mode=0o700)
    project = f"seismic-rehearsal-{secrets.token_hex(6)}"
    compose = Compose(work / "rehearsal.env", project)
    started = False
    evidence = []

    def record(message: str) -> None:
        evidence.append(message)
        print(f"PASS: {message}", flush=True)

    def secret_file(name: str, content: str) -> Path:
        path = work / name
        path.write_text(content, encoding="utf-8")
        # Mounted secrets must be readable by the unprivileged containers; the
        # parent directory is private to the host owner.
        path.chmod(0o644)
        return path

    try:
        print(
            "Preparing private rehearsal credentials and building images...", flush=True
        )
        caddy_image = next(
            line.split()[1]
            for line in (ROOT / "frontend" / "Dockerfile").read_text().splitlines()
            if line.startswith("FROM caddy:")
        )
        gateway_password = secrets.token_urlsafe(32)
        hashed = (
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-i",
                    "--entrypoint",
                    "caddy",
                    caddy_image,
                    "hash-password",
                    "--algorithm",
                    "bcrypt",
                ],
                input=(gateway_password + "\n").encode(),
                stdout=subprocess.PIPE,
                check=True,
                timeout=180,
            )
            .stdout.decode()
            .strip()
        )
        values = {
            "APP_DOMAIN": APP,
            "GRAFANA_DOMAIN": GRAFANA,
            "TLS_ISSUER": "internal",
            "BIND_ADDRESS": "127.0.0.1",
            "HTTP_PORT": "0",
            "HTTPS_PORT": "0",
            "BACKEND_IMAGE": "seismic-backend:rehearsal",
            "WEB_IMAGE": "seismic-web:rehearsal",
            "VITE_MAPBOX_ACCESS_TOKEN": "",
            "POSTGRES_PASSWORD_FILE": secret_file(
                "postgres_password", secrets.token_urlsafe(32) + "@:'%"
            ).as_posix(),
            "POSTGRES_ADMIN_PASSWORD_FILE": secret_file(
                "postgres_admin_password", secrets.token_urlsafe(32)
            ).as_posix(),
            "GRAFANA_ADMIN_PASSWORD_FILE": secret_file(
                "grafana_password", secrets.token_urlsafe(32)
            ).as_posix(),
            "GRAFANA_SECRET_KEY_FILE": secret_file(
                "grafana_key", secrets.token_urlsafe(48)
            ).as_posix(),
            "GRAFANA_GATEWAY_AUTH_FILE": secret_file(
                "gateway_auth", f"basic_auth {{\n observer {hashed}\n}}\n"
            ).as_posix(),
        }
        (work / "rehearsal.env").write_text(
            "".join(f"{key}='{value}'\n" for key, value in values.items()),
            encoding="utf-8",
        )
        compose.run("config", "--quiet")
        compose.run("build", "api", "web", timeout=1200, capture=False)
        started = True
        compose.run(
            "up", "-d", "--wait", "--wait-timeout", "180", timeout=300, capture=False
        )
        record(
            "All core containers healthy; topic initialization and migrations completed"
        )
        privileges = (
            compose.run(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "seismic_admin",
                "-d",
                "seismic",
                "-Atc",
                "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = 'seismic'",
            )
            .decode()
            .strip()
        )
        assert privileges == "f|f|f"
        record(
            "Application database role has no superuser, database creation or role creation privileges"
        )
        for service in ("api", "processor", "web"):
            container = compose.run("ps", "-q", service).decode().strip()
            user = (
                subprocess.check_output(
                    ["docker", "inspect", "--format", "{{.Config.User}}", container]
                )
                .decode()
                .strip()
            )
            assert user == "10001:10001", (service, user)
        # Read each JSON line: Compose versions return NDJSON rather than an array.
        states_text = compose.run("ps", "--format", "json").decode().strip()
        states = (
            json.loads(states_text)
            if states_text.startswith("[")
            else [json.loads(line) for line in states_text.splitlines()]
        )
        assert all(
            not state.get("Publishers") for state in states if state["Service"] != "web"
        )
        record("API, processor and web run as UID 10001; only web publishes host ports")
        compose.run(
            "cp",
            "web:/data/caddy/pki/authorities/local/root.crt",
            str(work / "root.crt"),
        )
        context = ssl.create_default_context(cafile=str(work / "root.crt"))
        https_port = int(
            compose.run("port", "web", "8443").decode().strip().rsplit(":", 1)[1]
        )
        http_port = int(
            compose.run("port", "web", "8080").decode().strip().rsplit(":", 1)[1]
        )

        def request(
            path: str, host: str = APP, authorization: str | None = None
        ) -> tuple[int, bytes, dict[str, str]]:
            connection = LocalHTTPS(host, https_port, context=context, timeout=20)
            try:
                headers = {"Authorization": authorization} if authorization else {}
                connection.request("GET", path, headers=headers)
                response = connection.getresponse()
                return response.status, response.read(), dict(response.getheaders())
            finally:
                connection.close()

        redirect = http.client.HTTPConnection("127.0.0.1", http_port, timeout=5)
        redirect.request("GET", "/", headers={"Host": APP})
        response = redirect.getresponse()
        assert response.status == 308 and (
            response.getheader("Location") or ""
        ).startswith(f"https://{APP}")
        response.read()
        redirect.close()
        status, html, _ = request("/")
        assert status == 200 and b'<div id="root">' in html and b"/assets/" in html
        assert request("/ready")[0] == 200
        for private in ("/metrics", "/docs", "/openapi.json"):
            assert request(private)[0] == 404
        record(
            "Verified HTTPS certificate and HTTP redirect; built React shell and API ready; metrics/docs private"
        )
        assert request("/api/health", GRAFANA)[0] == 401
        wrong = "Basic " + base64.b64encode(b"observer:wrong").decode()
        assert request("/api/health", GRAFANA, wrong)[0] == 401
        auth = (
            "Basic "
            + base64.b64encode(f"observer:{gateway_password}".encode()).decode()
        )
        assert request("/api/health", GRAFANA, auth)[0] == 200
        assert request("/api/dashboards/uid/seismic-platform", GRAFANA, auth)[0] == 401
        record(
            "Grafana rejects missing/wrong gateway credentials and still requires its own login"
        )

        fixture = json.loads(
            (ROOT / "backend/tests/fixtures/emsc_catalogue_capture.json").read_text()
        )

        def publish(catalogue: dict[str, Any]) -> None:
            (work / "fixture.json").write_text(json.dumps(catalogue), encoding="utf-8")
            compose.run("cp", str(work / "fixture.json"), "api:/tmp/rehearsal.json")
            compose.run(
                "exec",
                "-T",
                "api",
                "python",
                "-m",
                "seismic_stream.ingestion.fixture_producer",
                "--fixture",
                "/tmp/rehearsal.json",
                "--bootstrap-server",
                "kafka:19092",
                "--ingested-at",
                "2026-10-03T17:00:00Z",
            )

        def page() -> dict[str, Any]:
            status, body, _ = request("/api/v1/earthquakes")
            assert status == 200
            return cast(dict[str, Any], json.loads(body))

        publish(fixture)
        wait_for(lambda: len(page()["items"]) == 2, "Fixture did not reach the API")
        before = page()
        stream = LocalHTTPS(APP, https_port, context=context, timeout=20)
        stream.request(
            "GET", f"/api/v1/earthquakes/stream?after={before['latest_change_cursor']}"
        )
        sse = stream.getresponse()
        assert sse.status == 200 and "text/event-stream" in (
            sse.getheader("Content-Type") or ""
        )
        assert sse.readline() == b": connected\n"
        revised = json.loads(json.dumps(fixture))
        revised["features"] = [revised["features"][0]]
        revised["features"][0]["properties"]["lastupdate"] = "2026-10-03T18:00:00Z"
        revised["features"][0]["properties"]["mag"] = 2.4
        publish(revised)
        frame = b""
        while b'"magnitude":2.4' not in frame:
            line = sse.readline()
            assert line, "SSE disconnected before the committed revision"
            frame += line
        stream.close()
        assert b"event: earthquake" in frame
        record(
            "Fixture crossed containerized Kafka/PostgreSQL/API; committed revision arrived through HTTPS SSE"
        )
        compose.run("stop", "processor")
        processor = compose.run("ps", "--all", "-q", "processor").decode().strip()
        exit_code = (
            subprocess.check_output(
                ["docker", "inspect", "--format", "{{.State.ExitCode}}", processor]
            )
            .decode()
            .strip()
        )
        assert exit_code == "0"
        record("Processor handled Docker's stop signal and exited cleanly")

        print("Recreating containers with their persistent volumes...", flush=True)
        compose.run("down", timeout=180)
        compose.run("up", "-d", "--wait", "--wait-timeout", "180", timeout=300)
        https_port = int(
            compose.run("port", "web", "8443").decode().strip().rsplit(":", 1)[1]
        )
        assert len(page()["items"]) == 2 and page()["latest_change_cursor"] == 3
        publish(revised)

        # Wait for processor's committed metric rather than an arbitrary delay.
        def replay_committed() -> bool:
            code = "import urllib.request; print(urllib.request.urlopen('http://processor:9101/metrics').read().decode())"
            metrics = compose.run("exec", "-T", "api", "python", "-c", code).decode()
            return 'seismic_processor_records_total{outcome="committed"} 1.0' in metrics

        wait_for(replay_committed, "Replayed revision was not committed")
        assert len(page()["items"]) == 2 and page()["latest_change_cursor"] == 3
        record(
            "Container recreation preserved data and TLS CA; replay kept two rows and cursor 3"
        )

        archive = work / "seismic.dump"
        backup(compose, archive)
        try:
            backup(compose, archive)
        except FileExistsError:
            pass
        else:
            raise AssertionError("Backup overwrote an existing archive")
        try:
            restore(compose, archive, "seismic")
        except ValueError:
            pass
        else:
            raise AssertionError("Restore accepted the running database")
        restore(compose, archive, "seismic_restore_check")
        query = "SELECT event_id, magnitude, change_cursor FROM earthquake_events ORDER BY event_id; SELECT last_cursor FROM earthquake_change_clock; SELECT version_num FROM alembic_version;"

        def snapshot(database: str) -> bytes:
            return compose.run(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "seismic_admin",
                "-d",
                database,
                "-Atc",
                query,
            )

        assert snapshot("seismic") == snapshot("seismic_restore_check")
        record(
            "Binary PostgreSQL backup restored into a new database with matching events, cursor and schema version"
        )
        code = "import urllib.request; print(urllib.request.urlopen('http://prometheus:9090/api/v1/query?query=seismic_api_database_ready').read().decode())"
        wait_for(
            lambda: (
                '"1"' in compose.run("exec", "-T", "api", "python", "-c", code).decode()
            ),
            "Prometheus did not scrape containerized API",
        )
        record("Prometheus scraped API database readiness across the container network")
        report = {"completed_at": datetime.now(UTC).isoformat(), "checks": evidence}
        (rehearsal_root / "last-report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        print(
            "Deployment rehearsal passed. Evidence: deploy/.rehearsal/last-report.json",
            flush=True,
        )
    except BaseException:
        if started:
            compose.run("logs", "--tail", "30", capture=False)
        raise
    finally:
        if started:
            compose.run("down", "--volumes", "--remove-orphans", timeout=180)
        # Only remove this run's verified directory and unique Compose project.
        resolved = work.resolve()
        assert resolved.is_relative_to(
            rehearsal_root.resolve()
        ) and resolved.name.startswith("run-")
        shutil.rmtree(resolved)


if __name__ == "__main__":
    main()
