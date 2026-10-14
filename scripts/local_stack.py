"""Start the whole persistent local platform with one command."""

import argparse
import os
import secrets
import subprocess
from pathlib import Path

from deployment_support import ROOT, Compose

STATE = ROOT / "deploy" / ".local"
ENV_FILE = STATE / "stack.env"
PROJECT = "seismic-local"


def public_mapbox_token() -> str:
    if token := os.getenv("VITE_MAPBOX_ACCESS_TOKEN"):
        return token
    local_env = ROOT / "frontend" / ".env.local"
    if local_env.exists():
        for line in local_env.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.strip().removeprefix("export ").partition("=")
            if separator and key.strip() == "VITE_MAPBOX_ACCESS_TOKEN":
                return value.strip().strip("\"'")
    return ""


def saved_password(name: str) -> Path:
    path = STATE / name
    if not path.exists():
        with path.open("x", encoding="utf-8") as output:
            output.write(secrets.token_urlsafe(32))
        path.chmod(0o644)
    return path


def prepare() -> None:
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    values = {
        "APP_DOMAIN": "localhost",
        "GRAFANA_DOMAIN": "localhost",
        "TLS_ISSUER": "internal",
        "BIND_ADDRESS": "127.0.0.1",
        "BACKEND_IMAGE": "seismic-backend:local",
        "WEB_IMAGE": "seismic-web:local",
    }
    for key, name in (
        ("POSTGRES_PASSWORD_FILE", "postgres_password"),
        ("POSTGRES_ADMIN_PASSWORD_FILE", "postgres_admin_password"),
        ("GRAFANA_ADMIN_PASSWORD_FILE", "grafana_admin_password"),
        ("GRAFANA_SECRET_KEY_FILE", "grafana_secret_key"),
    ):
        values[key] = saved_password(name).as_posix()
    gateway_password = saved_password("grafana_gateway_password")
    gateway_auth = STATE / "grafana_gateway_auth"
    if not gateway_auth.exists():
        caddy_image = next(
            line.split()[1]
            for line in (ROOT / "frontend" / "Dockerfile").read_text().splitlines()
            if line.startswith("FROM caddy:")
        )
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
                input=gateway_password.read_bytes() + b"\n",
                stdout=subprocess.PIPE,
                check=True,
                timeout=180,
            )
            .stdout.decode()
            .strip()
        )
        gateway_auth.write_text(
            f"basic_auth {{\n observer {hashed}\n}}\n", encoding="utf-8"
        )
        gateway_auth.chmod(0o644)
    values["GRAFANA_GATEWAY_AUTH_FILE"] = gateway_auth.as_posix()
    ENV_FILE.write_text(
        "".join(f"{key}='{value}'\n" for key, value in values.items()), encoding="utf-8"
    )
    access = STATE / "access.txt"
    access.write_text(
        "Frontend: http://localhost:8080\nGrafana: http://localhost:3000\n"
        "Prometheus: http://localhost:9090\n\n"
        "Grafana gateway username: observer\n"
        f"Grafana gateway password: {gateway_password.read_text()}\n\n"
        "Grafana login username: admin\n"
        f"Grafana login password: {(STATE / 'grafana_admin_password').read_text()}\n",
        encoding="utf-8",
    )
    access.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["start", "stop", "status"], nargs="?", default="start"
    )
    args = parser.parse_args()
    compose = Compose(ENV_FILE, PROJECT, (ROOT / "deploy" / "compose.local.yaml",))
    if args.action == "start":
        subprocess.run(
            ["docker", "info"], stdout=subprocess.DEVNULL, check=True, timeout=20
        )
        print("Preparing local settings and building the app...", flush=True)
        prepare()
        token = public_mapbox_token()
        if token and not token.startswith("pk."):
            raise ValueError(
                "Use a public Mapbox token beginning with pk. in frontend/.env.local"
            )
        # BuildKit receives this public browser setting from the environment;
        # passwords remain mounted files and never enter the build context.
        os.environ["VITE_MAPBOX_ACCESS_TOKEN"] = token
        compose.run("config", "--quiet")
        compose.run("build", "api", "web", timeout=1200, capture=False)
        compose.run(
            "--profile",
            "live",
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            "180",
            timeout=300,
            capture=False,
        )
        print(
            "\nFrontend: http://localhost:8080\nGrafana: http://localhost:3000\n"
            "Prometheus: http://localhost:9090"
        )
        print(f"Grafana credentials: {STATE / 'access.txt'}")
        if not token:
            print(
                "Add your public Mapbox token to frontend/.env.local and rerun to enable the map."
            )
        print(
            "Live feed and catalogue recovery are running. Data persists between starts."
        )
    elif not ENV_FILE.exists():
        raise SystemExit("Start the platform first: python scripts/local_stack.py")
    elif args.action == "stop":
        compose.run("--profile", "live", "stop", capture=False)
        print("Stopped. Containers, credentials and data are retained.")
    else:
        compose.run("--profile", "live", "ps", "--all", capture=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        OSError,
        ValueError,
    ) as error:
        raise SystemExit(
            f"Local startup failed: {error}. Check Docker Desktop and ports 8080/3000."
        ) from None
