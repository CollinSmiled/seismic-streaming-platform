"""Shared argument-safe Docker Compose invocation for deployment tools."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Compose:
    def __init__(self, env_file: Path, project: str) -> None:
        self.command = [
            "docker",
            "compose",
            "--env-file",
            str(env_file.resolve()),
            "--project-name",
            project,
            "-f",
            str(ROOT / "deploy" / "compose.yaml"),
        ]

    def run(
        self,
        *args: str,
        timeout: int = 180,
        capture: bool = True,
        input_bytes: bytes | None = None,
    ) -> bytes:
        result = subprocess.run(
            [*self.command, *args],
            cwd=ROOT,
            check=True,
            timeout=timeout,
            input=input_bytes,
            stdout=subprocess.PIPE if capture else None,
        )
        return result.stdout or b""
