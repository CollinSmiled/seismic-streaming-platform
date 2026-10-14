"""Build a connection URL from a mounted password, then exec the service."""

import os
import sys
from pathlib import Path
from urllib.parse import quote

if password_file := os.getenv("DATABASE_PASSWORD_FILE"):
    password = Path(password_file).read_text(encoding="utf-8").rstrip("\r\n")
    os.environ["DATABASE_URL"] = (
        f"postgresql://{quote(os.environ['DATABASE_USER'], safe='')}:"
        f"{quote(password, safe='')}@{os.environ['DATABASE_HOST']}:"
        f"{os.getenv('DATABASE_PORT', '5432')}/"
        f"{quote(os.environ['DATABASE_NAME'], safe='')}?connect_timeout=5"
    )

if len(sys.argv) < 2:
    raise SystemExit("A service command is required")
os.execvp(sys.argv[1], sys.argv[1:])
