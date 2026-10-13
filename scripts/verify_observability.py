"""Smoke-check the running Prometheus and Grafana provisioning."""

from __future__ import annotations

import base64
import json
import os
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def get_json(url: str, *, basic_auth: bool = False) -> dict[str, object]:
    headers = {}
    if basic_auth:
        credentials = (
            f"{os.getenv('GRAFANA_ADMIN_USER', 'admin')}:"
            f"{os.getenv('GRAFANA_ADMIN_PASSWORD', 'local-dev-only')}"
        )
        token = base64.b64encode(credentials.encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    with urlopen(Request(url, headers=headers), timeout=5) as response:
        return json.load(response)  # type: ignore[no-any-return]


def main() -> None:
    prometheus_port = os.getenv("PROMETHEUS_PORT", "9090")
    grafana_port = os.getenv("GRAFANA_PORT", "3000")
    prometheus = f"http://127.0.0.1:{prometheus_port}"
    grafana = f"http://127.0.0.1:{grafana_port}"
    deadline = time.monotonic() + 90
    while True:
        try:
            targets = get_json(f"{prometheus}/api/v1/targets")
            active = targets["data"]["activeTargets"]  # type: ignore[index]
            api_targets = [
                target
                for target in active
                if target["labels"].get("job") == "seismic-api"
            ]
            if api_targets and api_targets[0]["health"] == "up":
                break
        except (OSError, KeyError, TypeError):
            pass
        if time.monotonic() > deadline:
            raise RuntimeError("Prometheus did not scrape the API successfully")
        time.sleep(2)

    database_query = 'seismic_api_database_ready{job="seismic-api"}'
    database = get_json(
        f"{prometheus}/api/v1/query?{urlencode({'query': database_query})}"
    )
    samples = database["data"]["result"]  # type: ignore[index]
    if len(samples) != 1 or samples[0]["value"][1] != "1":
        raise RuntimeError("API database readiness metric is not healthy")

    rules = get_json(f"{prometheus}/api/v1/rules")
    names = {
        rule["name"]
        for group in rules["data"]["groups"]  # type: ignore[index]
        for rule in group["rules"]
    }
    required = {
        "SeismicTargetDown",
        "SeismicWorkerUnready",
        "SeismicApiDatabaseUnavailable",
        "SeismicWorkerRepeatedFailures",
        "SeismicReconciliationStalled",
    }
    if not required <= names:
        raise RuntimeError(f"Missing active alert rules: {required - names}")

    while True:
        try:
            dashboard = get_json(
                f"{grafana}/api/dashboards/uid/seismic-platform", basic_auth=True
            )["dashboard"]
            break
        except OSError:
            if time.monotonic() > deadline:
                raise RuntimeError("Grafana dashboard did not become available") from None
            time.sleep(2)
    panels = dashboard["panels"]  # type: ignore[index]
    if len(panels) != 7:
        raise RuntimeError("Grafana dashboard did not provision all seven panels")
    for panel in panels:
        for target in panel["targets"]:
            expression = target["expr"]
            response = get_json(
                f"{prometheus}/api/v1/query?{urlencode({'query': expression})}"
            )
            if response["status"] != "success":
                raise RuntimeError(f"Invalid dashboard query: {expression}")
    print(
        "Prometheus scraped the API; five alerts and seven panel queries are active"
    )


if __name__ == "__main__":
    main()
